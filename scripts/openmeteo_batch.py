"""Collecte météo Open-Meteo / ECMWF IFS sur les villes UrbanHub."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import pandas as pd
import yaml

try:
    from .noaa_batch import ROOT, city_daily, fetch, publish
except ImportError:
    from noaa_batch import ROOT, city_daily, fetch, publish

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "ecmwf_ifs"
START = date(2020, 1, 1)
VARIABLES = {
    "temperature_2m": ("temperature", "°C"),
    "wind_speed_10m": ("wind_speed", "m/s"),
    "wind_direction_10m": ("wind_direction", "°"),
    "pressure_msl": ("pressure", "hPa"),
    "visibility": ("visibility", "m"),
    "rain": ("precipitation", "mm"),
}
GOLD = ["gold/kpis/weather_hourly.parquet", "gold/kpis/weather_daily.parquet"]


def fetch_city_year(output, city, start, end, stop):
    city_id = city["id"]
    key = f"bronze/openmeteo/year={start.year}/city_id={city_id}/{start}_{end}.json"
    path = output / key
    # Une mesure de pluie datée 14:00 couvre [13:00, 14:00[. Pour le
    # dernier créneau, récupérer aussi le début du jour suivant s'il est passé.
    api_end = min(end + timedelta(days=1), stop.date())
    query = urlencode({"latitude": city["latitude"], "longitude": city["longitude"],
                       "start_date": start, "end_date": api_end, "hourly": ",".join(VARIABLES),
                       "models": MODEL, "timezone": "GMT", "wind_speed_unit": "ms"})
    url = f"{ARCHIVE}?{query}"
    reusable = api_end < stop.date() - timedelta(days=2)
    content = path.read_bytes() if reusable and path.is_file() else fetch(url)
    payload = json.loads(content)
    units = payload["hourly_units"]
    if payload["utc_offset_seconds"] != 0 or any(units.get(var) != unit for var, (_, unit) in VARIABLES.items()):
        raise ValueError(f"Horodatage ou unités inattendus pour {city_id} {start.year}")
    raw = payload["hourly"]
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw["time"], utc=True))
    expected = pd.date_range(start, api_end + timedelta(days=1), freq="h", inclusive="left", tz="UTC")
    if not timestamps.equals(expected):
        raise ValueError(f"Heures API manquantes ou en double pour {city_id} {start.year}")
    hourly = pd.DataFrame({name: pd.Series(raw[var], index=timestamps, dtype="float64")
                           for var, (name, _) in VARIABLES.items()})
    rainfall = hourly.pop("precipitation")
    rainfall.index -= pd.Timedelta(hours=1)
    hourly["precipitation"] = rainfall
    hourly = hourly.loc[(hourly.index.date <= end) & (hourly.index < stop)].rename_axis("hour_utc").reset_index()
    required = ["temperature", "wind_speed", "pressure", "precipitation"]
    if hourly.empty or hourly[required].isna().any().any():
        raise ValueError(f"Couverture incomplète (température, vent, pression ou pluie) : {city_id} {start}–{end}")
    hourly["city_id"] = city_id
    hourly["source"] = "open-meteo"
    hourly["weather_model"] = MODEL
    path.parent.mkdir(parents=True, exist_ok=True)
    if not reusable or not path.is_file():
        path.write_bytes(content)
    print(f"{city_id} {start.year} : {len(hourly):,} heures", flush=True)
    return hourly, {"city_id": city_id, "url": url, "path": key, "rows": len(hourly),
                    "first_hour_utc": hourly["hour_utc"].min().isoformat(),
                    "last_hour_utc": hourly["hour_utc"].max().isoformat(),
                    "visibility_hours": int(hourly["visibility"].count())}


def run(start=START, end=None, workers=3, upload=False):
    stop = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end if end is not None else (stop - timedelta(hours=1)).date()
    if not date(2017, 1, 1) <= start <= end <= (stop - timedelta(hours=1)).date() or workers < 1:
        raise ValueError("Utiliser des dates croissantes depuis 2017, jusqu'à la dernière heure UTC terminée.")
    if upload and (start != START or end != (stop - timedelta(hours=1)).date()):
        raise ValueError("La publication officielle nécessite la période complète depuis 2020 jusqu'à l'heure actuelle.")
    output = ROOT / "data" / f"openmeteo-{start}_{end}"
    history = ROOT / "data" / "openmeteo-cache"
    cities = yaml.safe_load((ROOT / "config/cities.yml").read_text(encoding="utf-8"))["cities"]
    years = range(start.year, end.year + 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks = [pool.submit(fetch_city_year, history, city, max(start, date(year, 1, 1)),
                             min(end, date(year, 12, 31)), stop)
                 for city in cities for year in years]
        results = [task.result() for task in tasks]
    hourly = pd.concat([frame for frame, _ in results], ignore_index=True).sort_values(["city_id", "hour_utc"])
    if hourly.duplicated(["city_id", "hour_utc"]).any():
        raise ValueError("Doublons sur (city_id, hour_utc)")
    daily = city_daily(hourly)
    daily["source"] = "open-meteo"
    daily["weather_model"] = MODEL
    paths = []

    def save(frame, key):
        path = output / key
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False, engine="pyarrow")
        paths.append(key)

    for year, frame in hourly.groupby(hourly["hour_utc"].dt.year):
        save(frame, f"silver/weather/openmeteo/year={year}/weather_hourly.parquet")
    save(hourly, GOLD[0])
    save(daily, GOLD[1])
    manifest = "bronze/openmeteo/manifest.json"
    path = history / manifest
    path.write_text(json.dumps({"source": "Open-Meteo", "model": MODEL, "start": str(start), "end": str(end),
                                "exclusive_end_utc": min(stop, pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).isoformat(),
                                "files": [entry for _, entry in results]}, indent=2), encoding="utf-8")
    print(f"{len(hourly):,} heures-ville ; {len(daily):,} jours-ville ; {hourly['visibility'].count():,} h avec visibilité")
    if upload:
        # Une clé distante par ville et année : les rafraîchissements ne
        # s'accumulent pas dans le bucket à chaque changement de date.
        raw_keys = []
        for _, entry in results:
            cached = history / entry["path"]
            key = cached.relative_to(history).with_name("archive.json").as_posix()
            destination = output / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(cached.read_bytes())
            entry["key"] = key.removeprefix("bronze/")
            raw_keys.append(key)
        remote_manifest = output / manifest
        remote_manifest.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")),
                                               "files": [entry for _, entry in results]}, indent=2), encoding="utf-8")
        publish(output, raw_keys + [manifest], False, years, source="Open-Meteo")
        publish(output, paths, False, years, source="Open-Meteo")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, help="Jour UTC inclus, limité aux heures écoulées")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--upload", action="store_true", help="Publier Open-Meteo aux chemins Gold partagés")
    try:
        run(**vars(parser.parse_args()))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
