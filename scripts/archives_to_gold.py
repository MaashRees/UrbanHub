#!/usr/bin/env python3
"""Transforme les archives téléchargées en séries horaires et en tables Gold historiques.

Entrées (produites par les scripts d'archives, dossier data/) :
    data/openmeteo-archive/gold/weather_hourly_visibility.parquet     (scripts/openmeteo_archive.py)
    data/openaq-archive/silver/year=*/pollution_archive.parquet       (scripts/openaq_archive.py --silver)

Sorties dans data/archives-gold/ (rien n'est publié sans --upload) :
    weather_daily_visibility.parquet   jour par jour, même contrat que kpis/weather_daily
    pollution_hourly_archive.parquet   (city_id, pollutant, hour_utc), même contrat que kpis/pollution_hourly
    pollution_monthly.parquet          (city_id, month, pollutant) : lu par l'onglet Historique du dashboard
    city_hourly_history.parquet        météo et pollution par ville et par heure, mêmes noms de colonnes que kpis/city_hourly

Règles : tout en UTC ; la pollution d'une heure est la moyenne des capteurs de la ville (comme le
pollution_hourly en direct). Horodatage OpenAQ : l'archive donne la FIN de la période d'une heure,
le Silver en direct le DÉBUT ; vérifié le 20/11/2026 en comparant avec l'API (capteur 7941 : valeur 36,0
à 01:00+01:00 dans l'archive = période 23:00 à 00:00 UTC dans l'API). Le décalage par défaut est donc
de -1 heure (--openaq-shift-hours).

Exemples :
    python scripts/archives_to_gold.py
    python scripts/archives_to_gold.py --openaq-shift-hours 0   # sans décalage (non recommandé)
    python scripts/archives_to_gold.py --upload          # publie dans le bucket Gold (kpis/history/ et kpis/pollution_monthly.parquet)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("urbanhub.archives_to_gold")
POLLUTANTS = ["pm25", "pm10", "no2", "o3", "co"]
WEATHER_COLUMNS = {
    "temperature": "weather_temperature_c", "wind_speed": "weather_wind_speed_ms",
    "wind_direction": "weather_wind_direction_deg", "precipitation": "weather_precipitation_mm",
    "visibility": "weather_visibility_m", "pressure": "weather_pressure_hpa",
}


def weather_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """Même agrégation que scripts/noaa_batch.py (city_daily), avec la visibilité de l'archive."""
    data = hourly.assign(day_utc=hourly["hour_utc"].dt.floor("D"))
    return data.groupby(["city_id", "day_utc"], as_index=False).agg(
        temperature_mean=("temperature", "mean"), temperature_min=("temperature", "min"),
        temperature_max=("temperature", "max"), wind_speed_max=("wind_speed", "max"),
        visibility_mean=("visibility", "mean"), visibility_min=("visibility", "min"),
        temperature_hours=("temperature", "count"), precipitation_hours=("precipitation", "count"),
        precipitation_observed=("precipitation", lambda values: values.sum(min_count=1)),
    )


def load_silver(root: Path, shift_hours: float) -> pd.DataFrame:
    files = sorted((root / "silver").glob("year=*/pollution_archive.parquet"))
    if not files:
        raise SystemExit(f"Aucun Silver OpenAQ dans {root / 'silver'} : lancer scripts/openaq_archive.py --silver.")
    silver = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    silver["timestamp_utc"] = pd.to_datetime(silver["timestamp_utc"], utc=True) + pd.Timedelta(hours=shift_hours)
    return silver.drop_duplicates(["sensor_id", "timestamp_utc", "pollutant"])


def pollution_hourly(silver: pd.DataFrame) -> pd.DataFrame:
    """Moyenne par ville, polluant et heure UTC (contrat de kpis/pollution_hourly)."""
    data = silver.assign(hour_utc=silver["timestamp_utc"].dt.floor("h"))
    return data.groupby(["city_id", "city_name", "pollutant", "unit", "hour_utc"], as_index=False).agg(
        value_mean=("value", "mean"), value_min=("value", "min"), value_max=("value", "max"),
        value_std=("value", "std"), observations_count=("value", "size"), sensors_count=("sensor_id", "nunique"),
    )


