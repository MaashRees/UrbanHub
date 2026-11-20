#!/usr/bin/env python3
"""Transforme l'archive mensuelle CityBikes en Silver horaire.

Les fichiers source sont des Parquet mensuels publiés par CityBikes :
    https://data.citybik.es/dumps/by-network/<annee>/<AAAAMM>-<reseau>-stats.parquet

Exemples :
    python scripts/citybikes_archive.py --dry-run
    python scripts/citybikes_archive.py --years 2025 --networks vlille
    python scripts/citybikes_archive.py --years 2025 --upload

Le script lit le schéma au moment de la transformation et accepte les noms de
colonnes usuels de l'archive. Il ne fabrique pas de données pour les mois absents.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("CITYBIKES_ARCHIVE_BASE", "https://data.citybik.es/dumps/by-network")
ATTRIBUTION = "Bike-share data by CityBikes contributors and available from https://data.citybik.es"
LOG = logging.getLogger("urbanhub.citybikes_archive")


def configured_networks() -> list[str]:
    config = ROOT / "config" / "cities.yml"
    cities = yaml.safe_load(config.read_text(encoding="utf-8"))["cities"]
    return sorted({city["citybikes_network_id"] for city in cities})


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "UrbanHub-Archive/1.0", "Accept": "application/json, */*"})
    return session


def get(session: requests.Session, url: str, *, stream: bool = False) -> requests.Response:
    response = session.get(url, stream=stream, timeout=(10, 120))
    if response.status_code == 429:
        raise RuntimeError(f"Rate limit CityBikes archive sur {url}; relancer plus tard")
    response.raise_for_status()
    return response


def build_plan(session: requests.Session, years: list[int], networks: list[str]) -> list[dict[str, Any]]:
    pattern = re.compile(r"^(\d{4})(\d{2})-(.+)-stats\.parquet$")
    entries: list[dict[str, Any]] = []
    for year in years:
        response = session.get(f"{BASE_URL}/{year}/", timeout=(10, 30))
        if response.status_code == 404:
            LOG.warning("Année absente de l'archive : %s", year)
            continue
        response.raise_for_status()
        for item in response.json():
            match = pattern.match(item.get("name", ""))
            if not match or match.group(3) not in networks or item.get("type") != "file":
                continue
            entries.append(
                {
                    "year": int(match.group(1)),
                    "month": int(match.group(2)),
                    "network": match.group(3),
                    "name": item["name"],
                    "size": int(item.get("size", 0)),
                    "url": f"{BASE_URL}/{year}/{item['name']}",
                }
            )
    return sorted(entries, key=lambda item: (item["year"], item["month"], item["network"]))


def local_path(root: Path, entry: dict[str, Any]) -> Path:
    return root / str(entry["year"]) / entry["name"]


def download_one(session: requests.Session, root: Path, entry: dict[str, Any]) -> Path:
    target = local_path(root, entry)
    if target.exists() and target.stat().st_size == entry["size"]:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    response = get(session, entry["url"], stream=True)
    try:
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        if partial.stat().st_size != entry["size"]:
            raise ValueError(f"taille inattendue pour {entry['name']}")
        # Vérification légère : le fichier doit être lisible comme Parquet.
        pd.read_parquet(partial, engine="pyarrow", columns=[])
        partial.replace(target)
        return target
    finally:
        response.close()
        partial.unlink(missing_ok=True)


def find_column(frame: pd.DataFrame, candidates: tuple[str, ...], required: bool = True) -> str | None:
    lowered = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    if required:
        raise ValueError(f"Colonne absente. Candidates={candidates}; colonnes={list(frame.columns)}")
    return None


def parse_timestamp(values: pd.Series) -> pd.Series:
    """Parse les timestamps texte ou epoch en UTC sans supposer une unité unique."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() > 0.8 and numeric.notna().any():
        magnitude = numeric.dropna().abs().median()
        unit = "s" if magnitude < 1e11 else "ms" if magnitude < 1e14 else "us" if magnitude < 1e17 else "ns"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(values, utc=True, errors="coerce")


