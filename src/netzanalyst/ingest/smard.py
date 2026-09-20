"""Download SMARD time series and load them into Postgres.

SMARD (smard.de, Bundesnetzagentur) publishes the data behind its charts as
JSON. There is no official, documented REST API; these are the endpoints the
website itself calls, catalogued by bundesAPI:
    https://github.com/bundesAPI/smard-api

    index:  /app/chart_data/{filter}/{region}/index_{resolution}.json
            -> {"timestamps": [epoch_ms, ...]}   one entry per week-chunk
    data:   /app/chart_data/{filter}/{region}/{filter}_{region}_{res}_{ts}.json
            -> {"meta_data": {...}, "series": [[epoch_ms, value|null], ...]}

Because it is unofficial it can change without notice. Every response is
validated before it reaches the database, and the loader is idempotent, so a
re-run after a breakage is always safe.

Licence: SMARD data is CC BY 4.0 — attribution required. See data/README.md.

Usage
    python data/ingest/smard.py --from 2024-01-01 --to 2025-12-31
    python data/ingest/smard.py --from 2024-01-01 --to 2024-01-31 --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

BASE_URL = "https://www.smard.de/app/chart_data"
REGION = "DE"
RESOLUTION = "hour"
USER_AGENT = "netzanalyst/0.1 (portfolio project; +https://github.com/deekshavishnoi/netzanalyst)"

log = logging.getLogger("smard")


def _ssl_context() -> ssl.SSLContext:
    """TLS context with a working CA bundle.

    Python installed from python.org on macOS ships without a usable CA store
    until "Install Certificates.command" is run, which makes every HTTPS call
    fail with CERTIFICATE_VERIFY_FAILED. Prefer certifi's bundle when it is
    importable so the script works on a stock install; fall back to the system
    default otherwise. Verification is never disabled.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()


@dataclass(frozen=True)
class Series:
    """One SMARD filter mapped onto a destination table."""

    filter_id: int
    table: str  # generation | consumption | price
    key_column: str  # source | metric | bidding_zone
    key_value: str


# Mirrors sql/001_schema.sql. Keep the two in step.
GENERATION = [
    Series(1223, "generation", "source", "lignite"),
    Series(1224, "generation", "source", "nuclear"),
    Series(1225, "generation", "source", "wind_offshore"),
    Series(1226, "generation", "source", "hydro"),
    Series(1227, "generation", "source", "other_conventional"),
    Series(1228, "generation", "source", "other_renewable"),
    Series(4066, "generation", "source", "biomass"),
    Series(4067, "generation", "source", "wind_onshore"),
    Series(4068, "generation", "source", "solar"),
    Series(4069, "generation", "source", "hard_coal"),
    Series(4070, "generation", "source", "pumped_storage"),
    Series(4071, "generation", "source", "natural_gas"),
]

CONSUMPTION = [
    Series(410, "consumption", "metric", "total_load"),
    Series(4359, "consumption", "metric", "residual_load"),
    Series(4387, "consumption", "metric", "pumped_storage_consumption"),
]

PRICE = [
    Series(4169, "price", "bidding_zone", "DE-LU"),
]

ALL_SERIES = GENERATION + CONSUMPTION + PRICE

# A plausibility band per table, in the series' own units. A value outside the
# band means the upstream format changed (a unit switch, or an error page
# parsed as data) and we would rather fail loudly than poison the database.
SANITY_BOUNDS = {
    "generation": (-5_000.0, 120_000.0),  # MWh/h
    "consumption": (-40_000.0, 120_000.0),  # MWh/h; residual load can be negative
    "price": (-1_000.0, 5_000.0),  # EUR/MWh; negative prices are normal
}


