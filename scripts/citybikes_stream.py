#!/usr/bin/env python3
"""Collecteur micro-batch CityBikes pour Paris, Lyon et Lille.

Le script écrit les zones Bronze, Silver et Gold :

    data/bronze/citybikes/network=<id>/year=YYYY/month=MM/day=DD/*.json
    data/silver/mobility/year=YYYY/month=MM/mobility_stations_*.parquet

Source de vérité des tables Gold :
  - --storage local : tout reste local, Gold calculé depuis le Silver local.
  - --storage minio ou both (en ligne) : Gold calculé depuis le Silver de R2/MinIO, jamais
    depuis le Silver local. Seules les deux dernières heures sont relues, puis fusionnées avec
    le Gold déjà publié (sinon une autre machine écraserait les tables partagées avec sa
    propre vue). La première exécution, sans Gold publié, relit tout le Silver.

Exemples :
    python scripts/citybikes_stream.py --once
    python scripts/citybikes_stream.py --interval-seconds 300
    python scripts/citybikes_stream.py --storage local --once
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml
try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_AVAILABLE = True
except ImportError:  # le mode local reste disponible sans installer MinIO
    Minio = Any  # type: ignore[misc,assignment]
    MINIO_AVAILABLE = False

    class S3Error(Exception):
        pass

try:
    from dotenv import load_dotenv
except ImportError:  # dépendance optionnelle pour rester exécutable sur un environnement minimal
    def load_dotenv(dotenv_path: Path) -> None:
        """Fallback minimal pour charger les variables simples d'un fichier .env."""
        if not dotenv_path.exists():
            return
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_ROOT = "https://api.citybik.es/v2/networks"
TARGET_CITIES = ("paris", "lyon", "lille")
LOG = logging.getLogger("urbanhub.citybikes")
STOP_REQUESTED = False


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def env_bool(value: str | None, default: bool = False) -> bool:
    """Convertit une variable d'environnement en booléen lisible."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_minio_client() -> tuple[Minio, dict[str, str]]:
    """Construit le client MinIO à partir des variables du fichier .env."""
    if not MINIO_AVAILABLE:
        raise RuntimeError("Le paquet minio n'est pas installé. Lancez : pip install minio")
    load_dotenv(project_root() / ".env")
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    buckets = {
        "bronze": os.getenv("MINIO_BUCKET_BRONZE", "").strip(),
        "silver": os.getenv("MINIO_BUCKET_SILVER", "").strip(),
        "gold": os.getenv("MINIO_BUCKET_GOLD", "").strip(),
    }
    if not endpoint or not access_key or not secret_key or not all(buckets.values()):
        raise RuntimeError(
            "Configuration MinIO incomplète. Renseigner MINIO_ENDPOINT, "
            "MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET_BRONZE, "
            "MINIO_BUCKET_SILVER et MINIO_BUCKET_GOLD dans .env."
        )
    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=env_bool(os.getenv("MINIO_SECURE")),
    )
    return client, buckets


def ensure_bucket(client: Minio, bucket: str) -> None:
    """Crée le bucket cible s'il n'existe pas encore."""
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            LOG.info("Bucket MinIO créé : %s", bucket)
    except S3Error as error:
        raise RuntimeError(f"Impossible de préparer le bucket MinIO {bucket}: {error}") from error


def upload_file(client: Minio, bucket: str, local_path: Path, object_name: str) -> None:
    """Envoie un fichier local dans MinIO en conservant son chemin logique."""
    content_type = "application/json" if local_path.suffix == ".json" else "application/octet-stream"
    client.fput_object(bucket, object_name, str(local_path), content_type=content_type)
    LOG.info("MinIO upload : %s/%s", bucket, object_name)


def minio_object_name(local_path: Path, output_root: Path, zone: str) -> str:
    """Construit une clé MinIO sous le dossier métier citybikes uniquement."""
    if zone == "bronze":
        relative_path = local_path.relative_to(output_root / "bronze" / "citybikes")
    elif zone == "silver":
        relative_path = local_path.relative_to(output_root / "silver" / "mobility")
    elif zone == "gold":
        relative_path = local_path.relative_to(output_root / "gold")
    else:
        raise ValueError(f"Zone MinIO non supportée : {zone}")
    return f"citybikes/{relative_path.as_posix()}"


def load_cities(config_path: Path) -> dict[str, dict[str, Any]]:
    # La configuration centralise les identifiants CityBikes et les noms métier.
    with config_path.open(encoding="utf-8") as file:
        configured = yaml.safe_load(file).get("cities", [])
    cities = {city["id"]: city for city in configured}
    missing = set(TARGET_CITIES) - set(cities)
    if missing:
        raise ValueError(f"Villes absentes de {config_path}: {sorted(missing)}")
    return cities


def build_session() -> requests.Session:
    """Prépare un client borné : les 429 ne sont jamais rejoués automatiquement."""
    # On retente uniquement les erreurs serveur transitoires.
    # Les 429 sont volontairement exclus : les rejouer aggraverait le rate limit.
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        backoff_max=5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "UrbanHub-Stream/1.0 (educational project)",
        }
    )
    return session


def fetch_network(
    session: requests.Session,
    city: dict[str, Any],
    timeout: tuple[int, int],
) -> tuple[dict[str, Any], datetime]:
    # Un appel correspond à un snapshot complet d'un réseau.
    network_id = city["citybikes_network_id"]
    url = f"{API_ROOT}/{network_id}"
    observed_at = datetime.now(timezone.utc)
    response = session.get(url, timeout=timeout)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "non communiqué")
        raise requests.HTTPError(
            f"rate limit CityBikes (HTTP 429, Retry-After={retry_after})",
            response=response,
        )
    response.raise_for_status()
    payload = response.json()
    stations = payload.get("network", {}).get("stations")
    if not isinstance(stations, list):
        raise ValueError(f"Réponse invalide pour {city['id']}: stations absentes")
    return payload, observed_at


def write_bronze(
    payload: dict[str, Any],
    network_id: str,
    observed_at: datetime,
    output_root: Path,
) -> Path:
    # Bronze conserve le payload original pour audit et rejouabilité.
    directory = output_root / "bronze" / "citybikes" / f"network={network_id}"
    directory /= observed_at.strftime("year=%Y/month=%m/day=%d")
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_id = observed_at.strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"snapshot_{snapshot_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def stations_to_frame(
    payload: dict[str, Any], city: dict[str, Any], observed_at: datetime
) -> pd.DataFrame:
    # Silver est une ligne par station et par minute d'observation.
    observed_iso = observed_at.isoformat()
    snapshot_minute = observed_at.replace(second=0, microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    for station in payload["network"]["stations"]:
        extra = station.get("extra") or {}
        rows.append(
            {
                "city_id": city["id"],
                "city_name": city["name"],
                "network_id": city["citybikes_network_id"],
                "station_id": str(station.get("id", "")),
                "station_name": station.get("name"),
                "latitude": station.get("latitude"),
                "longitude": station.get("longitude"),
                "bikes_available": station.get("free_bikes"),
                "free_slots": station.get("empty_slots"),
                "station_timestamp": station.get("timestamp"),
                "station_status": extra.get("status"),
                "observed_at_utc": observed_iso,
                "snapshot_minute_utc": snapshot_minute,
            }
        )
    frame = pd.DataFrame(rows)
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    for column in ("bikes_available", "free_slots"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    return frame


def write_silver(frame: pd.DataFrame, output_root: Path, observed_at: datetime) -> Path:
    # Chaque micro-batch est écrit dans son propre fichier Parquet append-only.
    directory = output_root / "silver" / "mobility"
    directory /= observed_at.strftime("year=%Y/month=%m")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"mobility_stations_{observed_at.strftime('%Y%m%dT%H%M%S%fZ')}.parquet"
    frame.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    return path


def read_silver(output_root: Path) -> pd.DataFrame:
    # Les fichiers Silver peuvent être relus par le membre chargé des KPI.
    paths = sorted((output_root / "silver" / "mobility").glob("year=*/month=*/mobility_stations_*.parquet"))
    if not paths:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


SILVER_TIME_RE = re.compile(r"mobility_stations_(\d{8}T\d{6})\d*Z\.parquet$")
GOLD_REMOTE_NAMES = {
    "latest": "citybikes/kpis/mobility_station_latest.parquet",
    "hourly": "citybikes/kpis/mobility_hourly.parquet",
}
GOLD_KEYS = {"latest": ["network_id", "station_id"], "hourly": ["city_id", "hour_utc"]}
INCREMENTAL_HOURS = 1  # heures complètes précédant l'heure courante, recalculées à chaque cycle


def silver_object_time(object_name: str) -> datetime | None:
    """Date de collecte lue dans le nom d'un objet Silver (UTC), ou None si le nom est inattendu."""
    match = SILVER_TIME_RE.search(object_name)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def read_silver_remote(client: Minio, bucket: str, since: datetime | None = None) -> pd.DataFrame:
    """Relit le Silver publié (R2/MinIO), éventuellement seulement depuis `since` (UTC)."""
    names = []
    for item in client.list_objects(bucket, prefix="citybikes/", recursive=True):
        collected_at = silver_object_time(item.object_name)
        if collected_at is not None and (since is None or collected_at >= since):
            names.append(item.object_name)

    def read_one(name: str) -> pd.DataFrame:
        response = client.get_object(bucket, name)
        try:
            return pd.read_parquet(io.BytesIO(response.read()))
        finally:
            response.close()
            response.release_conn()

    if not names:
        return pd.DataFrame()
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = list(pool.map(read_one, sorted(names)))
    return pd.concat(frames, ignore_index=True)


