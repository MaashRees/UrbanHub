#!/usr/bin/env python3
"""Archives mensuelles CityBikes (data.citybik.es) : plan, téléchargement, publication.

Source : https://data.citybik.es/dumps/by-network/<année>/<AAAAMM>-<réseau>-stats.parquet
Un fichier Parquet par réseau et par mois : historique des changements d'état des stations.
Licence ODbL ; mention obligatoire : « Bike-share data by CityBikes contributors and available
from https://data.citybik.es ». Service « expérimental, sans garantie » : les conditions des
opérateurs (Vélib', Vélo'v, V'Lille) peuvent aussi s'appliquer.

Les réseaux viennent de config/cities.yml (velib, velov, vlille). Par défaut, les 5 dernières
années jusqu'en 2026 (2022 à 2026). L'archive ne commence qu'en novembre 2024 : les années
absentes sont signalées dans le plan, pas inventées.

Exemples :
    python scripts/citybikes_archive.py --dry-run           # plan et volumes, aucun téléchargement
    python scripts/citybikes_archive.py                     # télécharge dans data/citybikes-archive/
    python scripts/citybikes_archive.py --years 2025 --networks velov
    python scripts/citybikes_archive.py --upload --max-gb 2 # publie aussi dans le bucket Bronze

Les fichiers téléchargés sont des données externes : ils sont lus uniquement par pyarrow
(métadonnées et colonnes), jamais exécutés.
"""

from __future__ import annotations

import argparse
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

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("CITYBIKES_ARCHIVE_BASE", "https://data.citybik.es/dumps/by-network")
END_YEAR = 2026
YEARS_BACK = 5
ATTRIBUTION = "Bike-share data by CityBikes contributors and available from https://data.citybik.es"
LOG = logging.getLogger("urbanhub.citybikes_archive")


class InvalidParquet(Exception):
    """Fichier téléchargé de la bonne taille mais illisible comme Parquet."""


def default_years(end_year: int = END_YEAR, count: int = YEARS_BACK) -> list[int]:
    """Les `count` dernières années jusqu'à `end_year` incluse (2022 à 2026)."""
    return list(range(end_year - count + 1, end_year + 1))


def configured_networks(config: Path = ROOT / "config" / "cities.yml") -> list[str]:
    cities = yaml.safe_load(config.read_text(encoding="utf-8"))["cities"]
    return sorted({c["citybikes_network_id"] for c in cities})


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "UrbanHub-Archive/1.0 (projet etudiant)", "Accept": "application/json, */*"})
    return session


def get_with_retry(session: requests.Session, url: str, *, stream: bool = False, attempts: int = 5,
                   timeout: tuple[int, int] = (10, 120)) -> requests.Response:
    """GET avec reprise sur erreurs serveur ; un 429 respecte Retry-After (plafonné à 5 minutes)."""
    for attempt in range(1, attempts + 1):
        response = session.get(url, stream=stream, timeout=timeout)
        if response.status_code == 429 or response.status_code >= 500:
            wait = response.headers.get("Retry-After", "")
            pause = min(int(wait), 300) if wait.isdigit() else 2 ** attempt
            LOG.warning("HTTP %s sur %s, nouvelle tentative dans %s s (%d/%d)", response.status_code, url, pause, attempt, attempts)
            response.close()
            time.sleep(pause)
            continue
        return response
    raise RuntimeError(f"Échec répété sur {url}")


