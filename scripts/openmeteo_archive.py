#!/usr/bin/env python3
"""Météo Open-Meteo 2022 à 2026 avec visibilité : téléchargement parallèle, Silver et table horaire.

Pourquoi un second script : le Gold partagé (scripts/openmeteo_batch.py, modèle ecmwf_ifs) n'a de
visibilité qu'à partir de fin 2025. Deux API gratuites se complètent :
  * Historical Weather (ERA5)  : température, vent, direction, pression, précipitation. Pas de
    visibilité, décalage d'environ 6 jours.
  * Historical Forecast        : les mêmes variables et la **visibilité**, du 1er janvier 2022 à hier.
Les valeurs ERA5 sont prioritaires ; l'autre API comble la visibilité et les derniers jours.

Sorties (dossier data/openmeteo-archive/, sans toucher au Gold partagé) :
    bronze/openmeteo-archive/<api>/city=<id>/year=AAAA.json     réponses brutes
    silver/weather_openmeteo_archive/year=AAAA/weather_hourly.parquet
    gold/weather_hourly_visibility.parquet                      même contrat que kpis/weather_hourly
Précipitation : Open-Meteo donne le cumul de l'heure précédente ; la table horaire la range sur
l'heure de début [T-1 h, T[, comme le Gold partagé. Le Silver garde la valeur brute.

Exemples :
    python scripts/openmeteo_archive.py --dry-run          # plan et nombre de requêtes, aucun appel
    python scripts/openmeteo_archive.py                    # 2022 à 2026, dans data/openmeteo-archive/
    python scripts/openmeteo_archive.py --years 2025 --upload

Données Open-Meteo.com, licence CC BY 4.0, usage non commercial (https://open-meteo.com).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = os.getenv("OPENMETEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive")
FORECAST_URL = os.getenv("OPENMETEO_FORECAST_URL", "https://historical-forecast-api.open-meteo.com/v1/forecast")
FORECAST_START = date(2022, 1, 1)
ARCHIVE_LAG_DAYS = 6
END_YEAR = 2026
YEARS_BACK = 5
VARIABLES = {
    "temperature_2m": "temperature", "wind_speed_10m": "wind_speed", "wind_direction_10m": "wind_direction",
    "pressure_msl": "pressure", "visibility": "visibility", "precipitation": "precipitation",
}
MEASURES = list(VARIABLES.values())
LOG = logging.getLogger("urbanhub.openmeteo_archive")


def default_years(end_year: int = END_YEAR, count: int = YEARS_BACK) -> list[int]:
    return list(range(end_year - count + 1, end_year + 1))


def load_cities() -> list[dict[str, Any]]:
    cities = yaml.safe_load((ROOT / "config" / "cities.yml").read_text(encoding="utf-8"))["cities"]
    return [{"id": c["id"], "latitude": c["latitude"], "longitude": c["longitude"]} for c in cities]


def build_jobs(cities: list[dict[str, Any]], years: list[int], today: date | None = None) -> list[dict[str, Any]]:
    """Une requête par ville, année et API, bornée à ce que l'API sait servir (aucune requête vide)."""
    today = today or datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    archive_end = today - timedelta(days=ARCHIVE_LAG_DAYS)
    jobs = []
    for city in cities:
        for year in years:
            first, last = date(year, 1, 1), min(date(year, 12, 31), yesterday)
            for api, url, lo, hi in (
                ("archive", ARCHIVE_URL, first, min(last, archive_end)),
                ("historical_forecast", FORECAST_URL, max(first, FORECAST_START), last),
            ):
                if lo <= hi:
                    jobs.append({"api": api, "url": url, "city": city, "year": year, "start": lo, "end": hi})
    return jobs


