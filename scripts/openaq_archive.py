#!/usr/bin/env python3
"""Archive publique OpenAQ (AWS S3) : plan, téléchargement, conversion Silver, publication.

Source : bucket public `openaq-data-archive`, un fichier gzip par emplacement et par jour :
    records/csv.gz/locationid=<id>/year=<AAAA>/month=<MM>/location-<id>-<AAAAMMJJ>.csv.gz
Colonnes : location_id, sensor_id (ou sensors_id), location, datetime (ISO 8601 avec décalage),
lat, lon, parameter, unit (ou units), value. Les noms varient selon les fichiers : les deux
orthographes sont gérées. Les fichiers sont écrits 72 h après la fin de la journée : les 3 derniers
jours ne sont jamais dans l'archive (la collecte API les couvre).

Années par défaut : 2022 à 2026. Les emplacements viennent de l'API OpenAQ (clé OPENAQ_API_KEY),
autour des villes de config/cities.yml, ou de --location-ids. Pour borner le volume, seuls les
`--max-locations-per-city` emplacements les plus complets (défaut 5) sont retenus.

Exemples :
    python scripts/openaq_archive.py --dry-run                      # plan et volumes, rien n'est téléchargé
    python scripts/openaq_archive.py --years 2025                   # télécharge 2025
    python scripts/openaq_archive.py --silver                       # télécharge puis convertit en Silver
    python scripts/openaq_archive.py --location-ids 2696 --years 2025 --dry-run

Les fichiers téléchargés sont des données externes : ils sont seulement décompressés et lus par
pandas, jamais exécutés.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
S3_BASE = os.getenv("OPENAQ_ARCHIVE_BASE", "https://openaq-data-archive.s3.amazonaws.com")
PREFIX = "records/csv.gz"
END_YEAR = 2026
YEARS_BACK = 5
TARGET = {"pm25", "pm10", "no2", "o3", "co"}
ALIASES = {"sensors_id": "sensor_id", "units": "unit", "latitude": "lat", "longitude": "lon"}
REQUIRED = {"location_id", "datetime", "parameter", "value"}
MICRO = {"µg/m³", "μg/m³", "ug/m3", "µg/m3", "μg/m3"}
UNIT_FACTORS = {  # identiques à src/openaq_pipeline.py (UNIT_FACTORS_TO_UG_M3)
    "ppm": {"no2": 1880.0, "o3": 1960.0, "co": 1145.0},
    "ppb": {"no2": 1.880, "o3": 1.960, "co": 1.145},
}
LOG = logging.getLogger("urbanhub.openaq_archive")


class InvalidArchiveFile(Exception):
    """Fichier de la bonne taille mais illisible ou sans les colonnes attendues."""


def default_years(end_year: int = END_YEAR, count: int = YEARS_BACK) -> list[int]:
    return list(range(end_year - count + 1, end_year + 1))


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "UrbanHub-Archive/1.0 (projet etudiant)"})
    return session


def get_with_retry(session: requests.Session, url: str, *, stream: bool = False, attempts: int = 5) -> requests.Response:
    """GET avec reprise sur 429 et 5xx (Retry-After respecté, plafonné à 5 minutes)."""
    for attempt in range(1, attempts + 1):
        response = session.get(url, stream=stream, timeout=(10, 120))
        if response.status_code in {429, 503} or response.status_code >= 500:
            wait = response.headers.get("Retry-After", "")
            pause = min(int(wait), 300) if wait.isdigit() else 2 ** attempt
            LOG.warning("HTTP %s sur %s, nouvelle tentative dans %s s (%d/%d)", response.status_code, url, pause, attempt, attempts)
            response.close()
            time.sleep(pause)
            continue
        return response
    raise RuntimeError(f"Échec répété sur {url}")


def list_prefix(session: requests.Session, prefix: str) -> list[dict[str, Any]]:
    """Liste S3 (ListObjectsV2, sans identifiants) avec pagination."""
    items, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        response = get_with_retry(session, f"{S3_BASE}/?{urlencode(params)}")
        response.raise_for_status()
        xml = response.text
        for block in re.findall(r"<Contents>(.*?)</Contents>", xml, flags=re.S):
            key = re.search(r"<Key>([^<]+)</Key>", block)
            size = re.search(r"<Size>(\d+)</Size>", block)
            if key and size:
                items.append({"key": key.group(1), "size": int(size.group(1))})
        nxt = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if "<IsTruncated>true</IsTruncated>" in xml and nxt:
            token = nxt.group(1)
        else:
            return items


def discover_locations(max_per_city: int) -> list[dict[str, Any]]:
    """Emplacements OpenAQ autour des villes (API v3), les plus complets d'abord."""
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from src.openaq_pipeline import OpenAQClient, discover_city_sensors

    cities = yaml.safe_load((ROOT / "config" / "cities.yml").read_text(encoding="utf-8"))["cities"]
    _, catalog = discover_city_sensors(OpenAQClient(), cities)
    grouped: dict[int, dict[str, Any]] = {}
    for entry in catalog:
        loc = grouped.setdefault(entry["location_id"], {
            "location_id": entry["location_id"], "city_id": entry["city_id"], "city_name": entry["city_name"],
            "location_name": entry["location_name"], "locality": entry.get("locality") or "",
            "latitude": entry["latitude"], "longitude": entry["longitude"], "pollutants": set(),
            "datetime_last": entry.get("datetime_last") or ""})
        loc["pollutants"].add(entry["pollutant"])
    chosen = []
    for city in {g["city_id"] for g in grouped.values()}:
        # Les plus complets d'abord (nombre de polluants cibles), puis les plus récents.
        mine = sorted((g for g in grouped.values() if g["city_id"] == city),
                      key=lambda g: (len(g["pollutants"]), g["datetime_last"]), reverse=True)
        chosen.extend(mine[:max_per_city])
    for g in chosen:
        g["pollutants"] = sorted(g["pollutants"])
    return sorted(chosen, key=lambda g: (g["city_id"], g["location_id"]))


