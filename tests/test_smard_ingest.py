"""Tests for the SMARD loader's pure logic.

Network calls and database writes are not exercised here; they are covered by
the `--dry-run` path in CI and by the cross-validation recorded in
docs/data-sources.md.
"""

import datetime as dt

import pytest

from netzanalyst.ingest.smard import ALL_SERIES, SANITY_BOUNDS, check_sanity, parse_date


def test_series_registry_matches_schema_expectations() -> None:
    # Every series must target a table that has a sanity band defined.
    for series in ALL_SERIES:
        assert series.table in SANITY_BOUNDS, f"{series.key_value} targets unknown table"

    # Filter IDs are the primary key upstream and must be unique.
    ids = [s.filter_id for s in ALL_SERIES]
    assert len(ids) == len(set(ids)), "duplicate SMARD filter id"


def test_generation_sources_cover_the_twelve_smard_categories() -> None:
    generation = [s for s in ALL_SERIES if s.table == "generation"]
    assert len(generation) == 12


def test_parse_date_returns_utc() -> None:
    parsed = parse_date("2025-07-01")
    assert parsed.tzinfo is dt.timezone.utc
    assert (parsed.year, parsed.month, parsed.day) == (2025, 7, 1)


def test_check_sanity_accepts_plausible_values() -> None:
    now = dt.datetime.now(tz=dt.timezone.utc)
    check_sanity("generation", [(now, 45_000.0)], "solar")
    # Negative prices are real and must not be rejected.
    check_sanity("price", [(now, -50.0)], "DE-LU")
    # NULLs are allowed: recent hours are often not yet published.
    check_sanity("generation", [(now, None)], "solar")


def test_check_sanity_rejects_an_implausible_value() -> None:
    now = dt.datetime.now(tz=dt.timezone.utc)
    # A unit change upstream (MW -> kW) would look like this.
    with pytest.raises(RuntimeError, match="outside plausible range"):
        check_sanity("generation", [(now, 45_000_000.0)], "solar")