def fetch_json(session: requests.Session, url: str, params: dict[str, Any], attempts: int = 5) -> dict[str, Any]:
    """GET JSON ; reprise sur 429 et 5xx avec attente croissante (Retry-After respecté)."""
    for attempt in range(1, attempts + 1):
        response = session.get(url, params=params, timeout=(10, 120))
        if response.status_code == 429 or response.status_code >= 500:
            wait = response.headers.get("Retry-After", "")
            pause = min(int(wait), 120) if wait.isdigit() else min(15 * attempt, 90)
            LOG.warning("HTTP %s sur %s, nouvelle tentative dans %s s (%d/%d)", response.status_code, url, pause, attempt, attempts)
            response.close()
            time.sleep(pause)
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} : {response.text[:160]}")
        return response.json()
    raise RuntimeError(f"Échec répété sur {url}")


def download(session: requests.Session, root: Path, job: dict[str, Any]) -> dict[str, Any]:
    city = job["city"]
    rel = f"bronze/openmeteo-archive/{job['api']}/city={city['id']}/year={job['year']}.json"
    path = root / rel
    entry = {"api": job["api"], "city_id": city["id"], "year": job["year"], "path": rel,
             "start": job["start"].isoformat(), "end": job["end"].isoformat()}
    if path.exists():
        return {**entry, "status": "cached", "bytes": path.stat().st_size}
    try:
        payload = fetch_json(session, job["url"], {
            "latitude": city["latitude"], "longitude": city["longitude"], "start_date": entry["start"],
            "end_date": entry["end"], "hourly": ",".join(VARIABLES), "wind_speed_unit": "ms", "timezone": "UTC"})
        hourly = payload["hourly"]
        if not hourly.get("time"):
            raise ValueError("réponse sans heures")
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as error:
        LOG.error("Échec %s %s %s : %s", job["api"], city["id"], job["year"], error)
        return {**entry, "status": "error", "error": str(error)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return {**entry, "status": "downloaded", "bytes": path.stat().st_size}


def decode(path: Path) -> pd.DataFrame:
    hourly = json.loads(path.read_text(encoding="utf-8"))["hourly"]
    frame = pd.DataFrame({"timestamp_utc": pd.to_datetime(hourly["time"], utc=True)})
    for source, target in VARIABLES.items():
        frame[target] = pd.to_numeric(pd.Series(hourly.get(source)), errors="coerce")
    return frame.set_index("timestamp_utc")


def merge_city_year(archive: pd.DataFrame | None, forecast: pd.DataFrame | None) -> pd.DataFrame:
    """ERA5 d'abord ; historical_forecast comble les valeurs absentes (visibilité, derniers jours)."""
    frames = [f for f in (archive, forecast) if f is not None]
    merged = frames[0]
    for other in frames[1:]:
        merged = merged.combine_first(other)
    return merged.dropna(how="all").reset_index().sort_values("timestamp_utc")


def hourly_table(silver: pd.DataFrame) -> pd.DataFrame:
    """Contrat de kpis/weather_hourly : hour_utc, mesures, précipitation rangée sur l'heure de début."""
    # La valeur reçue à T est le cumul de [T-1 h, T[ : elle est rattachée à l'heure T-1 par jointure
    # (et non par décalage de ligne, qui se tromperait au moindre trou dans la série).
    rain = silver[["city_id", "timestamp_utc", "precipitation"]].copy()
    rain["hour_utc"] = rain["timestamp_utc"] - pd.Timedelta(hours=1)
    out = silver.drop(columns=["precipitation"]).rename(columns={"timestamp_utc": "hour_utc"}).merge(
        rain[["city_id", "hour_utc", "precipitation"]], on=["city_id", "hour_utc"], how="left")
    out["source"] = "open-meteo"
    out["weather_model"] = "era5+historical_forecast"
    return out[["city_id", "hour_utc"] + MEASURES + ["source", "weather_model"]]


def publish(root: Path, results: list[dict[str, Any]], silver: dict[int, Path]) -> int:
    try:
        from citybikes_stream import build_minio_client, ensure_bucket
    except ImportError:
        from scripts.citybikes_stream import build_minio_client, ensure_bucket
    client, buckets = build_minio_client()
    ensure_bucket(client, buckets["bronze"])
    ensure_bucket(client, buckets["silver"])
    sent = 0
    for item in results:
        if item["status"] in {"downloaded", "cached"}:
            client.fput_object(buckets["bronze"], item["path"].removeprefix("bronze/"), str(root / item["path"]),
                               content_type="application/json")
            sent += 1
    for year, path in silver.items():
        client.fput_object(buckets["silver"], f"weather_openmeteo_archive/year={year}/weather_hourly.parquet", str(path),
                           content_type="application/x-parquet")
        sent += 1
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", help="années (défaut : 2022 à 2026)")
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "openmeteo-archive")
    parser.add_argument("--workers", type=int, default=3, help="requêtes simultanées (défaut 3)")
    parser.add_argument("--dry-run", action="store_true", help="plan et nombre de requêtes, aucun appel réseau")
    parser.add_argument("--upload", action="store_true", help="publie Bronze (openmeteo-archive/) et Silver (weather_openmeteo_archive/)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    years = sorted(set(args.years)) if args.years else default_years()
    cities = load_cities()
    jobs = build_jobs(cities, years)
    skipped = [y for y in years if y < FORECAST_START.year]
    print(f"Années {years[0]} à {years[-1]} | villes : {', '.join(c['id'] for c in cities)} | {len(jobs)} requêtes "
          f"({sum(j['api'] == 'archive' for j in jobs)} ERA5, {sum(j['api'] == 'historical_forecast' for j in jobs)} historical_forecast)")
    if skipped:
        print(f"Avant 2022, la visibilité n'existe dans aucune des deux API : années {skipped} sans visibilité.")
    if args.dry_run or not jobs:
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "UrbanHub-Archive/1.0 (projet etudiant)"})
    args.root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda j: download(session, args.root, j), jobs))
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("downloaded", "cached", "error")}
    print("Téléchargement :", counts)
    if counts["error"]:
        print("Erreurs : relancer la commande, les fichiers déjà complets ne sont pas retéléchargés.")
        return 1

    by_key = {(r["city_id"], r["year"], r["api"]): args.root / r["path"] for r in results}
    per_year: dict[int, list[pd.DataFrame]] = {}
    for city in cities:
        for year in years:
            a, f = by_key.get((city["id"], year, "archive")), by_key.get((city["id"], year, "historical_forecast"))
            if not a and not f:
                continue
            merged = merge_city_year(decode(a) if a else None, decode(f) if f else None)
            merged.insert(0, "city_id", city["id"]); merged.insert(1, "station_id", f"openmeteo-{city['id']}")
            per_year.setdefault(year, []).append(merged)
    silver_paths: dict[int, Path] = {}
    all_silver = []
    for year, parts in sorted(per_year.items()):
        table = pd.concat(parts, ignore_index=True)
        target = args.root / "silver" / "weather_openmeteo_archive" / f"year={year}" / "weather_hourly.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(target, index=False)
        silver_paths[year] = target
        all_silver.append(table)
        print(f"Silver {year} : {len(table):,} lignes, visibilité sur {int(table['visibility'].notna().sum()):,}")
    gold = hourly_table(pd.concat(all_silver, ignore_index=True).sort_values(["city_id", "timestamp_utc"]))
    gold_path = args.root / "gold" / "weather_hourly_visibility.parquet"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold.to_parquet(gold_path, index=False)
    print(f"Table horaire : {len(gold):,} lignes, {gold['hour_utc'].min():%Y-%m-%d} à {gold['hour_utc'].max():%Y-%m-%d}, "
          f"visibilité sur {int(gold['visibility'].notna().sum()):,} heures")
    (args.root / "manifest.json").write_text(json.dumps({"generated_utc": datetime.now(timezone.utc).isoformat(),
                                                         "years": years, "files": results}, indent=2), encoding="utf-8")
    if args.upload:
        print("Objets publiés :", publish(args.root, results, silver_paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