def explicit_locations(ids: list[int]) -> list[dict[str, Any]]:
    return [{"location_id": i, "city_id": "inconnue", "city_name": "Inconnue", "location_name": f"location {i}",
             "locality": "", "latitude": 0.0, "longitude": 0.0, "pollutants": []} for i in ids]


def build_plan(session: requests.Session, locations: list[dict[str, Any]], years: list[int]) -> dict[str, Any]:
    pattern = re.compile(r"location-(\d+)-(\d{4})(\d{2})(\d{2})\.csv\.gz$")
    files, empty = [], []
    for loc in locations:
        for year in years:
            items = list_prefix(session, f"{PREFIX}/locationid={loc['location_id']}/year={year}/")
            found = 0
            for item in items:
                m = pattern.search(item["key"])
                if m:
                    found += 1
                    files.append({"location_id": loc["location_id"], "year": int(m.group(2)), "month": int(m.group(3)),
                                  "day": int(m.group(4)), "key": item["key"], "size": item["size"],
                                  "url": f"{S3_BASE}/{item['key']}"})
            if not found:
                empty.append((loc["location_id"], year))
    files.sort(key=lambda f: (f["location_id"], f["year"], f["month"], f["day"]))
    return {"locations": locations, "years": years, "files": files, "empty": empty,
            "total_bytes": sum(f["size"] for f in files)}


def local_path(root: Path, entry: dict[str, Any]) -> Path:
    return root / entry["key"]


def human(size: int) -> str:
    return f"{size / 1e6:,.1f} Mo" if size < 1e9 else f"{size / 1e9:.2f} Go"


def print_plan(plan: dict[str, Any]) -> None:
    print(f"Années : {plan['years'][0]} à {plan['years'][-1]} | emplacements : {len(plan['locations'])}")
    by_city: dict[str, list[int]] = {}
    for loc in plan["locations"]:
        by_city.setdefault(loc["city_id"], []).append(loc["location_id"])
    for city, ids in sorted(by_city.items()):
        mine = [f for f in plan["files"] if f["location_id"] in ids]
        print(f"  {city:8s} emplacements {ids} : {len(mine):6,d} fichiers, {human(sum(f['size'] for f in mine))}")
    per_year = {y: sum(1 for f in plan["files"] if f["year"] == y) for y in plan["years"]}
    print("Fichiers par année :", per_year)
    if plan["empty"]:
        print(f"Emplacements sans fichier une année donnée : {len(plan['empty'])} (ex. {plan['empty'][:4]})")
    print(f"Total : {len(plan['files']):,} fichiers, {human(plan['total_bytes'])}")


