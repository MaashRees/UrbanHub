import os
import io
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml
import requests
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from minio import Minio
from minio.versioningconfig import VersioningConfig, ENABLED
from minio.error import S3Error
from dotenv import load_dotenv

# ==============================================================================
# 1. INITIALISATION DU DATALAKE S3 / MINIO / CLOUDFLARE R2
# ==============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def load_config():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    cities_path = PROJECT_ROOT / "config" / "cities.yml"
    with open(cities_path, "r", encoding="utf-8") as f:
        cities_cfg = yaml.safe_load(f).get("cities", [])
    return cities_cfg

def get_bucket_names(endpoint: str):
    is_r2 = "r2.cloudflarestorage.com" in endpoint
    return {
        "bronze": os.getenv("MINIO_BUCKET_BRONZE", "urbanhub-bronze" if is_r2 else "bronze"),
        "silver": os.getenv("MINIO_BUCKET_SILVER", "urbanhub-silver" if is_r2 else "silver"),
        "gold": os.getenv("MINIO_BUCKET_GOLD", "urbanhub-gold" if is_r2 else "gold"),
    }

def init_datalake_client():
    load_config()
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
    region = "auto" if "r2.cloudflarestorage.com" in endpoint else None
    
    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region
    )
    buckets = get_bucket_names(endpoint)
    for b_name in buckets.values():
        if not client.bucket_exists(b_name):
            try:
                client.make_bucket(b_name)
                print(f"Bucket '{b_name}' créé.")
            except Exception as e:
                print(f"Note bucket '{b_name}': {e}")
        else:
            pass
            
    bronze_b = buckets["bronze"]
    try:
        client.set_bucket_versioning(bronze_b, VersioningConfig(ENABLED))
    except Exception:
        pass
    return client

# ==============================================================================
# 2. CLIENT API OPENAQ v3 AVEC REPRISE & RATE LIMITING
# ==============================================================================

class OpenAQClient:
    BASE_URL = "https://api.openaq.org/v3"
    
    def __init__(self, api_key: str = None):
        load_config()
        self.api_key = api_key or os.getenv("OPENAQ_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "User-Agent": "UrbanHub-IoT/1.0"
        })
        
    def get(self, endpoint: str, params: dict = None, max_retries: int = 3):
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait_time = int(resp.headers.get("x-ratelimit-reset", 2 ** attempt))
                    print(f"⚠️ [OpenAQ 429] Rate limit atteint. Attente {wait_time}s...")
                    time.sleep(max(1, wait_time))
                elif resp.status_code >= 500:
                    time.sleep(1 + attempt)
                else:
                    print(f"❌ [OpenAQ {resp.status_code}] sur {url}: {resp.text[:120]}")
                    return None
            except requests.RequestException as e:
                print(f"⚠️ [Erreur Réseau] {e} (tentative {attempt+1}/{max_retries})")
                time.sleep(1 + attempt)
        return None

# ==============================================================================
# 3. DÉCOUVERTE DES CAPTEURS & MATRICE VILLE x POLLUANTS
# ==============================================================================

TARGET_POLLUTANTS = ["pm25", "pm10", "no2", "o3", "co"]

