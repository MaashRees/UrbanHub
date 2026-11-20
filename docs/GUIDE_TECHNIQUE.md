# <img src="assets/icons/book-open.svg" width="18" height="18" alt=""> Guide Technique & Recettes d'Architecture - UrbanHub

> **Objectif :** Ce guide capitalise sur l'ensemble des concepts, codes et retours d'expérience validés dans le cadre des travaux pratiques du cours `Archi_data_lake` ([notes.md](../notes.md), [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb), [tp_datalake_sinistres.ipynb](../tp_datalake_sinistres.ipynb)).  
> Il fournit les **recettes prêtes à l'emploi** pour implémenter chaque étape du jumeau numérique urbain **UrbanHub**.

---

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> Sommaire
1. [Cartographie des Acquis & Références du Dépôt](#1-cartographie-des-acquis--références-du-dépôt)
2. [Structure des Buckets & Partitionnement Hive](#2-structure-des-buckets--partitionnement-hive)
3. [Recettes de Code Clés en Main](#3-recettes-de-code-clés-en-main)
   - [3.1 Connexion S3 idempotente & Versioning](#31-connexion-s3-idempotente--versioning)
   - [3.2 Téléchargement parallèle NOAA (Batch)](#32-téléchargement-parallèle-noaa-batch)
   - [3.3 Ingestion Micro-batch CityBikes (Streaming)](#33-ingestion-micro-batch-citybikes-streaming)
   - [3.4 Ingestion Capteurs OpenAQ v3 (IoT)](#34-ingestion-capteurs-openaq-v3-iot)
   - [3.5 Transformation Silver en Parquet (PyArrow)](#35-transformation-silver-en-parquet-pyarrow)
   - [3.6 Calcul des Indicateurs Gold & Jointure Multi-sources](#36-calcul-des-indicateurs-gold--jointure-multi-sources)
   - [3.7 Partage Sécurisé par URLs Pré-signées](#37-partage-sécurisé-par-urls-pré-signées)
   - [3.8 Sécurisation IAM du Frontend](#38-sécurisation-iam-du-frontend)
4. [Pièges Fréquents & Troubleshooting](#4-pièges-fréquents--troubleshooting)

---

## 1. Cartographie des Acquis & Références du Dépôt

Pour concevoir UrbanHub, nous réutilisons directement les briques éprouvées dans le projet :

| Sujet / Besoin | Fichier de référence dans le repo | Ce qu'on réutilise pour UrbanHub |
| :--- | :--- | :--- |
| **Stockage S3 Local** | [docker-compose.yml](../docker-compose.yml) | Conteneur Silo/MinIO (`localhost:9000`, console sur `9001`). Données persistées dans `../minio_data`. |
| **Partitionnement Hive** | [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb) | Formats de clés S3 `year=YYYY/month=MM/day=DD/` pour élagage (*Partition Pruning*). |
| **Format Parquet & PyArrow** | [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb) | Écriture en mémoire via `io.BytesIO()`, conversion colonnaire, métadonnées utilisateur S3 (`stat.metadata`). |
| **Versioning d'objets** | [tp_datalake_simple.ipynb](../tp_datalake_simple.ipynb) | Activation du versioning sur `bronze` pour auditabilité et reproductibilité des ingestions. |
| **Sécurité IAM & Rôles** | [policy_gold.json](../policy_gold.json) & [notes.md](../notes.md) | Politique `Allow` sur `gold/*` uniquement, pour restreindre l'utilisateur du frontend/dashboard. |
| **Partage sécurisé** | [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb) | Génération d'URLs pré-signées temporaires (`client.get_presigned_url`). |

---

## 2. Structure des Buckets & Partitionnement Hive

Dans UrbanHub, nous appliquons une convention de nommage stricte inspirée du standard Hive :

### <img src="assets/icons/layers-bronze.svg" width="18" height="18" alt=""> Bucket `bronze` (Données brutes, append-only, versioning activé)
- **Météo NOAA :** `noaa/year=YYYY/station_id=<USAF_WBAN>.csv`
- **Mobilité CityBikes :** `citybikes/network=<network_id>/year=YYYY/month=MM/day=DD/snapshot_<HHMMSS>.json`
- **Pollution OpenAQ :** `openaq/city=<city_id>/year=YYYY/month=MM/day=DD/measurements_<HHMMSS>.json`

### <img src="assets/icons/layers-silver.svg" width="18" height="18" alt=""> Bucket `silver` (Données nettoyées, typées, dédupliquées en Parquet)
- `weather/year=YYYY/weather_france.parquet`
- `mobility/year=YYYY/month=MM/mobility_stations.parquet`
- `pollution/year=YYYY/month=MM/pollution_sensors.parquet`

### <img src="assets/icons/layers-gold.svg" width="18" height="18" alt=""> Bucket `gold` (Agrégats métier & tables croisées)
- `kpis/weather_daily.parquet`
- `kpis/mobility_station_latest.parquet` et `kpis/mobility_hourly.parquet`
- `kpis/pollution_hourly.parquet`
- `kpis/city_hourly.parquet` (Table de croisement multi-sources alignée sur `city_id` et `timestamp_hour`)
- `kpis/summary_dashboard.json` (Fichier léger pour affichage direct des cartes KPI)

---

## 3. Recettes de Code Clés en Main

### 3.1 Connexion S3 idempotente & Versioning
*(Inspiré de [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb))*

```python
from minio import Minio
from minio.versioningconfig import VersioningConfig, ENABLED

def init_datalake_client():
    client = Minio(
        "localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin123",
        secure=False
    )
    
    # Création idempotente des 3 buckets
    for bucket in ["bronze", "silver", "gold"]:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"Bucket '{bucket}' créé.")
    
    # Activation du versioning sur Bronze
    client.set_bucket_versioning("bronze", VersioningConfig(ENABLED))
    return client

client = init_datalake_client()
```

---

### 3.2 Téléchargement parallèle NOAA (Batch)
L'énoncé exige un **téléchargement parallèle** des stations météo françaises sur les 5 dernières années.

```python
import io
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

NOAA_BASE_URL = "https://www.ncei.noaa.gov/data/global-hourly/access"

def download_and_store_station(client, station_id, year):
    """Télécharge un fichier station-année et le pousse directement dans Bronze."""
    url = f"{NOAA_BASE_URL}/{year}/{station_id}.csv"
    s3_path = f"noaa/year={year}/{station_id}.csv"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UrbanHub/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
            
        client.put_object(
            bucket_name="bronze",
            object_name=s3_path,
            data=io.BytesIO(content),
            length=len(content),
            content_type="text/csv",
            metadata={"source": "NOAA", "station_id": station_id, "year": str(year)}
        )
        return station_id, year, "OK", len(content)
    except Exception as e:
        return station_id, year, f"ERROR: {str(e)}", 0

def fetch_all_noaa_parallel(client, station_list, years, max_workers=8):
    """Orchestre le téléchargement parallèle borné à max_workers threads."""
    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for year in years:
            for station_id in station_list:
                tasks.append(executor.submit(download_and_store_station, client, station_id, year))
        
        for future in as_completed(tasks):
            st_id, yr, status, size = future.result()
            print(f"[{status}] Station {st_id} ({yr}) - {size} octets")
```

---

### 3.3 Ingestion Micro-batch CityBikes (Streaming)
Collecte toutes les 5 minutes pour les réseaux configurés dans [config/cities.yml](../config/cities.yml) (ex: `velib-metropole`, `velo-v`, `vlille`).

```python
import io
import json
import urllib.request
from datetime import datetime, timezone

def capture_citybikes_snapshot(client, network_id="velib-metropole"):
    """Récupère l'état instantané des stations et l'archive dans Bronze."""
    url = f"http://api.citybik.es/v2/networks/{network_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "UrbanHub-Stream/1.0"})
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        
    now = datetime.now(timezone.utc)
    date_path = now.strftime("year=%Y/month=%m/day=%d")
    time_str = now.strftime("%H%M%S")
    s3_path = f"citybikes/network={network_id}/{date_path}/snapshot_{time_str}.json"
    
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    
    client.put_object(
        bucket_name="bronze",
        object_name=s3_path,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type="application/json",
        metadata={
            "network": network_id,
            "ingestion_utc": now.isoformat(),
            "stations_count": str(len(data.get("network", {}).get("stations", [])))
        }
    )
    print(f"[OK] Instantané CityBikes sauvegardé : bronze/{s3_path}")
```

---

### 3.4 Ingestion Capteurs OpenAQ v3 (IoT)
> **Rappel essentiel :** L'API v2 est dépréciée (`HTTP 410`). L'API v3 nécessite une clé passée dans le header `X-API-Key`.

```python
import os
import io
import json
import urllib.request
from datetime import datetime, timezone

OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "")

def fetch_openaq_measurements(client, location_id, city_name="Paris"):
    """Récupère les dernières mesures IoT d'une station OpenAQ."""
    url = f"https://api.openaq.org/v3/locations/{location_id}/latest"
    req = urllib.request.Request(url, headers={
        "X-API-Key": OPENAQ_API_KEY,
        "User-Agent": "UrbanHub-IoT/1.0"
    })
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        
    now = datetime.now(timezone.utc)
    date_path = now.strftime("year=%Y/month=%m/day=%d")
    time_str = now.strftime("%H%M%S")
    s3_path = f"openaq/city={city_name}/{date_path}/loc_{location_id}_{time_str}.json"
    
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    client.put_object(
        bucket_name="bronze",
        object_name=s3_path,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type="application/json",
        metadata={"city": city_name, "location_id": str(location_id)}
    )
    print(f"[OK] Mesures OpenAQ archivées : bronze/{s3_path}")
```

---

### 3.5 Transformation Silver en Parquet (PyArrow)
*(Patron issu de [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb))*

```python
import io
import pandas as pd
from datetime import datetime, timezone

def upload_dataframe_to_silver_parquet(client, df, s3_object_path, author="data_engineer"):
    """Convertit un DataFrame pandas en Parquet en mémoire et l'écrit dans Silver."""
    # 1. Ajout de la date de traitement d'audit
    df_clean = df.copy()
    df_clean["date_traitement_utc"] = datetime.now(timezone.utc).isoformat()
    
    # 2. Conversion Parquet en mémoire vive avec compression snappy (par défaut PyArrow)
    parquet_buffer = io.BytesIO()
    df_clean.to_parquet(parquet_buffer, index=False, engine="pyarrow")
    parquet_bytes = parquet_buffer.getvalue()
    
    # 3. Pousser vers MinIO Silver avec métadonnées S3
    client.put_object(
        bucket_name="silver",
        object_name=s3_object_path,
        data=io.BytesIO(parquet_bytes),
        length=len(parquet_bytes),
        content_type="application/x-parquet",
        metadata={
            "auteur": author,
            "source": "bronze",
            "format": "parquet",
            "lignes": str(len(df_clean))
        }
    )
    print(f"Écrit dans silver/{s3_object_path} ({len(parquet_bytes)} octets, {len(df_clean)} lignes)")

def read_silver_parquet(client, s3_object_path):
    """Lit un fichier Parquet depuis Silver directement en DataFrame."""
    resp = client.get_object("silver", s3_object_path)
    df = pd.read_parquet(io.BytesIO(resp.read()))
    resp.close()
    resp.release_conn()
    return df
```

---

### 3.6 Calcul des Indicateurs Gold & Jointure Multi-sources

Pour répondre à la **Partie 4 (Analyse croisée)**, nous agrégeons chaque flux sur la même maille spatio-temporelle : `(city_id, timestamp_hour)`.

```python
import io
import json
import pandas as pd
from datetime import datetime, timezone

def build_city_hourly_gold(client, df_weather, df_mobility, df_pollution):
    """
    Jointure multi-sources sur city_id et hour_utc.
    Chaque source doit au préalable être agrégée à l'heure.
    """
    # 1. Troncature de l'horodatage à l'heure exacte
    df_weather["hour_utc"] = pd.to_datetime(df_weather["timestamp"]).dt.floor("h")
    df_mobility["hour_utc"] = pd.to_datetime(df_mobility["timestamp"]).dt.floor("h")
    df_pollution["hour_utc"] = pd.to_datetime(df_pollution["timestamp"]).dt.floor("h")
    
    # 2. Agrégations intermédiaires horaires par ville
    w_hourly = df_weather.groupby(["city_id", "hour_utc"]).agg({
        "temperature": "mean",
        "precipitation": "sum",
        "wind_speed": "mean",
        "visibility": "mean"
    }).reset_index()
    
    m_hourly = df_mobility.groupby(["city_id", "hour_utc"]).agg({
        "bikes_available": "sum",
        "free_slots": "sum"
    }).reset_index()
    
    p_hourly = df_pollution.groupby(["city_id", "hour_utc", "pollutant"])["value"].mean().unstack().reset_index()
    
    # 3. Jointure externe (outer) ou interne (inner) selon couverture
    city_hourly = w_hourly.merge(m_hourly, on=["city_id", "hour_utc"], how="inner")
    city_hourly = city_hourly.merge(p_hourly, on=["city_id", "hour_utc"], how="inner")
    
    # 4. Sauvegarde dans Gold
    parquet_buffer = io.BytesIO()
    city_hourly.to_parquet(parquet_buffer, index=False, engine="pyarrow")
    
    client.put_object(
        bucket_name="gold",
        object_name="kpis/city_hourly.parquet",
        data=io.BytesIO(parquet_buffer.getvalue()),
        length=len(parquet_buffer.getvalue()),
        content_type="application/x-parquet"
    )
    print("Table Gold multi-sources 'city_hourly.parquet' générée avec succès.")
    return city_hourly
```

---

### 3.7 Partage Sécurisé par URLs Pré-signées
*(Validé dans [tp_datalake_partitionnement.ipynb](../tp_datalake_partitionnement.ipynb))*

Permet de donner un accès temporaire (sans identifiants) au dashboard ou aux partenaires :

```python
from datetime import timedelta

def generate_report_presigned_url(client, object_name="kpis/summary_dashboard.json", hours=2):
    """Génère une URL publique temporaire de téléchargement sécurisé."""
    url = client.get_presigned_url(
        method="GET",
        bucket_name="gold",
        object_name=object_name,
        expires=timedelta(hours=hours)
    )
    return url

url = generate_report_presigned_url(client)
print("Lien sécurisé temporaire (2h) :", url)
```

---

### 3.8 Sécurisation IAM du Frontend
*(Validé dans [notes.md](../notes.md) et [policy_gold.json](../policy_gold.json))*

Le frontend (ex. Voilà) ne doit avoir accès **qu'à la couche Gold** en lecture seule :

```powershell
# 1. Créer l'utilisateur frontend dans MinIO Silo
docker exec silo3 mcli admin user add local frontend_user FrontPass2026!

# 2. Copier la politique policy_gold.json dans le conteneur
docker cp policy_gold.json silo3:/tmp/policy_gold.json

# 3. Créer et attacher la politique restreinte
docker exec silo3 mcli admin policy create local lecture_gold /tmp/policy_gold.json
docker exec silo3 mcli admin policy attach local lecture_gold --user frontend_user
```

---

## 4. Pièges Fréquents & Troubleshooting

| Problème rencontré | Cause racine | Solution éprouvée |
| :--- | :--- | :--- |
| **`[Errno 11001] getaddrinfo failed`** | Utilisation de `"minio:9000"` depuis un script exécuté sur l'hôte Windows. | Remplacer par `"localhost:9000"`. Réserver `"minio"` uniquement aux communications inter-conteneurs Docker. |
| **`OpenAQ HTTP Error 410 Gone`** | Tentative d'utilisation de l'ancienne API v2 dépréciée. | Basculer sur l'API v3 (`https://api.openaq.org/v3/...`) avec l'entête `X-API-Key`. |
| **`OpenAQ HTTP Error 401 Unauthorized`** | Clé API absente ou invalide. | Récupérer une clé gratuite sur le site OpenAQ et la déclarer dans `.env` (`OPENAQ_API_KEY`). |
| **Doublons à la ré-exécution du streaming** | Polling répété sur les mêmes créneaux temporels. | Dédupliquer systématiquement sur `(network_id, station_id, timestamp)` lors du passage en Silver. |
| **Perte des zéros initiaux des stations NOAA** | Codes USAF/WBAN interprétés comme des entiers au lieu de chaînes de caractères. | Spécifier `dtype={'station_id': str}` ou formater avec `str(station_id).zfill(6)`. |
| **`Implicit Deny` IAM MinIO** | Un utilisateur créé dans MinIO n'a aucune politique attachée. | Toujours attacher une politique IAM explicite (`mcli admin policy attach`). |
| **Script Python bloqué par les alias Microsoft Store** | `python.exe` pointe vers les liens symboliques WindowsApps protégés. | Exécuter via `uv run python mon_script.py` ou appeler directement l'interpréteur uv. |