def validate_file(path: Path) -> dict[str, Any]:
    """Décompresse l'en-tête et vérifie les colonnes attendues (orthographes alternatives incluses)."""
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            # Depuis 2023, l'en-tête est entre guillemets ("location_id","sensors_id",...) : csv.reader les retire.
            header = [c.strip().lower() for c in next(csv.reader([handle.readline()]), [])]
            rows = sum(1 for _ in handle)
    except (OSError, EOFError, UnicodeDecodeError, csv.Error) as error:
        raise InvalidArchiveFile(str(error)) from error
    columns = {ALIASES.get(c, c) for c in header}
    missing = REQUIRED - columns
    if missing:
        raise InvalidArchiveFile(f"colonnes absentes : {sorted(missing)}")
    return {"rows": rows}


def download_one(session: requests.Session, root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    target = local_path(root, entry)
    result = {k: entry[k] for k in ("location_id", "year", "month", "day", "key", "size")}
    if target.exists() and target.stat().st_size == entry["size"]:
        return {**result, "status": "cached"}
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        response = get_with_retry(session, entry["url"], stream=True)
        response.raise_for_status()
        with part.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                handle.write(chunk)
        if part.stat().st_size != entry["size"]:
            raise ValueError(f"taille {part.stat().st_size} au lieu de {entry['size']}")
        info = validate_file(part)
        part.replace(target)
        return {**result, "status": "downloaded", **info}
    except InvalidArchiveFile as error:
        part.unlink(missing_ok=True)
        LOG.error("Fichier invalide %s : %s", entry["key"], error)
        return {**result, "status": "invalid", "error": str(error)}
    except (requests.RequestException, OSError, ValueError, RuntimeError) as error:
        part.unlink(missing_ok=True)
        LOG.error("Échec %s : %s", entry["key"], error)
        return {**result, "status": "error", "error": str(error)}


def normalise_unit(unit: str, parameter: str, value: float) -> tuple[float, str] | None:
    """Même règle que le Silver en direct : µg/m³ ; ppm et ppb convertis ; autres unités écartées."""
    if unit in MICRO:
        return value, "µg/m³"
    factor = UNIT_FACTORS.get(unit, {}).get(parameter)
    return (value * factor, "µg/m³") if factor else None


def to_silver(root: Path, plan: dict[str, Any], results: list[dict[str, Any]], shift_hours: float = 0.0) -> dict[int, Path]:
    """Convertit les fichiers valides en tables Silver annuelles (mêmes colonnes que le Silver en direct)."""
    by_loc = {l["location_id"]: l for l in plan["locations"]}
    frames: dict[int, list[pd.DataFrame]] = {}
    for item in results:
        if item["status"] not in {"downloaded", "cached"}:
            continue
        df = pd.read_csv(local_path(root, item), compression="gzip")
        df.columns = [ALIASES.get(c.lower(), c.lower()) for c in df.columns]
        df["parameter"] = df["parameter"].astype(str).str.lower()
        df = df[df["parameter"].isin(TARGET)].copy()
        if df.empty:
            continue
        converted = [normalise_unit(str(u), p, v) for u, p, v in zip(df.get("unit", ""), df["parameter"], df["value"])]
        df = df.assign(_c=converted)
        df = df[df["_c"].notna()]
        df["value"] = [c[0] for c in df["_c"]]
        df["unit"] = "µg/m³"
        df = df[(df["value"] >= 0) & ~((df["parameter"].isin(["pm25", "pm10", "no2", "o3"])) & (df["value"] > 5000))
                & ~((df["parameter"] == "co") & (df["value"] > 200000))]
        loc = by_loc[item["location_id"]]
        ts = pd.to_datetime(df["datetime"], utc=True, errors="coerce") + pd.Timedelta(hours=shift_hours)
        out = pd.DataFrame({
            "sensor_id": df["sensor_id"].astype(str) if "sensor_id" in df else "", "location_id": int(item["location_id"]),
            "location_name": loc["location_name"], "locality": loc["locality"], "pollutant": df["parameter"],
            "timestamp_utc": ts, "latitude": df["lat"] if "lat" in df else loc["latitude"],
            "longitude": df["lon"] if "lon" in df else loc["longitude"], "value": df["value"], "unit": "µg/m³",
            "city_id": loc["city_id"], "city_name": loc["city_name"],
        }).dropna(subset=["timestamp_utc"])
        frames.setdefault(item["year"], []).append(out)
    written = {}
    for year, parts in sorted(frames.items()):
        table = pd.concat(parts, ignore_index=True).drop_duplicates(["sensor_id", "timestamp_utc"])
        table["date_traitement_utc"] = datetime.now(timezone.utc).isoformat()
        target = root / "silver" / f"year={year}" / "pollution_archive.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        table.sort_values(["city_id", "location_id", "timestamp_utc"]).to_parquet(target, index=False)
        written[year] = target
        LOG.info("Silver %d : %s lignes", year, f"{len(table):,}")
    return written


def publish(root: Path, results: list[dict[str, Any]], silver: dict[int, Path]) -> int:
    try:
        from citybikes_stream import build_minio_client, ensure_bucket
    except ImportError:
        from scripts.citybikes_stream import build_minio_client, ensure_bucket
    client, buckets = build_minio_client()
    ensure_bucket(client, buckets["bronze"])
    ensure_bucket(client, buckets["silver"])
    def send(item: dict[str, Any]) -> int:
        client.fput_object(buckets["bronze"], f"openaq-archive/{item['key']}", str(local_path(root, item)),
                           content_type="application/gzip")
        return 1

    # 21 000 petits objets : envoi en parallèle (le client MinIO est sûr pour les threads)
    with ThreadPoolExecutor(max_workers=8) as pool:
        sent = sum(pool.map(send, [i for i in results if i["status"] in {"downloaded", "cached"}]))
    for year, path in silver.items():
        client.fput_object(buckets["silver"], f"pollution-archive/year={year}/pollution_archive.parquet", str(path),
                           content_type="application/x-parquet")
        sent += 1
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", help="années (défaut : 2022 à 2026)")
    parser.add_argument("--location-ids", type=int, nargs="+", help="emplacements OpenAQ explicites (sans appel à l'API)")
    parser.add_argument("--max-locations-per-city", type=int, default=5, help="emplacements retenus par ville (défaut 5)")
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "openaq-archive")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true", help="plan et volumes seulement, aucun téléchargement")
    parser.add_argument("--silver", action="store_true", help="convertit les fichiers téléchargés en tables Silver annuelles")
    parser.add_argument("--shift-hours", type=float, default=-1.0, help="décalage appliqué à l'horodatage ; l'archive donne la FIN de période, -1 donne le début comme le Silver en direct (la transformation scripts/archives_to_gold.py l'applique par défaut)")
    parser.add_argument("--upload", action="store_true", help="publie Bronze (openaq-archive/) et Silver (pollution-archive/)")
    parser.add_argument("--max-files", type=int, default=30000, help="refuse de télécharger au-delà de ce nombre de fichiers")
    parser.add_argument("--max-gb", type=float, default=1.0, help="refuse de publier au-delà de ce volume")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    years = sorted(set(args.years)) if args.years else default_years()
    locations = explicit_locations(args.location_ids) if args.location_ids else discover_locations(args.max_locations_per_city)
    session = build_session()
    plan = build_plan(session, locations, years)
    print_plan(plan)
    if args.dry_run or not plan["files"]:
        return 0
    if len(plan["files"]) > args.max_files:
        print(f"Téléchargement refusé : {len(plan['files']):,} fichiers dépassent --max-files {args.max_files:,}. "
              "Réduire --years ou --max-locations-per-city, ou relever la limite en connaissance de cause.")
        return 2
    if args.upload and plan["total_bytes"] > args.max_gb * 1e9:
        print(f"Publication refusée : {human(plan['total_bytes'])} dépasse --max-gb {args.max_gb}.")
        return 2

    args.root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda e: download_one(session, args.root, e), plan["files"]))
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("downloaded", "cached", "error", "invalid")}
    silver = to_silver(args.root, plan, results, args.shift_hours) if args.silver else {}
    manifest = {"generated_utc": datetime.now(timezone.utc).isoformat(), "source": S3_BASE, "years": years,
                "locations": [{k: v for k, v in l.items()} for l in locations], "counts": counts, "files": results}
    (args.root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("Résultat :", counts)
    if args.upload:
        print("Objets publiés :", publish(args.root, results, silver))
    return 1 if counts["error"] or counts["invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