def list_year(session: requests.Session, year: int) -> list[dict[str, Any]] | None:
    """Liste JSON des fichiers d'une année, ou None si l'année n'existe pas dans l'archive (404)."""
    response = get_with_retry(session, f"{BASE_URL}/{year}/")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def build_plan(session: requests.Session, years: list[int], networks: list[str]) -> dict[str, Any]:
    """Fichiers disponibles pour les réseaux et années demandés, et ce qui manque."""
    pattern = re.compile(r"^(\d{4})(\d{2})-(" + "|".join(re.escape(n) for n in networks) + r")-stats\.parquet$")
    files, missing_years = [], []
    for year in years:
        listing = list_year(session, year)
        if listing is None:
            missing_years.append(year)
            continue
        for item in listing:
            match = pattern.match(item.get("name", ""))
            if match and item.get("type") == "file":
                files.append({"year": int(match.group(1)), "month": int(match.group(2)), "network": match.group(3),
                              "name": item["name"], "size": int(item.get("size", 0)),
                              "url": f"{BASE_URL}/{year}/{item['name']}"})
    files.sort(key=lambda f: (f["network"], f["year"], f["month"]))
    absent = {}
    for network in networks:
        have = {(f["year"], f["month"]) for f in files if f["network"] == network}
        if have:
            first, last = min(have), max(have)
            absent[network] = [f"{y}{m:02d}" for y in years for m in range(1, 13) if first <= (y, m) <= last and (y, m) not in have]
        else:
            absent[network] = []
    return {"years": years, "networks": networks, "files": files, "missing_years": missing_years,
            "gaps": absent, "total_bytes": sum(f["size"] for f in files)}


def local_path(root: Path, entry: dict[str, Any]) -> Path:
    return root / str(entry["year"]) / entry["name"]


def parquet_info(path: Path) -> dict[str, Any]:
    """Lecture des métadonnées Parquet seulement (aucune exécution de contenu)."""
    import pyarrow.parquet as pq

    # Fichier ouvert et refermé explicitement : sous Windows, un Parquet invalide laisserait sinon
    # le fichier verrouillé et impossible à supprimer.
    with path.open("rb") as handle:
        meta = pq.ParquetFile(handle).metadata
        return {"rows": meta.num_rows, "columns": [meta.schema.column(i).name for i in range(meta.num_columns)]}


