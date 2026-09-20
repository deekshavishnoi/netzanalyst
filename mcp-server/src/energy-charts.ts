/**
 * Client for the Energy-Charts API (Fraunhofer ISE).
 *
 * Used for recent data that is not in the Postgres snapshot yet. The database
 * holds the bulk SMARD history; this covers "what happened yesterday".
 *
 * API: https://api.energy-charts.info/  (OpenAPI at /openapi.json)
 * Licence: CC BY 4.0, attribution "energy-charts.info". The licence string is
 * returned in every response and is passed through to the caller.
 */

import { config } from "./config.js";

/** Shape of GET /v2/public_power, verified against the live API. */
interface PublicPowerResponse {
  schema_version: string;
  country: string;
  timezone: string;
  resolution: string;
  interval_minutes: number;
  unit: string;
  available_from: string;
  available_until: string;
  license: string;
  deprecated: boolean;
  series: { id: string; name: string }[];
  data: { timestamp: string; values: Record<string, number | null> }[];
}

export interface EnergyChartsResult {
  source: "energy-charts.info (Fraunhofer ISE)";
  licence: string;
  country: string;
  timezone: string;
  unit: string;
  resolution: string;
  availableFrom: string;
  availableUntil: string;
  /** Totals per production type over the requested window, in MWh. */
  totalsMwh: Record<string, number>;
  /** Hourly averages, to keep the payload small enough for a model context. */
  hourly: { timestamp: string; values: Record<string, number> }[];
  note: string;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export class EnergyChartsError extends Error {}

export async function fetchEnergyCharts(
  start: string,
  end: string,
  country = "de",
): Promise<EnergyChartsResult> {
  if (!DATE_RE.test(start) || !DATE_RE.test(end)) {
    throw new EnergyChartsError("start and end must be dates in YYYY-MM-DD form.");
  }
  if (start > end) {
    throw new EnergyChartsError("start must not be after end.");
  }

  const spanDays =
    (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000;
  if (spanDays > 31) {
    throw new EnergyChartsError(
      `Range is ${spanDays} days. This tool covers recent periods only; ask for at most 31 days, ` +
        `or query the database for longer history.`,
    );
  }

  const url = new URL("/v2/public_power", config.energyChartsBaseUrl);
  url.searchParams.set("country", country);
  url.searchParams.set("start", start);
  url.searchParams.set("end", end);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  let payload: PublicPowerResponse;
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { accept: "application/json", "user-agent": "netzanalyst/0.1" },
    });
    if (!response.ok) {
      throw new EnergyChartsError(
        `Energy-Charts returned HTTP ${response.status} ${response.statusText}.`,
      );
    }
    payload = (await response.json()) as PublicPowerResponse;
  } catch (error) {
    if (error instanceof EnergyChartsError) throw error;
    if ((error as Error).name === "AbortError") {
      throw new EnergyChartsError("Energy-Charts did not respond within 30 seconds.");
    }
    throw new EnergyChartsError(`Could not reach Energy-Charts: ${(error as Error).message}`);
  } finally {
    clearTimeout(timer);
  }

  if (!Array.isArray(payload.data) || !Array.isArray(payload.series)) {
    throw new EnergyChartsError(
      "Unexpected response shape from Energy-Charts; the API contract may have changed.",
    );
  }

  const intervalHours = (payload.interval_minutes ?? 15) / 60;

  // Totals in MWh: values are MW over an interval of interval_minutes.
  const totals: Record<string, number> = {};
  for (const point of payload.data) {
    for (const [key, value] of Object.entries(point.values ?? {})) {
      if (value === null || !Number.isFinite(value)) continue;
      totals[key] = (totals[key] ?? 0) + value * intervalHours;
    }
  }
  for (const key of Object.keys(totals)) {
    totals[key] = Math.round(totals[key]! * 100) / 100;
  }

  // Downsample to hourly means. A month of 15-minute data across ~20 production
  // types is far too much to put in front of a model.
  const buckets = new Map<string, { sums: Record<string, number>; n: number }>();
  for (const point of payload.data) {
    const hourKey = point.timestamp.slice(0, 13);
    let bucket = buckets.get(hourKey);
    if (!bucket) {
      bucket = { sums: {}, n: 0 };
      buckets.set(hourKey, bucket);
    }
    bucket.n += 1;
    for (const [key, value] of Object.entries(point.values ?? {})) {
      if (value === null || !Number.isFinite(value)) continue;
      bucket.sums[key] = (bucket.sums[key] ?? 0) + value;
    }
  }

  const hourly = [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([hourKey, bucket]) => {
      const values: Record<string, number> = {};
      for (const [key, sum] of Object.entries(bucket.sums)) {
        values[key] = Math.round((sum / bucket.n) * 100) / 100;
      }
      return { timestamp: `${hourKey}:00`, values };
    });

  return {
    source: "energy-charts.info (Fraunhofer ISE)",
    licence: payload.license ?? "CC BY 4.0, attribution: energy-charts.info",
    country: payload.country ?? country,
    timezone: payload.timezone ?? "Europe/Berlin",
    unit: payload.unit ?? "MW",
    resolution: payload.resolution ?? "unknown",
    availableFrom: payload.available_from ?? start,
    availableUntil: payload.available_until ?? end,
    totalsMwh: totals,
    hourly,
    note:
      "totalsMwh is energy in MWh over the requested window. hourly values are " +
      "mean power in MW for each hour, downsampled from the API's " +
      `${payload.interval_minutes ?? 15}-minute resolution. Negative values mean net consumption ` +
      "(for example pumped storage) or net export for cross-border trading.",
  };
}