def discover_city_sensors(aq_client: OpenAQClient, cities: list, radius_m: int = 25000):
    matrix = {}
    catalog = []
    
    for city in cities:
        city_id = city["id"]
        city_name = city["name"]
        lat = city["latitude"]
        lon = city["longitude"]
        
        matrix[city_id] = {
            "city_name": city_name,
            "total_locations": 0,
            "pollutants_found": set(),
            "locations": []
        }
        
        coord_str = f"{lat},{lon}"
        params = {
            "coordinates": coord_str,
            "radius": radius_m,
            "limit": 30
        }
        data = aq_client.get("locations", params=params)
        if not data:
            continue
            
        results = data.get("results", [])
        matrix[city_id]["total_locations"] = data.get("meta", {}).get("found", len(results))
        
        for loc in results:
            loc_id = loc.get("id")
            loc_name = loc.get("name")
            locality = loc.get("locality")
            coords = loc.get("coordinates")
            dt_last = loc.get("datetimeLast", {}).get("utc") if loc.get("datetimeLast") else None
            
            sensors = loc.get("sensors", [])
            valid_sensors = []
            for s in sensors:
                pname = s.get("parameter", {}).get("name", "").lower()
                punits = s.get("parameter", {}).get("units")
                if pname in TARGET_POLLUTANTS:
                    matrix[city_id]["pollutants_found"].add(pname)
                    sensor_entry = {
                        "sensor_id": s.get("id"),
                        "pollutant": pname,
                        "unit": punits,
                        "location_id": loc_id,
                        "location_name": loc_name,
                        "locality": locality,
                        "latitude": coords.get("latitude") if coords else lat,
                        "longitude": coords.get("longitude") if coords else lon,
                        "city_id": city_id,
                        "city_name": city_name,
                        "datetime_last": dt_last
                    }
                    valid_sensors.append(sensor_entry)
                    catalog.append(sensor_entry)
            
            if valid_sensors:
                matrix[city_id]["locations"].append({
                    "id": loc_id,
                    "name": loc_name,
                    "locality": locality,
                    "coordinates": coords,
                    "datetime_last": dt_last,
                    "sensors_count": len(valid_sensors),
                    "pollutants": list(set(s["pollutant"] for s in valid_sensors))
                })
                
    return matrix, catalog

# ==============================================================================
# 4. INGESTION EN ZONE BRONZE (JSON BRUT + PARTITIONNEMENT HIVE)
# ==============================================================================

def ingest_openaq_to_bronze(minio_client: Minio, aq_client: OpenAQClient, catalog: list, max_sensors_per_pollutant: int = 2):
    now = datetime.now(timezone.utc)
    date_path = now.strftime("year=%Y/month=%m/day=%d")
    time_str = now.strftime("%H%M%S")
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    bronze_bucket = get_bucket_names(endpoint)["bronze"]
    
    selected_sensors = []
    by_city_pollutant = {}
    for entry in catalog:
        is_recent = entry.get("datetime_last") and "2026" in str(entry["datetime_last"])
        if not is_recent:
            continue
        key = (entry["city_id"], entry["pollutant"])
        if key not in by_city_pollutant:
            by_city_pollutant[key] = []
        if len(by_city_pollutant[key]) < max_sensors_per_pollutant:
            by_city_pollutant[key].append(entry)
            selected_sensors.append(entry)
            
    print(f"📥 Début de l'ingestion Bronze pour {len(selected_sensors)} capteurs sélectionnés...")
    ingested_keys = []
    
    dt_from = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    
    for s in selected_sensors:
        sid = s["sensor_id"]
        cid = s["city_id"]
        params = {
            "datetime_from": dt_from,
            "limit": 300
        }
        res = aq_client.get(f"sensors/{sid}/measurements", params=params)
        if not res or not res.get("results"):
            continue
            
        payload = {
            "sensor_metadata": s,
            "ingestion_utc": now.isoformat(),
            "query_params": params,
            "response": res
        }
        
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        s3_path = f"openaq/city={cid}/{date_path}/sensor_{sid}_{time_str}.json"
        
        minio_client.put_object(
            bucket_name=bronze_bucket,
            object_name=s3_path,
            data=io.BytesIO(json_bytes),
            length=len(json_bytes),
            content_type="application/json",
            metadata={
                "source": "OpenAQ_v3",
                "city": cid,
                "sensor_id": str(sid),
                "pollutant": s["pollutant"],
                "records_count": str(len(res.get("results", [])))
            }
        )
        ingested_keys.append(s3_path)
        time.sleep(0.05)
        
    print(f"✅ Total Bronze : {len(ingested_keys)} objets sauvegardés dans {bronze_bucket}.")
    return ingested_keys

# ==============================================================================
# 5. NETTOYAGE & TRANSFORMATION VERS SILVER (PARQUET, CONVERSION UNITÉS)
# ==============================================================================