def fetch_json(url: str, *, retries: int = 4, timeout: int = 30) -> dict[str, Any]:
    """GET a URL and parse JSON, retrying on transient failures."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                payload: Any = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"{url} returned {type(payload).__name__}, expected a JSON object"
                )
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise  # a missing chunk is a real answer, not a blip
            backoff = 2**attempt
            log.warning("fetch failed (%s), retry %d/%d in %ds", exc, attempt + 1, retries, backoff)
            time.sleep(backoff)
    raise RuntimeError(f"giving up on {url}") from last


def chunk_timestamps(filter_id: int) -> list[int]:
    """Week-start timestamps (epoch ms) SMARD has data for."""
    url = f"{BASE_URL}/{filter_id}/{REGION}/index_{RESOLUTION}.json"
    payload = fetch_json(url)
    stamps = payload.get("timestamps")
    if not isinstance(stamps, list) or not stamps:
        raise RuntimeError(f"index for filter {filter_id} has no timestamps: {payload!r:.200}")
    return sorted(int(t) for t in stamps)


def fetch_chunk(filter_id: int, chunk_ms: int) -> list[tuple[dt.datetime, float | None]]:
    """One week of hourly points for a filter. Returns [(ts_utc, value)]."""
    url = f"{BASE_URL}/{filter_id}/{REGION}/{filter_id}_{REGION}_{RESOLUTION}_{chunk_ms}.json"
    payload = fetch_json(url)
    series = payload.get("series")
    if not isinstance(series, list):
        raise RuntimeError(f"chunk {filter_id}/{chunk_ms}: 'series' missing or not a list")

    rows: list[tuple[dt.datetime, float | None]] = []
    for point in series:
        if not (isinstance(point, list) and len(point) == 2):
            raise RuntimeError(f"chunk {filter_id}/{chunk_ms}: bad point {point!r}")
        epoch_ms, value = point
        ts = dt.datetime.fromtimestamp(int(epoch_ms) / 1000, tz=dt.timezone.utc)
        rows.append((ts, None if value is None else float(value)))
    return rows


def check_sanity(table: str, rows: list[tuple[dt.datetime, float | None]], label: str) -> None:
    lo, hi = SANITY_BOUNDS[table]
    for ts, value in rows:
        if value is not None and not (lo <= value <= hi):
            raise RuntimeError(
                f"{label} at {ts.isoformat()}: value {value} outside plausible "
                f"range [{lo}, {hi}] for table '{table}'. Upstream format may have "
                f"changed — check the SMARD response before loading."
            )


def parse_date(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)


def load(
    conn: psycopg.Connection[Any],
    series: Series,
    rows: list[tuple[dt.datetime, float | None]],
    chunk_ms: int,
) -> int:
    """Upsert one chunk. Idempotent: re-running overwrites with fresh values."""
    value_col = "eur_per_mwh" if series.table == "price" else "mwh"
    sql = (
        f"INSERT INTO {series.table} (ts, {series.key_column}, {value_col}) "
        f"VALUES (%s, %s, %s) "
        f"ON CONFLICT (ts, {series.key_column}) DO UPDATE SET {value_col} = EXCLUDED.{value_col}"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, [(ts, series.key_value, value) for ts, value in rows])
        cur.execute(
            "INSERT INTO ingest_log (smard_filter_id, region, resolution, chunk_start, row_count) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (smard_filter_id, region, resolution, chunk_start) "
            "DO UPDATE SET row_count = EXCLUDED.row_count, fetched_at = now()",
            (
                series.filter_id,
                REGION,
                RESOLUTION,
                dt.datetime.fromtimestamp(chunk_ms / 1000, tz=dt.timezone.utc),
                len(rows),
            ),
        )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--from", dest="date_from", required=True, help="inclusive start date, YYYY-MM-DD"
    )
    ap.add_argument("--to", dest="date_to", required=True, help="inclusive end date, YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="fetch and validate, write nothing")
    ap.add_argument("--only", help="comma-separated filter ids, e.g. 4068,410")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    start, end = parse_date(args.date_from), parse_date(args.date_to)
    if start > end:
        log.error("--from must not be after --to")
        return 2
    # --to is an inclusive calendar day, so the half-open upper bound is the
    # midnight after it. Dates are interpreted as UTC, matching SMARD's own
    # timestamps; calendar-in-Berlin filtering happens in the SQL views.
    end_exclusive = end + dt.timedelta(days=1)

    wanted = ALL_SERIES
    if args.only:
        ids = {int(x) for x in args.only.split(",")}
        wanted = [s for s in ALL_SERIES if s.filter_id in ids]
        if not wanted:
            log.error("no series match --only %s", args.only)
            return 2

    conn = None
    if not args.dry_run:
        try:
            import psycopg
        except ImportError:
            log.error("psycopg is not installed. Run: pip install -r data/ingest/requirements.txt")
            return 3
        url = os.environ.get("DATABASE_URL")
        if not url:
            log.error("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
            return 3
        conn = psycopg.connect(url)

    total = 0
    try:
        for series in wanted:
            label = f"{series.key_value} (filter {series.filter_id})"
            try:
                stamps = chunk_timestamps(series.filter_id)
            except Exception as exc:
                log.error("%s: could not read index: %s", label, exc)
                return 4

            # A chunk starting before `start` can still contain wanted hours,
            # so keep the last chunk that begins at or before the start date.
            selected = [
                t for t in stamps if start.timestamp() * 1000 <= t <= end.timestamp() * 1000
            ]
            earlier = [t for t in stamps if t < start.timestamp() * 1000]
            if earlier:
                selected.insert(0, earlier[-1])
            if not selected:
                log.warning("%s: no chunks in range", label)
                continue

            loaded = 0
            for chunk_ms in selected:
                rows = fetch_chunk(series.filter_id, chunk_ms)
                rows = [(ts, v) for ts, v in rows if start <= ts < end_exclusive]
                if not rows:
                    continue
                check_sanity(series.table, rows, label)
                if conn is not None:
                    loaded += load(conn, series, rows, chunk_ms)
                else:
                    loaded += len(rows)
                time.sleep(0.2)  # be polite to a public service

            if conn is not None:
                conn.commit()
            total += loaded
            log.info("%-34s %6d rows", label, loaded)
    finally:
        if conn is not None:
            conn.close()

    verb = "would load" if args.dry_run else "loaded"
    log.info("%s %d rows across %d series", verb, total, len(wanted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