def normalize_archive(frame: pd.DataFrame, network: str) -> pd.DataFrame:
    """Mappe le schéma source vers le contrat Silver du flux direct."""
    timestamp_column = find_column(frame, ("timestamp", "datetime", "date", "time", "last_updated"))
    station_column = find_column(frame, ("station_id", "station", "id", "uid"))
    bikes_column = find_column(frame, ("free_bikes", "bikes_available", "bikes"))
    slots_column = find_column(frame, ("empty_slots", "free_slots", "slots"))
    name_column = find_column(frame, ("station_name", "name"), required=False)
    latitude_column = find_column(frame, ("latitude", "lat"), required=False)
    longitude_column = find_column(frame, ("longitude", "lon", "lng"), required=False)

    data = pd.DataFrame(
        {
            "network_id": network,
            "station_id": frame[station_column].astype(str),
            "station_name": frame[name_column] if name_column else pd.NA,
            "latitude": frame[latitude_column] if latitude_column else pd.NA,
            "longitude": frame[longitude_column] if longitude_column else pd.NA,
            "bikes_available": pd.to_numeric(frame[bikes_column], errors="coerce"),
            "free_slots": pd.to_numeric(frame[slots_column], errors="coerce"),
            "observed_at_utc": parse_timestamp(frame[timestamp_column]),
        }
    )
    data = data.dropna(subset=["station_id", "observed_at_utc"])
    data["snapshot_minute_utc"] = data["observed_at_utc"].dt.floor("min").astype(str)
    data["city_id"] = {"velib": "paris", "velov": "lyon", "vlille": "lille"}.get(network, network)
    data["city_name"] = data["city_id"].map({"paris": "Paris", "lyon": "Lyon", "lille": "Lille"})
    return data.sort_values(["station_id", "observed_at_utc"]).drop_duplicates(
        ["network_id", "station_id", "observed_at_utc"], keep="last"
    )


def to_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    """Produit un état horaire par station via dernier état connu puis forward-fill."""
    value_columns = ["station_name", "latitude", "longitude", "bikes_available", "free_slots"]
    outputs: list[pd.DataFrame] = []
    keys = ["city_id", "city_name", "network_id", "station_id"]
    for key_values, station in frame.groupby(keys, dropna=False):
        station = station.sort_values("observed_at_utc").set_index("observed_at_utc")
        hourly = station[value_columns].resample("1h").last().ffill()
        for key, value in zip(keys, key_values):
            hourly[key] = value
        hourly = hourly.reset_index().rename(columns={"observed_at_utc": "hour_utc"})
        hourly["observed_at_utc"] = hourly["hour_utc"]
        hourly["snapshot_minute_utc"] = hourly["hour_utc"].astype(str)
        outputs.append(hourly)
    if not outputs:
        return pd.DataFrame()
    columns = ["city_id", "city_name", "network_id", "station_id", "station_name", "latitude", "longitude",
               "bikes_available", "free_slots", "observed_at_utc", "snapshot_minute_utc", "hour_utc"]
    return pd.concat(outputs, ignore_index=True)[columns].sort_values(["city_id", "station_id", "hour_utc"])


def transform(files: list[Path], output_root: Path) -> list[Path]:
    outputs: list[Path] = []
    for year in sorted({int(path.parent.name) for path in files}):
        year_frames: list[pd.DataFrame] = []
        for path in files:
            if int(path.parent.name) != year:
                continue
            network = path.name.split("-", 2)[1]
            LOG.info("Lecture du schéma réel : %s", path)
            year_frames.append(normalize_archive(pd.read_parquet(path), network))
        hourly = to_hourly(pd.concat(year_frames, ignore_index=True))
        destination = output_root / "silver" / f"year={year}" / "citybikes_stations_hourly.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        hourly.to_parquet(destination, index=False, engine="pyarrow", compression="snappy")
        outputs.append(destination)
        LOG.info("Silver historique %s : %d lignes", destination, len(hourly))
    return outputs


def publish(files: list[Path], archive_root: Path) -> None:
    from scripts.citybikes_stream import build_minio_client, ensure_bucket, minio_object_name, upload_file

    client, buckets = build_minio_client()
    for bucket in buckets.values():
        ensure_bucket(client, bucket)
    # Les Parquet bruts vont en Bronze ; les séries horaires vont en Silver.
    for path in files:
        object_name = f"citybikes/archive/raw/year={path.parent.name}/{path.name}"
        upload_file(client, buckets["bronze"], path, object_name)
    for path in sorted((archive_root / "silver").glob("year=*/citybikes_stations_hourly.parquet")):
        object_name = f"citybikes/archive/silver/{path.parent.name}/{path.name}"
        upload_file(client, buckets["silver"], path, object_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", default=[2025])
    parser.add_argument("--networks", nargs="+", default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "citybikes-archive")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    networks = args.networks or configured_networks()
    session = build_session()
    plan = build_plan(session, sorted(set(args.years)), networks)
    total_mb = sum(item["size"] for item in plan) / 1e6
    print(f"Plan : {len(plan)} fichiers, {total_mb:.1f} Mo, réseaux={','.join(networks)}")
    if args.dry_run:
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        local_files = list(pool.map(lambda entry: download_one(session, args.output, entry), plan))
    (args.output / "manifest.json").write_text(
        json.dumps({"generated_utc": datetime.now(timezone.utc).isoformat(), "files": [str(p) for p in local_files]}, indent=2),
        encoding="utf-8",
    )
    silver_files = transform(local_files, args.output)
    if args.upload:
        publish(local_files, args.output)
    print(f"Transformation terminée : {len(silver_files)} Silver historique(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