def pollution_monthly(hourly: pd.DataFrame) -> pd.DataFrame:
    month = hourly["hour_utc"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")
    return hourly.assign(month=month).groupby(["city_id", "month", "pollutant", "unit"], as_index=False).agg(
        value_mean=("value_mean", "mean"), value_max=("value_max", "max"), hours_count=("value_mean", "size"))


def city_hourly_history(weather: pd.DataFrame, pollution: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par ville et par heure météo ; la pollution est ajoutée quand elle existe."""
    pivot = pollution.pivot_table(index=["city_id", "hour_utc"], columns="pollutant", values="value_mean").reset_index()
    pivot = pivot.rename(columns={p: f"pollution_{p}_ugm3" for p in pivot.columns if p in POLLUTANTS})
    w = weather[["city_id", "hour_utc"] + list(WEATHER_COLUMNS)].rename(columns=WEATHER_COLUMNS)
    merged = w.merge(pivot, on=["city_id", "hour_utc"], how="outer", validate="one_to_one")
    has_pol = merged[[c for c in merged if c.startswith("pollution_")]].notna().any(axis=1)
    has_met = merged["weather_temperature_c"].notna()
    merged["statut_jointure"] = "meteo_seule"
    merged.loc[has_pol & has_met, "statut_jointure"] = "pollution_et_meteo"
    merged.loc[has_pol & ~has_met, "statut_jointure"] = "pollution_seule"
    return merged.sort_values(["city_id", "hour_utc"]).reset_index(drop=True)


def checks(name: str, frame: pd.DataFrame, keys: list[str]) -> None:
    dup = int(frame.duplicated(keys).sum())
    print(f"  {name:34s} {len(frame):>9,} lignes | doublons sur {keys} : {dup}")
    if dup:
        raise SystemExit(f"{name} : doublons sur la clé, arrêt.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weather", type=Path, default=ROOT / "data" / "openmeteo-archive" / "gold" / "weather_hourly_visibility.parquet")
    parser.add_argument("--openaq-root", type=Path, default=ROOT / "data" / "openaq-archive")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "archives-gold")
    parser.add_argument("--openaq-shift-hours", type=float, default=-1.0, help="décalage de l'horodatage OpenAQ : -1 ramène la fin de période de l'archive au début de période du Silver en direct")
    parser.add_argument("--upload", action="store_true", help="publie dans le bucket Gold")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.weather.exists():
        raise SystemExit(f"{args.weather} introuvable : lancer scripts/openmeteo_archive.py.")
    weather = pd.read_parquet(args.weather)
    weather["hour_utc"] = pd.to_datetime(weather["hour_utc"], utc=True)
    silver = load_silver(args.openaq_root, args.openaq_shift_hours)
    poll_h = pollution_hourly(silver)
    tables = {
        "weather_daily_visibility": (weather_daily(weather), ["city_id", "day_utc"]),
        "pollution_hourly_archive": (poll_h, ["city_id", "pollutant", "hour_utc"]),
        "pollution_monthly": (pollution_monthly(poll_h), ["city_id", "month", "pollutant"]),
        "city_hourly_history": (city_hourly_history(weather, poll_h), ["city_id", "hour_utc"]),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Sorties dans {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}")
    for name, (frame, keys) in tables.items():
        checks(name, frame, keys)
        frame.to_parquet(args.output / f"{name}.parquet", index=False)
    hist = tables["city_hourly_history"][0]
    print("Jointure :", hist["statut_jointure"].value_counts().to_dict())
    print("Pollution par ville et année (heures avec mesure) :")
    p = poll_h.assign(annee=poll_h["hour_utc"].dt.year).groupby(["city_id", "annee"])["hour_utc"].nunique().unstack(fill_value=0)
    print(p.to_string())
    if args.upload:
        try:
            from citybikes_stream import build_minio_client, ensure_bucket
        except ImportError:
            from scripts.citybikes_stream import build_minio_client, ensure_bucket
        client, buckets = build_minio_client()
        ensure_bucket(client, buckets["gold"])
        for name in tables:
            key = "kpis/pollution_monthly.parquet" if name == "pollution_monthly" else f"kpis/history/{name}.parquet"
            client.fput_object(buckets["gold"], key, str(args.output / f"{name}.parquet"), content_type="application/x-parquet")
            print("Publié :", f"{buckets['gold']}/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