UNIT_FACTORS_TO_UG_M3 = {
    "ppm": {
        "no2": 1880.0,
        "o3": 1960.0,
        "co": 1145.0,
        "so2": 2620.0
    },
    "ppb": {
        "no2": 1.880,
        "o3": 1.960,
        "co": 1.145,
        "so2": 2.620
    }
}

def clean_and_transform_to_silver(minio_client: Minio):
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    buckets = get_bucket_names(endpoint)
    bronze_bucket = buckets["bronze"]
    silver_bucket = buckets["silver"]
    
    objects = list(minio_client.list_objects(bronze_bucket, prefix="openaq/", recursive=True))
    if not objects:
        print(f"⚠️ Aucun objet trouvé dans {bronze_bucket}/openaq/")
        # Si Silver existe déjà, charger la table existante
        try:
            resp = minio_client.get_object(silver_bucket, "pollution/pollution_france.parquet")
            df = pd.read_parquet(io.BytesIO(resp.read()))
            resp.close()
            resp.release_conn()
            print(f"ℹ️ Relecture de la table existante {silver_bucket}/pollution/pollution_france.parquet ({len(df)} lignes)")
            return df
        except Exception:
            return None
        
    records = []
    treatment_timestamp = datetime.now(timezone.utc).isoformat()
    
    for obj in objects:
        resp = minio_client.get_object(bronze_bucket, obj.object_name)
        data = json.loads(resp.read().decode("utf-8"))
        resp.close()
        resp.release_conn()
        
        meta = data.get("sensor_metadata", {})
        results = data.get("response", {}).get("results", [])
        
        for item in results:
            val = item.get("value")
            param = item.get("parameter", {})
            pname = param.get("name", meta.get("pollutant", "")).lower()
            raw_unit = param.get("units", meta.get("unit", "µg/m³"))
            
            dt_period = item.get("period", {})
            dt_from = dt_period.get("datetimeFrom", {}) if dt_period else {}
            dt_str = dt_from.get("utc") if dt_from else None
            if not dt_str and "datetime" in item:
                dt_str = item["datetime"].get("utc")
                
            if val is None or dt_str is None:
                continue
                
            if val < 0:
                continue
                
            clean_unit = raw_unit
            clean_val = float(val)
            
            if raw_unit in UNIT_FACTORS_TO_UG_M3:
                factors = UNIT_FACTORS_TO_UG_M3[raw_unit]
                if pname in factors:
                    clean_val = clean_val * factors[pname]
                    clean_unit = "µg/m³"
            elif raw_unit == "µg/m³":
                clean_unit = "µg/m³"
                
            if pname in ["pm25", "pm10", "no2", "o3"] and clean_val > 5000:
                continue
            if pname == "co" and clean_val > 200000:
                continue
                
            records.append({
                "sensor_id": str(meta.get("sensor_id")),
                "location_id": int(meta.get("location_id", 0)),
                "location_name": str(meta.get("location_name", "Inconnue")),
                "locality": str(meta.get("locality", "")),
                "pollutant": pname,
                "timestamp_utc": dt_str,
                "latitude": float(meta.get("latitude", 0.0)),
                "longitude": float(meta.get("longitude", 0.0)),
                "value": clean_val,
                "unit": clean_unit,
                "city_id": meta.get("city_id", "inconnue"),
                "city_name": meta.get("city_name", "Inconnue"),
                "date_traitement_utc": treatment_timestamp
            })
            
    if not records:
        print("⚠️ Aucun enregistrement valide extrait de Bronze.")
        return None
        
    df = pd.DataFrame(records)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    initial_len = len(df)
    df = df.drop_duplicates(subset=["sensor_id", "timestamp_utc"]).reset_index(drop=True)
    duplicates_removed = initial_len - len(df)
    print(f"🧹 Déduplication : {duplicates_removed} doublons supprimés sur {initial_len} lignes.")
    
    # Sauvegarde Parquet dans Silver
    now = datetime.now(timezone.utc)
    s3_silver_paths = [
        f"pollution/year={now.year}/month={now.month:02d}/pollution_sensors.parquet",
        "pollution/pollution_france.parquet"
    ]
    
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    parquet_bytes = buf.getvalue()
    
    for s3_path in s3_silver_paths:
        minio_client.put_object(
            bucket_name=silver_bucket,
            object_name=s3_path,
            data=io.BytesIO(parquet_bytes),
            length=len(parquet_bytes),
            content_type="application/x-parquet",
            metadata={
                "source": "bronze/openaq",
                "format": "parquet",
                "lignes": str(len(df)),
                "auteur": "personne_3_julie"
            }
        )
    print(f"💾 Silver sauvegardé : {silver_bucket}/pollution/pollution_france.parquet ({len(df)} lignes)")
    return df