def read_gold_remote(client: Minio, bucket: str, kind: str) -> pd.DataFrame | None:
    """Relit une table Gold mobilité publiée, ou None si elle n'existe pas encore."""
    try:
        response = client.get_object(bucket, GOLD_REMOTE_NAMES[kind])
    except S3Error as error:
        if error.code in {"NoSuchKey", "NoSuchBucket"}:
            return None
        raise
    try:
        return pd.read_parquet(io.BytesIO(response.read()))
    finally:
        response.close()
        response.release_conn()


def merge_gold(existing: pd.DataFrame | None, recomputed: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Les lignes recalculées remplacent celles de même clé ; les autres lignes publiées sont conservées."""
    keys = GOLD_KEYS[kind]
    if existing is None or existing.empty:
        return recomputed.reset_index(drop=True)
    existing = existing.copy()
    if "hour_utc" in keys:
        existing["hour_utc"] = pd.to_datetime(existing["hour_utc"], utc=True)
        recomputed = recomputed.assign(hour_utc=pd.to_datetime(recomputed["hour_utc"], utc=True))
    replaced = pd.MultiIndex.from_frame(recomputed[keys])
    kept = existing.loc[~pd.MultiIndex.from_frame(existing[keys]).isin(replaced)]
    merged = pd.concat([kept, recomputed], ignore_index=True)
    return merged.sort_values(keys).reset_index(drop=True)


def build_gold_remote(
    client: Minio,
    buckets: dict[str, str],
    output_root: Path,
    now: datetime | None = None,
    rebuild: bool = False,
) -> dict[str, Path]:
    """Gold calculé depuis le Silver publié, copié en local pour les notebooks.

    Par défaut, seules les dernières heures sont relues et fusionnées avec le Gold publié.
    Avec `rebuild=True`, le Gold est reconstruit uniquement depuis tout le Silver publié, sans
    reprendre les lignes déjà publiées (utile si le Gold contient des heures sans Silver en ligne).
    """
    now = now or datetime.now(timezone.utc)
    published = {kind: read_gold_remote(client, buckets["gold"], kind) for kind in GOLD_REMOTE_NAMES}
    bootstrap = rebuild or any(frame is None or frame.empty for frame in published.values())
    since = None if bootstrap else now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=INCREMENTAL_HOURS)
    silver = read_silver_remote(client, buckets["silver"], since)
    if silver.empty:
        LOG.warning("Aucun Silver publié depuis %s : Gold inchangé.", since)
        return {}
    latest, hourly = compute_gold(silver)
    if since is not None:
        # Les heures plus anciennes que la fenêtre relue ne doivent pas être modifiées.
        hourly = hourly.loc[pd.to_datetime(hourly["hour_utc"], utc=True) >= since]
    if rebuild:
        tables = {"latest": latest.reset_index(drop=True), "hourly": hourly.reset_index(drop=True)}
    else:
        tables = {
            "latest": merge_gold(published["latest"], latest, "latest"),
            "hourly": merge_gold(published["hourly"], hourly, "hourly"),
        }
    gold_dir = output_root / "gold" / "kpis"
    gold_dir.mkdir(parents=True, exist_ok=True)
    paths = {"latest": gold_dir / "mobility_station_latest.parquet", "hourly": gold_dir / "mobility_hourly.parquet"}
    for kind, frame in tables.items():
        frame.to_parquet(paths[kind], index=False, engine="pyarrow")
    LOG.info(
        "Gold mobilité (depuis le Silver publié, %s) : %d stations, %d lignes horaires",
        "reconstruction complète" if bootstrap else f"depuis {since:%Y-%m-%d %H:%M} UTC",
        len(tables["latest"]), len(tables["hourly"]),
    )
    return paths


def compute_gold(silver: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcule les deux tables Gold mobilité (dernier état par station, indicateurs horaires)."""
    silver = silver.copy()
    silver["observed_at_utc"] = pd.to_datetime(silver["observed_at_utc"], utc=True)
    silver["hour_utc"] = silver["observed_at_utc"].dt.floor("h")
    silver["valid_bikes"] = silver["bikes_available"].notna()
    silver["valid_slots"] = silver["free_slots"].notna()
    # Une relance dans la même minute ne doit pas doubler une observation.
    silver = silver.drop_duplicates(
        subset=["network_id", "station_id", "snapshot_minute_utc"], keep="last"
    )

    # Gold 1 : dernier état connu de chaque station.
    latest_index = silver.groupby(["network_id", "station_id"])["observed_at_utc"].idxmax()
    latest = silver.loc[latest_index].copy()
    latest["is_empty"] = latest["bikes_available"].eq(0)
    latest["is_full"] = latest["free_slots"].eq(0)
    latest["capacity_estimated"] = latest[["bikes_available", "free_slots"]].sum(axis=1, min_count=1)
    latest = latest.drop(columns=["valid_bikes", "valid_slots", "hour_utc"])

    # Gold 2 : indicateurs horaires par ville.
    keys = ["city_id", "city_name", "hour_utc"]
    hourly = silver.groupby(keys, dropna=False).agg(
        stations_observed=("station_id", "nunique"),
        observations=("station_id", "count"),
        bikes_available_total=("bikes_available", "sum"),
        bikes_available_mean=("bikes_available", "mean"),
        free_slots_total=("free_slots", "sum"),
        free_slots_mean=("free_slots", "mean"),
        valid_bike_observations=("valid_bikes", "sum"),
        valid_slot_observations=("valid_slots", "sum"),
    ).reset_index()
    valid_bikes = silver[silver["valid_bikes"]].groupby(keys)
    valid_slots = silver[silver["valid_slots"]].groupby(keys)
    empty = valid_bikes["bikes_available"].apply(lambda values: values.eq(0).sum()).rename("empty_observations")
    full = valid_slots["free_slots"].apply(lambda values: values.eq(0).sum()).rename("full_observations")
    hourly = hourly.merge(empty, on=keys, how="left").merge(full, on=keys, how="left")
    hourly["breakdown_rate"] = hourly["empty_observations"] / hourly["valid_bike_observations"].replace(0, pd.NA)
    hourly["saturation_rate"] = hourly["full_observations"] / hourly["valid_slot_observations"].replace(0, pd.NA)
    critical = silver[
        (silver["valid_bikes"] & silver["bikes_available"].eq(0))
        | (silver["valid_slots"] & silver["free_slots"].eq(0))
    ].groupby(keys)["station_id"].nunique().rename("critical_station_count")
    hourly = hourly.merge(critical, on=keys, how="left")
    hourly["critical_station_count"] = hourly["critical_station_count"].fillna(0).astype("int64")
    hourly["critical_station_rate"] = hourly["critical_station_count"] / hourly["stations_observed"].replace(0, pd.NA)

    return latest, hourly


def build_gold(silver: pd.DataFrame, output_root: Path) -> dict[str, Path]:
    """Mode local : Gold calculé depuis le Silver local, écrit sous data/gold/kpis."""
    if silver.empty:
        return {}
    latest, hourly = compute_gold(silver)
    gold_dir = output_root / "gold" / "kpis"
    gold_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "latest": gold_dir / "mobility_station_latest.parquet",
        "hourly": gold_dir / "mobility_hourly.parquet",
    }
    latest.to_parquet(paths["latest"], index=False, engine="pyarrow")
    hourly.to_parquet(paths["hourly"], index=False, engine="pyarrow")
    LOG.info("Gold mobilité (local) : %d stations, %d lignes horaires", len(latest), len(hourly))
    return paths


