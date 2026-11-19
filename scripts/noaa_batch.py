import argparse
import csv
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pandas as pd
import yaml
from botocore.config import Config
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CATALOG_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
ARCHIVE_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com"
LAST_ISD_YEAR = 2025
REQUIRED = {"STATION", "DATE", "TMP", "WND", "VIS", "SLP"}
MEASUREMENTS = ["temperature", "wind_speed", "wind_direction", "pressure", "visibility"]
GOOD_QUALITY = {"0", "1", "4", "5", "9"}
CITY_HOUR = ["city_id", "hour_utc"]


def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "UrbanHub/1.0"}), timeout=30) as response:
                return response.read()
        except (URLError, OSError) as exc:
            if attempt == 2 or (isinstance(exc, HTTPError) and exc.code not in {429, 500, 502, 503, 504}):
                raise
            time.sleep(2**attempt)


def station_jobs(years, sample):
    cities = yaml.safe_load((ROOT / "config/cities.yml").read_text(encoding="utf-8"))
    city_by_usaf = {city["noaa_station_filter"]: city["id"] for city in cities["cities"]}
    catalog = pd.read_csv(io.BytesIO(fetch(CATALOG_URL)), dtype=str)
    french = catalog.loc[catalog["CTRY"].eq("FR")].copy()
    french = french.loc[french["USAF"].str.fullmatch(r"\d{6}", na=False)
                       & french["WBAN"].str.fullmatch(r"\d{5}", na=False)
                       & french["BEGIN"].str.fullmatch(r"\d{8}", na=False)
                       & french["END"].str.fullmatch(r"\d{8}", na=False)]
    french["station_id"] = french["USAF"] + french["WBAN"]
    french["city_id"] = french["USAF"].map(city_by_usaf)
    if sample:
        french = french.dropna(subset=["city_id"])
    jobs = []
    for year in years:
        active = french.loc[french["BEGIN"].le(f"{year}1231") & french["END"].ge(f"{year}0101")]
        active = active.drop_duplicates("station_id").sort_values("station_id")
        jobs.extend((year, row.station_id, row.city_id) for row in active.itertuples(index=False))
    return jobs


def download(job, output):
    year, station, city = job
    path = output / f"bronze/noaa/year={year}/station_id={station}.csv"
    url = f"{ARCHIVE_URL}/{year}/{station}.csv"
    result = {"year": year, "station_id": station, "city_id": city if pd.notna(city) else None,
              "url": url, "path": path.relative_to(output).as_posix(), "bytes": 0}
    try:
        if path.is_file():
            result.update(status="cached", bytes=path.stat().st_size)
        else:
            content = fetch(url)
            header = next(csv.reader([content.split(b"\n", 1)[0].decode("utf-8-sig")]))
            if not REQUIRED.issubset(header):
                raise ValueError("en-tête NOAA inattendu")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            result.update(status="downloaded", bytes=len(content))
    except (OSError, ValueError) as exc:
        status = "missing" if isinstance(exc, HTTPError) and exc.code == 404 else "error"
        result.update(status=status, detail=str(exc))
    return result


def parts(raw, column, width=4):
    if column not in raw:
        return pd.DataFrame(index=raw.index, columns=range(width))
    return raw[column].str.split(",", expand=True).reindex(columns=range(width))


def numeric(values, sentinel, scale=1):
    numbers = pd.to_numeric(values, errors="coerce").astype("float64")
    return numbers.mask(numbers.eq(sentinel)) / scale