# ==============================================================================
# 6. CALCUL DES INDICATEURS GOLD (QUESTIONS MÉTIER POLLUTION)
# ==============================================================================

OMS_THRESHOLDS_24H = {
    "pm25": 15.0,
    "pm10": 45.0,
    "no2": 25.0,
    "o3": 100.0,
    "co": 4000.0
}

def compute_gold_pollution(minio_client: Minio, df_silver: pd.DataFrame):
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    gold_bucket = get_bucket_names(endpoint)["gold"]
    
    df = df_silver.copy()
    df["hour_utc"] = df["timestamp_utc"].dt.floor("h")
    
    # 1. Table Gold : pollution_hourly
    hourly = df.groupby(["city_id", "city_name", "pollutant", "unit", "hour_utc"]).agg(
        value_mean=("value", "mean"),
        value_min=("value", "min"),
        value_max=("value", "max"),
        value_std=("value", "std"),
        observations_count=("value", "count"),
        sensors_count=("sensor_id", "nunique")
    ).reset_index()
    
    buf = io.BytesIO()
    hourly.to_parquet(buf, index=False, engine="pyarrow")
    bytes_gold = buf.getvalue()
    
    minio_client.put_object(
        bucket_name=gold_bucket,
        object_name="kpis/pollution_hourly.parquet",
        data=io.BytesIO(bytes_gold),
        length=len(bytes_gold),
        content_type="application/x-parquet",
        metadata={"source": "silver/pollution", "auteur": "personne_3_julie"}
    )
    print(f"🏆 Gold sauvegardé : {gold_bucket}/kpis/pollution_hourly.parquet ({len(hourly)} lignes)")
    
    # 2. Indicateurs métier
    zones_ranking = df.groupby(["city_name", "location_name", "pollutant", "unit"]).agg(
        concentration_moyenne=("value", "mean"),
        pic_maximal=("value", "max"),
        nb_mesures=("value", "count")
    ).reset_index().sort_values(by=["pollutant", "concentration_moyenne"], ascending=[True, False])
    
    df["heure_du_jour"] = df["timestamp_utc"].dt.hour
    diurnal_profile = df.groupby(["city_name", "pollutant", "heure_du_jour"]).agg(
        valeur_moyenne=("value", "mean")
    ).reset_index()
    
    dominance = []
    for pol, group in df.groupby("pollutant"):
        seuil = OMS_THRESHOLDS_24H.get(pol, 1.0)
        ratio_moyen = group["value"].mean() / seuil
        depassements = (group["value"] > seuil).mean() * 100
        dominance.append({
            "pollutant": pol,
            "seuil_ref_oms": seuil,
            "moyenne_observee": round(group["value"].mean(), 2),
            "ratio_sur_seuil": round(ratio_moyen, 2),
            "pct_mesures_au_dessus_seuil": round(depassements, 1)
        })
    df_dominance = pd.DataFrame(dominance).sort_values(by="ratio_sur_seuil", ascending=False)
    
    anomalies = []
    for (cid, pol), group in df.groupby(["city_id", "pollutant"]):
        p95 = group["value"].quantile(0.95)
        extreme_rows = group[group["value"] >= p95]
        for _, row in extreme_rows.iterrows():
            anomalies.append({
                "city_id": cid,
                "location": row["location_name"],
                "pollutant": pol,
                "timestamp_utc": row["timestamp_utc"].isoformat(),
                "valeur": row["value"],
                "seuil_p95": round(p95, 2)
            })
            
    summary_json = {
        "generation_utc": datetime.now(timezone.utc).isoformat(),
        "total_mesures_silver": len(df),
        "total_heures_gold": len(hourly),
        "villes_couvertes": df["city_name"].unique().tolist(),
        "polluants_analyses": df["pollutant"].unique().tolist(),
        "dominance_polluants": df_dominance.to_dict(orient="records"),
        "top_zones_polluees": zones_ranking.head(10).to_dict(orient="records"),
        "nb_anomalies_detectees_p95": len(anomalies)
    }
    
    summary_bytes = json.dumps(summary_json, indent=2, ensure_ascii=False).encode("utf-8")
    minio_client.put_object(
        bucket_name=gold_bucket,
        object_name="kpis/pollution_summary.json",
        data=io.BytesIO(summary_bytes),
        length=len(summary_bytes),
        content_type="application/json"
    )
    print(f"🏆 Résumé JSON sauvegardé : {gold_bucket}/kpis/pollution_summary.json")
    return hourly, zones_ranking, diurnal_profile, df_dominance, anomalies