def download_one(session: requests.Session, root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Télécharge un fichier vers un .part, vérifie la taille puis le Parquet, et renomme. Reprend si déjà complet."""
    target = local_path(root, entry)
    result = {k: entry[k] for k in ("year", "month", "network", "name", "size")}
    if target.exists() and target.stat().st_size == entry["size"]:
        return {**result, "status": "cached", **parquet_info(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    try:
        response = get_with_retry(session, entry["url"], stream=True)
        response.raise_for_status()
        with part.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
        if part.stat().st_size != entry["size"]:
            raise ValueError(f"taille {part.stat().st_size} au lieu de {entry['size']}")
        try:
            info = parquet_info(part)
        except Exception as error:  # Parquet illisible : fichier supprimé, jamais conservé
            raise InvalidParquet(str(error)) from error
        part.replace(target)
        return {**result, "status": "downloaded", **info}
    except InvalidParquet as error:
        part.unlink(missing_ok=True)
        LOG.error("Parquet invalide %s : %s", entry["name"], error)
        return {**result, "status": "invalid", "error": str(error)}
    except (requests.RequestException, OSError, ValueError, RuntimeError) as error:
        part.unlink(missing_ok=True)
        LOG.error("Échec %s : %s", entry["name"], error)
        return {**result, "status": "error", "error": str(error)}


def human(size: int) -> str:
    return f"{size / 1e6:,.0f} Mo" if size < 1e9 else f"{size / 1e9:.2f} Go"


def print_plan(plan: dict[str, Any]) -> None:
    print(f"Années demandées : {plan['years'][0]} à {plan['years'][-1]} | réseaux : {', '.join(plan['networks'])}")
    if plan["missing_years"]:
        print(f"Années absentes de l'archive (rien à télécharger) : {', '.join(map(str, plan['missing_years']))}")
    for network in plan["networks"]:
        mine = [f for f in plan["files"] if f["network"] == network]
        if not mine:
            print(f"  {network:8s} aucun fichier")
            continue
        gaps = plan["gaps"][network]
        print(f"  {network:8s} {len(mine):2d} fichiers, {mine[0]['year']}{mine[0]['month']:02d} à {mine[-1]['year']}{mine[-1]['month']:02d}, "
              f"{human(sum(f['size'] for f in mine))}" + (f" | mois manquants : {', '.join(gaps)}" if gaps else ""))
    print(f"Total : {len(plan['files'])} fichiers, {human(plan['total_bytes'])}")


def publish(root: Path, results: list[dict[str, Any]]) -> int:
    """Copie les fichiers valides vers le bucket Bronze (citybikes-archive/year=AAAA/...)."""
    try:
        from citybikes_stream import build_minio_client, ensure_bucket
    except ImportError:
        from scripts.citybikes_stream import build_minio_client, ensure_bucket
    client, buckets = build_minio_client()
    ensure_bucket(client, buckets["bronze"])
    sent = 0
    for item in results:
        if item["status"] not in {"downloaded", "cached"}:
            continue
        key = f"citybikes-archive/year={item['year']}/{item['name']}"
        client.fput_object(buckets["bronze"], key, str(local_path(root, item)), content_type="application/octet-stream")
        LOG.info("Publié : %s/%s", buckets["bronze"], key)
        sent += 1
    return sent


def publish_silver(paths: list[Path]) -> int:
    """Publie les Silver horaires (un fichier par réseau et par année) dans le bucket Silver existant.

    Clé : citybikes-archive/year=AAAA/citybikes_stations_hourly_<réseau>.parquet. Aucun objet existant n'est
    écrasé et aucun bucket n'est créé. Le Bronze brut (environ 950 Mo) n'est pas publié : il se retélécharge
    depuis la source publique.
    """
    try:
        from citybikes_stream import build_minio_client
    except ImportError:
        from scripts.citybikes_stream import build_minio_client
    client, buckets = build_minio_client()
    if not client.bucket_exists(buckets["silver"]):
        raise RuntimeError(f"Bucket {buckets['silver']} introuvable : vérifier MINIO_BUCKET_SILVER dans .env")
    sent = 0
    for path in paths:
        key = f"citybikes-archive/{path.parent.name}/{path.name}"
        try:
            client.stat_object(buckets["silver"], key)
            LOG.info("Déjà présent, ignoré : %s/%s", buckets["silver"], key)
            continue
        except Exception:
            pass
        client.fput_object(buckets["silver"], key, str(path), content_type="application/octet-stream")
        LOG.info("Publié : %s/%s", buckets["silver"], key)
        sent += 1
    return sent


def find_column(frame: pd.DataFrame, candidates: tuple[str, ...], required: bool = True) -> str | None:
    lowered = {str(column).lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    if required:
        raise ValueError(f"Colonne absente. Candidates={candidates}; colonnes={list(frame.columns)}")
    return None


def parse_timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() > 0.8 and numeric.notna().any():
        magnitude = numeric.dropna().abs().median()
        unit = "s" if magnitude < 1e11 else "ms" if magnitude < 1e14 else "us" if magnitude < 1e17 else "ns"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(values, utc=True, errors="coerce")


COLONNES_UTILES = ("timestamp", "datetime", "date", "time", "last_updated", "station_id", "station", "id", "uid",
                   "free_bikes", "bikes_available", "bikes", "empty_slots", "free_slots", "free", "slots",
                   "station_name", "name", "latitude", "lat", "longitude", "lon", "lng")
ETAT = ["bikes_available", "free_slots"]
STATIQUE = ["station_name", "latitude", "longitude"]
# Une station sans aucun relevé depuis plus de 72 h est considérée hors service : on ne la remplit plus
EXPIRATION = pd.Timedelta(hours=72)
SILVER_COLONNES = ["city_id", "city_name", "network_id", "station_id", "station_name", "latitude", "longitude",
                   "bikes_available", "free_slots", "observed_at_utc", "snapshot_minute_utc", "hour_utc"]


def normalize_archive(frame: pd.DataFrame, network: str) -> pd.DataFrame:
    """Mappe le schéma réel de l'archive (id, name, bikes, free, timestamp) vers le contrat Silver direct."""
    timestamp_column = find_column(frame, ("timestamp", "datetime", "date", "time", "last_updated"))
    station_column = find_column(frame, ("station_id", "station", "id", "uid"))
    bikes_column = find_column(frame, ("free_bikes", "bikes_available", "bikes"))
    slots_column = find_column(frame, ("empty_slots", "free_slots", "free", "slots"))
    name_column = find_column(frame, ("station_name", "name"), required=False)
    latitude_column = find_column(frame, ("latitude", "lat"), required=False)
    longitude_column = find_column(frame, ("longitude", "lon", "lng"), required=False)
    data = pd.DataFrame({
        "station_id": frame[station_column].astype(str),
        "station_name": frame[name_column] if name_column else pd.NA,
        "latitude": pd.to_numeric(frame[latitude_column], errors="coerce") if latitude_column else float("nan"),
        "longitude": pd.to_numeric(frame[longitude_column], errors="coerce") if longitude_column else float("nan"),
        "bikes_available": pd.to_numeric(frame[bikes_column], errors="coerce"),
        "free_slots": pd.to_numeric(frame[slots_column], errors="coerce"),
        "observed_at_utc": parse_timestamp(frame[timestamp_column]),
    })
    data = data.dropna(subset=["station_id", "observed_at_utc"])
    # Des valeurs négatives existent dans la source (4 lignes pour Vélib' 2025) : erreur de donnée, écartée.
    # Les grandes capacités (stations d'événements : festivals, hippodrome) sont réelles et conservées.
    data = data[(data["bikes_available"].fillna(0) >= 0) & (data["free_slots"].fillna(0) >= 0)]
    return data.sort_values(["station_id", "observed_at_utc"])


def hourly_month(frame: pd.DataFrame, network: str, carry: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """État horaire par station pour un mois : dernier état connu de l'heure, puis forward-fill.

    L'archive n'écrit une ligne que lorsque l'état d'une station change : le forward-fill est exact tant que
    le collecteur tournait. Les heures sans aucun relevé sur tout le réseau (panne de collecte) sont écartées,
    et une station silencieuse depuis plus de EXPIRATION n'est plus remplie. `carry` porte le dernier état connu
    du mois précédent ; la fonction renvoie aussi le `carry` à passer au mois suivant.
    """
    f = frame.assign(hour_utc=frame["observed_at_utc"].dt.floor("h")).sort_values("observed_at_utc")
    last = f.drop_duplicates(["station_id", "hour_utc"], keep="last")
    hours = pd.date_range(last["hour_utc"].min(), last["hour_utc"].max(), freq="h")
    observed_hours = pd.DatetimeIndex(last["hour_utc"].unique())

    if carry is None or carry.empty:
        carry = pd.DataFrame({**{c: pd.Series(dtype="float64") for c in ETAT}, **{c: pd.Series(dtype="object") for c in STATIQUE},
                              "last_obs": pd.Series(dtype=hours.dtype)}).rename_axis("station_id")
    alive = carry[carry["last_obs"] + EXPIRATION >= hours[0]]
    seed = alive.reset_index()[["station_id"] + ETAT].assign(hour_utc=hours[0])
    obs = pd.concat([seed, last[["station_id", "hour_utc"] + ETAT]], ignore_index=True)
    obs = obs.drop_duplicates(["station_id", "hour_utc"], keep="last")

    grid_index = pd.MultiIndex.from_product([obs["station_id"].unique(), hours], names=["station_id", "hour_utc"])
    grid = obs.set_index(["station_id", "hour_utc"])[ETAT].reindex(grid_index).groupby(level=0).ffill().dropna()
    grid = grid[grid.index.get_level_values("hour_utc").isin(observed_hours)]

    derniere_obs = last.groupby("station_id")["hour_utc"].max()
    derniere_obs = pd.concat([alive["last_obs"], derniere_obs]).groupby(level=0).max()
    limite = derniere_obs.reindex(grid.index.get_level_values("station_id")).to_numpy() + EXPIRATION
    grid = grid[grid.index.get_level_values("hour_utc").to_numpy() <= limite]

    statique = pd.concat([carry[STATIQUE], f.drop_duplicates("station_id", keep="last").set_index("station_id")[STATIQUE]])
    statique = statique[~statique.index.duplicated(keep="last")]
    out = grid.reset_index().merge(statique.reset_index(), on="station_id", how="left")
    city_id = {"velib": "paris", "velov": "lyon", "vlille": "lille"}.get(network, network)
    out["network_id"] = network
    out["city_id"] = city_id
    out["city_name"] = {"paris": "Paris", "lyon": "Lyon", "lille": "Lille"}.get(city_id, city_id)
    out["observed_at_utc"] = out["hour_utc"]
    out["snapshot_minute_utc"] = out["hour_utc"].astype(str)
    out = out[SILVER_COLONNES].sort_values(["station_id", "hour_utc"])

    dernier_etat = obs.sort_values("hour_utc").drop_duplicates("station_id", keep="last").set_index("station_id")[ETAT]
    new_carry = dernier_etat.join(statique).join(derniere_obs.rename("last_obs"))
    return out, new_carry


def transform_archive(root: Path, results: list[dict[str, Any]]) -> list[Path]:
    """Transforme les Parquet bruts valides en Silver horaire : un fichier par réseau et par année.

    Les mois sont traités un par un (sans la colonne JSON `extra`) et écrits au fur et à mesure : la mémoire
    reste bornée même pour Vélib'. Fichier : silver/year=AAAA/citybikes_stations_hourly_<réseau>.parquet
    """
    files = sorted((local_path(root, item) for item in results if item["status"] in {"downloaded", "cached"}),
                   key=lambda p: (p.name.split("-", 2)[1], p.name))
    outputs: list[Path] = []
    for network in sorted({p.name.split("-", 2)[1] for p in files}):
        carry = None
        writers: dict[int, tuple[Any, Path]] = {}
        try:
            for path in (p for p in files if p.name.split("-", 2)[1] == network):
                year = int(path.parent.name)
                present = set(pq.read_schema(path).names)
                LOG.info("Lecture : %s", path.name)
                raw = pd.read_parquet(path, columns=[c for c in COLONNES_UTILES if c in present])
                month, carry = hourly_month(normalize_archive(raw, network), network, carry)
                del raw
                table = pa.Table.from_pandas(month, preserve_index=False)
                if year not in writers:
                    destination = root / "silver" / f"year={year}" / f"citybikes_stations_hourly_{network}.parquet"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    writers[year] = (pq.ParquetWriter(destination, table.schema, compression="snappy"), destination)
                    outputs.append(destination)
                writers[year][0].write_table(table.cast(writers[year][0].schema))
                LOG.info("  %s : %d lignes horaires", path.name, len(month))
        finally:
            for writer, _ in writers.values():
                writer.close()
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", help="années (défaut : les 5 dernières jusqu'à 2026)")
    parser.add_argument("--networks", nargs="+", help="réseaux (défaut : ceux de config/cities.yml)")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "citybikes-archive")
    parser.add_argument("--workers", type=int, default=2, help="téléchargements simultanés (défaut 2, soyez raisonnable)")
    parser.add_argument("--dry-run", action="store_true", help="affiche le plan et les volumes sans rien télécharger")
    parser.add_argument("--upload-silver", action="store_true",
                        help="publie les Silver horaires dans le bucket Silver (citybikes-archive/), sans écraser l'existant")
    parser.add_argument("--upload", action="store_true", help="publie aussi dans le bucket Bronze (clés citybikes-archive/)")
    parser.add_argument("--max-gb", type=float, default=2.0, help="refuse de publier si le volume dépasse cette taille (défaut 2 Go)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    years = sorted(set(args.years)) if args.years else default_years()
    networks = args.networks or configured_networks()
    session = build_session()
    plan = build_plan(session, years, networks)
    print_plan(plan)
    if args.dry_run or not plan["files"]:
        return 0
    if args.upload and plan["total_bytes"] > args.max_gb * 1e9:
        print(f"Publication refusée : {human(plan['total_bytes'])} dépasse --max-gb {args.max_gb}. Le quota gratuit de R2 est de 10 Go.")
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ATTRIBUTION.txt").write_text(ATTRIBUTION + "\nLicence ODbL 1.0 : https://opendatacommons.org/licenses/odbl/1-0/\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda e: download_one(session, args.output, e), plan["files"]))
    manifest = {"generated_utc": datetime.now(timezone.utc).isoformat(), "source": BASE_URL, "attribution": ATTRIBUTION,
                "years": years, "networks": networks, "files": results}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("downloaded", "cached", "error", "invalid")}
    print("Résultat :", counts, "| lignes totales :", f"{sum(r.get('rows', 0) for r in results):,}")
    silver_paths = transform_archive(args.output, results)
    print("Silver historique :", [str(path) for path in silver_paths])
    if args.upload_silver:
        print("Silver publiés :", publish_silver(silver_paths))
    if args.upload:
        print("Fichiers publiés :", publish(args.output, results))
    return 1 if counts["error"] or counts["invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