def decode(path, station, city):
    raw = pd.read_csv(path, dtype=str, usecols=lambda col: col in REQUIRED | {"AA1", "AA2", "AA3", "AA4"})
    if raw.empty or not raw["STATION"].eq(station).fillna(False).all():
        raise ValueError(f"CSV vide ou identifiant de station incorrect : {path.name}")
    out = pd.DataFrame({"station_id": pd.Series(station, index=raw.index, dtype="string"),
                        "city_id": pd.Series(city, index=raw.index, dtype="string"),
                        "timestamp_utc": pd.to_datetime(raw["DATE"], utc=True, errors="coerce")})
    tmp, wind, vis, slp = (parts(raw, name, width) for name, width in (("TMP", 2), ("WND", 5), ("VIS", 4), ("SLP", 2)))
    out["temperature"] = numeric(tmp[0], 9999, 10).where(tmp[1].isin(GOOD_QUALITY | {"C"}))
    out["wind_direction"] = numeric(wind[0], 999).where(wind[1].isin(GOOD_QUALITY) & ~wind[2].isin({"C", "V"}))
    out["wind_speed"] = numeric(wind[3], 9999, 10).where(wind[4].isin(GOOD_QUALITY))
    out["visibility"] = numeric(vis[0], 999999).where(vis[1].isin(GOOD_QUALITY))
    out["pressure"] = numeric(slp[0], 99999, 10).where(slp[1].isin(GOOD_QUALITY))

    hourly_rain = pd.Series(float("nan"), index=raw.index)
    for i in range(1, 5):
        aa = parts(raw, f"AA{i}")
        period = numeric(aa[0], 99)
        depth = numeric(aa[1], 9999, 10).where(aa[3].isin(GOOD_QUALITY) & aa[2].isin({"2", "4", "9"}))
        out[f"precipitation{'' if i == 1 else f'_aa{i}'}"] = depth
        out[f"precipitation_period_hours{'' if i == 1 else f'_aa{i}'}"] = period.astype("Int16")
        hourly_rain = hourly_rain.fillna(depth.where(period.eq(1)))
    out["precipitation_1h"] = hourly_rain
    out = out.dropna(subset=["timestamp_utc"])
    return (out.assign(_completeness=out[MEASUREMENTS].notna().sum(axis=1), _rain=out["precipitation_1h"].notna())
            .sort_values(["_completeness", "_rain"], ascending=False, kind="stable")
            .drop_duplicates(["station_id", "timestamp_utc"]).drop(columns=["_completeness", "_rain"])
            .sort_values("timestamp_utc").reset_index(drop=True))


def city_hourly(silver):
    city = silver.dropna(subset=["city_id"]).copy()
    city["hour_utc"] = city["timestamp_utc"].dt.floor("h")
    station_hours = city.groupby(CITY_HOUR + ["station_id"], as_index=False)[
        ["temperature", "wind_speed", "pressure", "visibility"]].mean()
    hourly = station_hours.groupby(CITY_HOUR, as_index=False).agg(
        temperature=("temperature", "mean"), wind_speed=("wind_speed", "mean"),
        pressure=("pressure", "mean"), visibility=("visibility", "mean"),
        weather_station_count=("station_id", "nunique"),
    )
    # Une mesure 1 h clôturée à 14:00 couvre [13:00, 14:00[. Garder seulement
    # les clôtures à l'heure pile, dont les intervalles ne se chevauchent pas.
    rain = city.loc[city["timestamp_utc"].eq(city["hour_utc"])].dropna(subset=["precipitation_1h"]).copy()
    rain["hour_utc"] -= pd.Timedelta(hours=1)
    rain = rain.groupby(CITY_HOUR, as_index=False)["precipitation_1h"].mean().rename(
        columns={"precipitation_1h": "precipitation"})
    return hourly.merge(rain, on=CITY_HOUR, how="outer", validate="one_to_one")


def city_daily(hourly):
    data = hourly.assign(day_utc=hourly["hour_utc"].dt.floor("D"))
    return data.groupby(["city_id", "day_utc"], as_index=False).agg(
        temperature_mean=("temperature", "mean"), temperature_min=("temperature", "min"),
        temperature_max=("temperature", "max"), wind_speed_max=("wind_speed", "max"),
        visibility_mean=("visibility", "mean"), visibility_min=("visibility", "min"),
        temperature_hours=("temperature", "count"), precipitation_hours=("precipitation", "count"),
        precipitation_observed=("precipitation", lambda values: values.sum(min_count=1)),
    )