# ==============================================================================
# 7. ANALYSE CROISÉE MULTI-SOURCES & FUSION GLOBALE
# ==============================================================================

def harmonize_mobility_kpis(minio_client: Minio, gold_bucket: str):
    """Garantit que les tables mobilité existent sous kpis/ et citybikes/kpis/."""
    pairs = [
        ("citybikes/kpis/mobility_hourly.parquet", "kpis/mobility_hourly.parquet"),
        ("citybikes/kpis/mobility_station_latest.parquet", "kpis/mobility_station_latest.parquet")
    ]
    for src, dst in pairs:
        try:
            minio_client.stat_object(gold_bucket, dst)
        except Exception:
            try:
                resp = minio_client.get_object(gold_bucket, src)
                data = resp.read()
                resp.close()
                resp.release_conn()
                minio_client.put_object(gold_bucket, dst, io.BytesIO(data), len(data), content_type="application/x-parquet")
                print(f"  ✨ Harmonisé {src} ➔ {dst}")
            except Exception:
                pass

def check_and_build_cross_analysis(minio_client: Minio, df_pollution_hourly: pd.DataFrame):
    """
    Exécute la fusion multi-sources réelle sur (city_id, hour_utc) :
    Pollution OpenAQ (P3) + Météo NOAA (P1) + Mobilité CityBikes (P2).
    """
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    gold_bucket = get_bucket_names(endpoint)["gold"]
    
    print("\n🔍 Contrôle et fusion multi-sources pour l'analyse croisée :")
    harmonize_mobility_kpis(minio_client, gold_bucket)
    
    # 1. Vérification Météo NOAA (P1)
    df_w = pd.DataFrame()
    for w_key in ["kpis/weather_hourly.parquet", "sample/2025-2025/kpis/weather_hourly.parquet"]:
        try:
            resp = minio_client.get_object(gold_bucket, w_key)
            df_w = pd.read_parquet(io.BytesIO(resp.read()))
            resp.close()
            resp.release_conn()
            print(f"  - Source 1 Météo NOAA (Personne 1) : 🟢 Disponible ({w_key}, {len(df_w)} lignes)")
            break
        except Exception:
            continue
    if df_w.empty:
        print("  - Source 1 Météo NOAA (Personne 1) : 🔴 ABSENTE")
        
    # 2. Vérification Mobilité CityBikes (P2)
    df_m = pd.DataFrame()
    for m_key in ["kpis/mobility_hourly.parquet", "citybikes/kpis/mobility_hourly.parquet"]:
        try:
            resp = minio_client.get_object(gold_bucket, m_key)
            df_m = pd.read_parquet(io.BytesIO(resp.read()))
            resp.close()
            resp.release_conn()
            print(f"  - Source 2 Mobilité CityBikes (Personne 2) : 🟢 Disponible ({m_key}, {len(df_m)} lignes)")
            break
        except Exception:
            continue
    if df_m.empty:
        print("  - Source 2 Mobilité CityBikes (Personne 2) : 🔴 ABSENTE")
        
    # 3. Source 3 Pollution OpenAQ (P3)
    print(f"  - Source 3 Pollution OpenAQ (Personne 3) : 🟢 Disponible ({len(df_pollution_hourly)} lignes)")
    
    # Pivot de la pollution par polluant
    p_pivot = df_pollution_hourly.pivot_table(
        index=["city_id", "hour_utc"],
        columns="pollutant",
        values="value_mean"
    ).reset_index()
    pollutant_cols = [c for c in p_pivot.columns if c not in ["city_id", "hour_utc"]]
    p_pivot = p_pivot.rename(columns={col: f"pollution_{col}_ugm3" for col in pollutant_cols})
    
    # Préparation météo
    w_cols = ["city_id", "hour_utc", "temperature", "wind_speed", "precipitation", "visibility", "pressure"]
    w_sub = df_w[[c for c in w_cols if c in df_w.columns]].copy() if not df_w.empty else pd.DataFrame(columns=["city_id", "hour_utc"])
    w_sub = w_sub.rename(columns={
        "temperature": "weather_temperature_c",
        "wind_speed": "weather_wind_speed_ms",
        "precipitation": "weather_precipitation_mm",
        "visibility": "weather_visibility_m",
        "pressure": "weather_pressure_hpa"
    })
    
    # Préparation mobilité
    m_cols = ["city_id", "hour_utc", "bikes_available_total", "free_slots_total", "stations_observed", "breakdown_rate", "saturation_rate", "critical_station_rate"]
    m_sub = df_m[[c for c in m_cols if c in df_m.columns]].copy() if not df_m.empty else pd.DataFrame(columns=["city_id", "hour_utc"])
    m_sub = m_sub.rename(columns={
        "bikes_available_total": "mobility_bikes_available",
        "free_slots_total": "mobility_free_slots",
        "stations_observed": "mobility_stations_count",
        "breakdown_rate": "mobility_breakdown_rate",
        "saturation_rate": "mobility_saturation_rate",
        "critical_station_rate": "mobility_critical_rate"
    })
    
    # Fusion externe (outer) pour conserver toutes les observations temporelles
    city_hourly = p_pivot.merge(m_sub, on=["city_id", "hour_utc"], how="outer")
    city_hourly = city_hourly.merge(w_sub, on=["city_id", "hour_utc"], how="outer")
    
    city_name_map = {"paris": "Paris", "lyon": "Lyon", "lille": "Lille"}
    city_hourly["city_name"] = city_hourly["city_id"].map(city_name_map)
    
    # Attribution du statut de jointure
    def get_status(row):
        has_pol = pd.notna(row.get("pollution_no2_ugm3")) or pd.notna(row.get("pollution_pm25_ugm3"))
        has_mob = pd.notna(row.get("mobility_bikes_available"))
        has_wth = pd.notna(row.get("weather_temperature_c"))
        if has_pol and has_mob and has_wth:
            return "complete_3_sources"
        elif has_pol and has_mob:
            return "pollution_et_mobilite"
        elif has_pol and has_wth:
            return "pollution_et_meteo"
        elif has_mob and has_wth:
            return "mobilite_et_meteo"
        elif has_pol:
            return "pollution_seule"
        elif has_mob:
            return "mobilite_seule"
        else:
            return "meteo_seule"
            
    city_hourly["statut_jointure"] = city_hourly.apply(get_status, axis=1)
    city_hourly = city_hourly.sort_values(by=["city_id", "hour_utc"]).reset_index(drop=True)
    
    # Sauvegarde Parquet dans Gold
    buf = io.BytesIO()
    city_hourly.to_parquet(buf, index=False, engine="pyarrow")
    bytes_cross = buf.getvalue()
    
    minio_client.put_object(
        bucket_name=gold_bucket,
        object_name="kpis/city_hourly.parquet",
        data=io.BytesIO(bytes_cross),
        length=len(bytes_cross),
        content_type="application/x-parquet",
        metadata={
            "description": "Table croisee multi-sources unifiee sur (city_id, hour_utc)",
            "statut": "multi_sources_fusionnees",
            "auteur": "personne_3_julie",
            "lignes": str(len(city_hourly))
        }
    )
    print(f"🏆 Table Gold multi-sources sauvegardée : {gold_bucket}/kpis/city_hourly.parquet ({len(city_hourly)} lignes)")
    
    # Rapport de diagnostic
    status_report = {
        "date_diagnostic_utc": datetime.now(timezone.utc).isoformat(),
        "responsable_croisement": "Personne 3 (Julie)",
        "statut_global": "multi_sources_fusionnees",
        "sources": {
            "meteo_noaa": {
                "statut": "connectee_et_fusionnee" if not df_w.empty else "absente",
                "responsable": "Personne 1 (Rémi)",
                "lignes_source": len(df_w)
            },
            "mobilite_citybikes": {
                "statut": "connectee_et_fusionnee" if not df_m.empty else "absente",
                "responsable": "Personne 2 (Conanbot)",
                "lignes_source": len(df_m)
            },
            "pollution_openaq": {
                "statut": "connectee_et_fusionnee",
                "responsable": "Personne 3 (Julie)",
                "lignes_source": len(df_pollution_hourly)
            }
        },
        "table_croisee": {
            "destination": "gold/kpis/city_hourly.parquet",
            "total_lignes": len(city_hourly),
            "repartition_statuts": city_hourly["statut_jointure"].value_counts().to_dict(),
            "villes": city_hourly["city_id"].unique().tolist()
        }
    }
    
    diag_bytes = json.dumps(status_report, indent=2, ensure_ascii=False).encode("utf-8")
    minio_client.put_object(
        bucket_name=gold_bucket,
        object_name="kpis/diagnostic_couverture_croisee.json",
        data=io.BytesIO(diag_bytes),
        length=len(diag_bytes),
        content_type="application/json"
    )
    print(f"📋 Diagnostic de couverture mis à jour : {gold_bucket}/kpis/diagnostic_couverture_croisee.json")
    return status_report, city_hourly