def collect_once(
    session: requests.Session,
    cities: dict[str, dict[str, Any]],
    output_root: Path,
    timeout: tuple[int, int],
    request_delay: float,
    minio_client: Minio | None = None,
    minio_buckets: dict[str, str] | None = None,
) -> int:
    collected = 0
    # Les villes sont interrogées séquentiellement pour limiter la pression API.
    for index, city_id in enumerate(TARGET_CITIES):
        city = cities[city_id]
        try:
            LOG.info("Collecte %s (%s)", city["name"], city["citybikes_network_id"])
            payload, observed_at = fetch_network(session, city, timeout)
            bronze_path = write_bronze(payload, city["citybikes_network_id"], observed_at, output_root)
            frame = stations_to_frame(payload, city, observed_at)
            silver_path = write_silver(frame, output_root, observed_at)
            if minio_client is not None and minio_buckets is not None:
                # Les chemins relatifs deviennent les clés d'objets MinIO.
                upload_file(
                    minio_client,
                    minio_buckets["bronze"],
                    bronze_path,
                    minio_object_name(bronze_path, output_root, "bronze"),
                )
                upload_file(
                    minio_client,
                    minio_buckets["silver"],
                    silver_path,
                    minio_object_name(silver_path, output_root, "silver"),
                )
            collected += len(frame)
            LOG.info("OK %s : %d stations | Bronze=%s | Silver=%s", city["name"], len(frame), bronze_path, silver_path)
        except (requests.RequestException, ValueError, KeyError, S3Error, OSError) as error:
            LOG.error("Échec %s : %s", city["name"], error)
        if index < len(TARGET_CITIES) - 1:
            time.sleep(request_delay)

    if minio_client is not None and minio_buckets is not None:
        # En ligne : tout vient de R2. Le Silver local de cette machine n'entre jamais dans le Gold publié.
        try:
            gold_paths = build_gold_remote(minio_client, minio_buckets, output_root)
        except (S3Error, OSError, ValueError) as error:
            LOG.error("Gold non mis à jour (lecture du Silver ou du Gold publié impossible) : %s", error)
            gold_paths = {}
        for path in gold_paths.values():
            upload_file(
                minio_client,
                minio_buckets["gold"],
                path,
                minio_object_name(path, output_root, "gold"),
            )
    else:
        # Hors ligne : tout reste local.
        build_gold(read_silver(output_root), output_root)
    return collected


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="effectue un seul micro-batch")
    parser.add_argument("--interval-seconds", type=int, default=300, help="intervalle entre deux cycles (défaut: 300 = 5 min)")
    parser.add_argument("--request-delay", type=float, default=1.0, help="délai entre les villes (défaut: 1 s)")
    parser.add_argument(
        "--storage",
        choices=("local", "minio", "both"),
        default="both",
        help="local : tout en local ; minio ou both (en ligne) : Silver et Gold relus depuis R2/MinIO (défaut: both)",
    )
    parser.add_argument(
        "--rebuild-gold",
        action="store_true",
        help="reconstruit les tables Gold uniquement depuis tout le Silver publié (R2/MinIO), puis quitte sans collecter",
    )
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--read-timeout", type=int, default=15)
    parser.add_argument("--output-root", type=Path, default=root / "data")
    parser.add_argument("--config", type=Path, default=root / "config" / "cities.yml")
    return parser.parse_args()


