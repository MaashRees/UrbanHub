#!/usr/bin/env python3
"""Gold mobilité historique : agrège les Silver horaires de l'archive CityBikes par ville et par heure.

Entrée : les fichiers produits par scripts/citybikes_archive.py
    <dossier>/silver/year=AAAA/citybikes_stations_hourly_<réseau>.parquet
Sortie : mobility_hourly_archive.parquet, une ligne par (city_id, hour_utc) :
    stations, bikes_total, free_total, empty_stations, full_stations, fill_rate (vélos / (vélos + places libres)),
    movements (somme des variations absolues de vélos par station entre deux heures : mesure d'usage plancher)

Les stations de capacité supérieure à 150 (stations temporaires d'événements : festivals, hippodrome) sont
écartées de l'agrégat pour ne pas fausser le taux de remplissage ; elles représentent 0,003 % des lignes.

Exemples :
    python scripts/citybikes_archive_gold.py --input-dir data/citybikes-archive
    python scripts/citybikes_archive_gold.py --input-dir data/citybikes-archive --upload
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

LOG = logging.getLogger("urbanhub.citybikes_archive_gold")
CAPACITE_MAX = 150
CLE_GOLD = "kpis/history/mobility_hourly_archive.parquet"


def aggregate(silver_dir: Path) -> pd.DataFrame:
    fichiers = sorted(silver_dir.glob("year=*/citybikes_stations_hourly_*.parquet"))
    if not fichiers:
        raise SystemExit(f"Aucun Silver trouvé dans {silver_dir} : lancer scripts/citybikes_archive.py d'abord.")
    morceaux = []
    for fichier in fichiers:
        LOG.info("Lecture : %s", fichier.relative_to(silver_dir))
        df = pd.read_parquet(fichier, columns=["city_id", "hour_utc", "station_id", "bikes_available", "free_slots"])
        df = df[(df["bikes_available"] + df["free_slots"]) <= CAPACITE_MAX]
        df["vide"] = df["bikes_available"] == 0
        df["pleine"] = df["free_slots"] == 0
        # Usage : variation absolue du nombre de vélos d'une station entre deux heures consécutives. C'est une
        # mesure plancher (les départs et retours dans la même heure se compensent) qui inclut aussi le
        # rééquilibrage par l'opérateur. Les trous de plus d'une heure ne comptent pas.
        df = df.sort_values(["station_id", "hour_utc"])
        ecart = df.groupby("station_id")["hour_utc"].diff()
        df["mouvements"] = df.groupby("station_id")["bikes_available"].diff().abs().where(ecart == pd.Timedelta(hours=1), 0)
        morceaux.append(df.groupby(["city_id", "hour_utc"], as_index=False).agg(
            stations=("station_id", "nunique"), bikes_total=("bikes_available", "sum"), free_total=("free_slots", "sum"),
            empty_stations=("vide", "sum"), full_stations=("pleine", "sum"), movements=("mouvements", "sum")))
        del df
    out = pd.concat(morceaux, ignore_index=True)
    out["hour_utc"] = pd.to_datetime(out["hour_utc"], utc=True)
    out["fill_rate"] = out["bikes_total"] / (out["bikes_total"] + out["free_total"])
    return out.sort_values(["city_id", "hour_utc"]).reset_index(drop=True)


def publish(path: Path) -> None:
    try:
        from citybikes_stream import build_minio_client
    except ImportError:
        from scripts.citybikes_stream import build_minio_client
    client, buckets = build_minio_client()
    if not client.bucket_exists(buckets["gold"]):
        raise RuntimeError(f"Bucket {buckets['gold']} introuvable : vérifier MINIO_BUCKET_GOLD dans .env")
    try:
        client.stat_object(buckets["gold"], CLE_GOLD)
        print(f"Déjà présent, non écrasé : {buckets['gold']}/{CLE_GOLD}")
        return
    except Exception:
        pass
    client.fput_object(buckets["gold"], CLE_GOLD, str(path), content_type="application/octet-stream")
    print(f"Publié : {buckets['gold']}/{CLE_GOLD}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=Path("data/citybikes-archive"), help="dossier contenant silver/")
    parser.add_argument("--output", type=Path, help="fichier de sortie (défaut : <input-dir>/gold/mobility_hourly_archive.parquet)")
    parser.add_argument("--upload", action="store_true", help="publie dans le bucket Gold (sans écraser l'existant)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    table = aggregate(args.input_dir / "silver")
    sortie = args.output or args.input_dir / "gold" / "mobility_hourly_archive.parquet"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(sortie, index=False, compression="snappy")
    print(f"{len(table):,} lignes ville-heure, du {table.hour_utc.min():%d/%m/%Y} au {table.hour_utc.max():%d/%m/%Y} -> {sortie}")
    print(table.groupby("city_id").agg(heures=("hour_utc", "size"), stations_max=("stations", "max"), remplissage=("fill_rate", "mean")).round(3).to_string())
    if args.upload:
        publish(sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