# ==============================================================================
# PIPELINE GLOBAL
# ==============================================================================

def run_pipeline():
    cities = load_config()
    minio_client = init_datalake_client()
    aq_client = OpenAQClient()
    
    print("\n=== ÉTAPE 1 : Découverte des capteurs & matrice ===")
    matrix, catalog = discover_city_sensors(aq_client, cities)
    print(f"Capteurs découverts : {len(catalog)} capteurs cibles.")
    
    print("\n=== ÉTAPE 2 : Ingestion Bronze (IoT OpenAQ v3) ===")
    ingested_keys = ingest_openaq_to_bronze(minio_client, aq_client, catalog)
    
    print("\n=== ÉTAPE 3 : Nettoyage Silver (Parquet, Déduplication, Unités) ===")
    df_silver = clean_and_transform_to_silver(minio_client)
    
    if df_silver is not None and not df_silver.empty:
        print("\n=== ÉTAPE 4 : Calcul des Indicateurs Gold & Questions Métier ===")
        hourly, zones, diurnal, dominance, anomalies = compute_gold_pollution(minio_client, df_silver)
        
        print("\n=== ÉTAPE 5 : Analyse Croisée & Fusion Multi-sources ===")
        diag, city_hourly = check_and_build_cross_analysis(minio_client, hourly)
        print("\n🎉 Pipeline OpenAQ exécuté avec succès.")
    else:
        print("❌ Aucune donnée Silver générée.")

if __name__ == "__main__":
    run_pipeline()