def stop_handler(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    LOG.info("Arrêt demandé (signal %s), fin du cycle en cours.", signum)


def main() -> None:
    args = parse_args()
    if args.interval_seconds <= 0 or args.request_delay < 0:
        raise SystemExit("interval-seconds doit être > 0 et request-delay doit être >= 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    cities = load_cities(args.config)
    session = build_session()
    timeout = (args.connect_timeout, args.read_timeout)
    minio_client = None
    minio_buckets = None
    if args.storage != "local":
        minio_client, minio_buckets = build_minio_client()
        for bucket in minio_buckets.values():
            ensure_bucket(minio_client, bucket)

    if args.rebuild_gold:
        if minio_client is None or minio_buckets is None:
            raise SystemExit("--rebuild-gold demande un stockage en ligne (--storage minio ou both).")
        paths = build_gold_remote(minio_client, minio_buckets, args.output_root, rebuild=True)
        for path in paths.values():
            upload_file(minio_client, minio_buckets["gold"], path, minio_object_name(path, args.output_root, "gold"))
        return

    LOG.info("Démarrage CityBikes : intervalle=%ss, sortie=%s, stockage=%s", args.interval_seconds, args.output_root, args.storage)
    # Boucle de streaming : un cycle complet, puis attente jusqu'au prochain.
    while not STOP_REQUESTED:
        started = time.monotonic()
        collect_once(
            session,
            cities,
            args.output_root,
            timeout,
            args.request_delay,
            minio_client=minio_client,
            minio_buckets=minio_buckets,
        )
        if args.once or STOP_REQUESTED:
            break
        elapsed = time.monotonic() - started
        wait_seconds = max(0, args.interval_seconds - elapsed)
        LOG.info("Prochain cycle dans %.1f secondes", wait_seconds)
        if STOP_REQUESTED:
            break
        time.sleep(wait_seconds)
    LOG.info("Collecteur arrêté")


if __name__ == "__main__":
    main()