def publish(output, outputs, sample, years, *, source="NOAA-ISD"):
    load_dotenv(ROOT / ".env")
    endpoint = os.environ["MINIO_ENDPOINT"]
    protocol = "https" if os.getenv("MINIO_SECURE", "true").lower() == "true" else "http"
    buckets = {layer: os.environ[f"MINIO_BUCKET_{layer.upper()}"] for layer in ("bronze", "silver", "gold")}
    client = boto3.client("s3", endpoint_url=f"{protocol}://{endpoint}", region_name="auto",
                          aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
                          aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
                          config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                        request_checksum_calculation="when_required",
                                        response_checksum_validation="when_required"))
    prefix = f"sample/{years[0]}-{years[-1]}/" if sample else ""
    for relative in outputs:
        layer, key = relative.split("/", 1)
        if source == "NOAA-ISD" and not sample and layer == "gold" and key.startswith("kpis/"):
            key = key.replace("kpis/", "kpis/noaa/", 1)
        content_type = {".csv": "text/csv", ".json": "application/json", ".parquet": "application/x-parquet"}
        client.upload_file(str(output / relative), buckets[layer], prefix + key,
                           ExtraArgs={"ContentType": content_type[Path(key).suffix], "Metadata": {"source": source}})
        print(f"s3://{buckets[layer]}/{prefix}{key}")


def run(mode="sample", start_year=None, end_year=None, workers=3, upload=False):
    if mode not in {"sample", "france"}:
        raise ValueError("Le mode doit être sample ou france.")
    sample = mode == "sample"
    start = start_year if start_year is not None else (2025 if sample else 2020)
    end = end_year if end_year is not None else (start if sample else start + 4)
    if not 1901 <= start <= end <= LAST_ISD_YEAR or workers < 1:
        raise ValueError("Choisir des années croissantes entre 1901 et 2025 et au moins un thread.")
    years = range(start, end + 1)
    output = ROOT / "data" / f"noaa-{mode}-{start}-{end}"
    jobs = station_jobs(years, sample)
    if not jobs:
        raise RuntimeError("Aucune station active dans le catalogue pour cette période.")
    print(f"NOAA {start}–{end} : {len(jobs)} fichiers station-année, {workers} threads")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download, job, output) for job in jobs]
        manifest = [future.result() for future in as_completed(futures)]
    manifest.sort(key=lambda item: (item["year"], item["station_id"]))
    manifest_path = "bronze/noaa/manifest.json"
    (output / manifest_path).parent.mkdir(parents=True, exist_ok=True)
    (output / manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    files = [entry for entry in manifest if entry["status"] in {"downloaded", "cached"}]
    print(pd.Series([entry["status"] for entry in manifest]).value_counts().to_string())
    if not files or any(entry["status"] == "error" for entry in manifest) or (sample and len(files) != len(jobs)):
        raise RuntimeError(f"Lot incomplet ; voir {output / manifest_path} et relancer pour reprendre.")

    def save(df, relative):
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        outputs.append(relative)
        print(f"{relative} : {len(df):,} lignes")

    outputs = [entry["path"] for entry in files] + [manifest_path]
    hours = []
    for year in years:
        frames = [decode(output / entry["path"], entry["station_id"], entry["city_id"])
                  for entry in files if entry["year"] == year]
        if frames:
            silver = pd.concat(frames, ignore_index=True)
            silver = silver.loc[silver["timestamp_utc"].dt.year.eq(year)]
            save(silver, f"silver/weather/year={year}/weather_france.parquet")
            hours.append(city_hourly(silver))
    hourly = pd.concat(hours, ignore_index=True).groupby(CITY_HOUR, as_index=False).first()
    hourly = hourly.loc[hourly["hour_utc"].dt.year.between(start, end)].reset_index(drop=True)
    hourly["weather_station_count"] = hourly["weather_station_count"].fillna(0).astype("int64")
    save(hourly, "gold/kpis/weather_hourly.parquet")
    save(city_daily(hourly), "gold/kpis/weather_daily.parquet")
    if upload:
        publish(output, outputs, sample, years)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "france"), default="sample")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--upload", action="store_true", help="Publier les sorties dans les buckets du .env")
    try:
        run(**vars(parser.parse_args()))
    except (RuntimeError, ValueError, KeyError) as exc:
        sys.exit(str(exc))
