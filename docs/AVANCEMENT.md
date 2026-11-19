# 📊 Journal d'Avancement & Feuille de Route — UrbanHub

> **Dernière mise à jour :** 19 novembre 2026  
> **Statut global :** 🟡 En phase de cadrage et initialisation technique  
> **Documents associés :** [Cahier des charges (ENONCE.md)](ENONCE.md) | [Plan d'action (PLAN.md)](PLAN.md) | [Guide Technique & Recettes (GUIDE_TECHNIQUE.md)](GUIDE_TECHNIQUE.md)

Ce document recense l'état d'avancement des différentes composantes de la plateforme **UrbanHub**, les vérifications d'infrastructure réalisées, ainsi que les tâches restantes pour chaque flux.

---

## 🛠️ 1. État des Vérifications Techniques & Environnement

| Composant | Statut | Observations & Diagnostic | Référence / Solution |
| :--- | :---: | :--- | :--- |
| **Data Lake Cloud (Cloudflare R2)** | 🟢 Opérationnel & Validé | Connexion HTTPS validée sur `*.r2.cloudflarestorage.com`. Buckets `urbanhub-bronze`, `urbanhub-silver`, `urbanhub-gold` accessibles. Test d'écriture/lecture réussi. | [DATALAKE_CLOUD_GUIDE.md](DATALAKE_CLOUD_GUIDE.md) |
| **Data Lake Local (MinIO / Silo)** | 🟢 Opérationnel | Conteneur `urbanhub-minio` actif sur ports `9000` (API) et `9001` (Console Web). | [docker-compose.yml](../docker-compose.yml) |
| **Dashboard Voilà Dédié** | 🟢 Opérationnel | Service autonome `urbanhub-dashboard` actif sur le port `8866`. Endpoint validé HTTP 200 OK. | [http://localhost:8866](http://localhost:8866) |
| **Environnement Python (uv)** | 🟢 Opérationnel | Python 3.11 avec `duckdb`, `pyarrow`, `pandas`, `minio`, `boto3`, `folium`, `seaborn`, `ipywidgets`, `scipy`. | [requirements.txt](../requirements.txt) |
| **API CityBikes (Mobilité)** | 🟢 Accessible | Réponse HTTP 200 sur `http://api.citybik.es/v2/networks`. Prêt pour l'ingestion temps réel. | [config/cities.yml](../config/cities.yml) |
| **NOAA Data (Météo)** | 🟢 Validé | Archive ISD Global Hourly accessible via NODD ; lot France 2020–2024 téléchargé et publié. | [Résultats NOAA](RESULTATS_NOAA.md) |
| **API OpenAQ (Pollution)** | 🟠 Action requise | **Attention :** L'API v2 est dépréciée (`HTTP 410 Gone`). L'API v3 requiert impérativement une clé d'API (`HTTP 401 Unauthorized` sans header `X-API-Key`). Une clé gratuite doit être générée sur le site officiel OpenAQ et placée dans [.env](../.env.example). | [GUIDE_TECHNIQUE.md (Section 3.4)](GUIDE_TECHNIQUE.md#34-ingestion-capteurs-openaq-v3-iot) |
| **Structure du projet** | 🟢 Structuré | Dossier `docs/` créé avec [ENONCE.md](ENONCE.md), [PLAN.md](PLAN.md), [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md), [DATALAKE_CLOUD_GUIDE.md](DATALAKE_CLOUD_GUIDE.md) et ce fichier [AVANCEMENT.md](AVANCEMENT.md). | Arborescence UrbanHub |

---

## 📋 2. Suivi Détaillé par Flux & Livrables

### 🔹 Partie 1 — Flux Batch : Météo NOAA (Stations France sur 5 ans)
- [x] Récupération et prise de connaissance du cahier des charges
- [x] Vérification de l’accessibilité des CSV NOAA ISD via le miroir public NODD.
- [x] Filtrage du catalogue `isd-history.csv` sur `CTRY=FR` et les dates d’activité ; identifiants `USAF + WBAN` conservés comme texte. Le lot inclut 211 stations distinctes.
- [x] Développement et exécution du [script de téléchargement parallèle](../scripts/noaa_batch.py) avec `ThreadPoolExecutor` : 1 029 fichiers récupérés sur 1 048 candidats, 19 absences HTTP 404 consignées dans le manifeste.
- [x] Ingestion **Bronze** : 1 029 CSV bruts du lot France 2020–2024 publiés et vérifiés sous `noaa/year=AAAA/station_id=<identifiant>.csv` sur R2.
- [ ] Versioning natif **Bronze** : bloqué sur Cloudflare R2, dont l’[API S3 ne prend pas en charge le versioning de bucket](https://developers.cloudflare.com/r2/api/s3/api/#unimplemented-bucket-level-operations). Les CSV restent disponibles en copie locale et leurs empreintes ont été vérifiées sur R2. Si le versioning natif est exigé pour la démo, le valider sur un bucket MinIO/Silo séparé.
- [x] Nettoyage **Silver** : données traitées en mémoire par année avec pandas, conversion des unités et de l’horodatage en UTC, déduplication par station et instant ; cinq Parquets écrits avec PyArrow et vérifiés sur R2 (12 483 296 observations).
- [x] Agrégations **Gold** et questions métier : `weather_hourly.parquet` (129 809 heures-ville) et `weather_daily.parquet` (5 450 jours-ville) publiés et relus sur R2 ; notebook France exécuté et conclusions rédigées sur la saisonnalité, les périodes inhabituelles, les extrêmes et la visibilité. [Résultats, limites et déroulé de démo](RESULTATS_NOAA.md).
- [ ] Filmer la séquence de démo NOAA avec Seer

### 🔹 Partie 2 — Flux Streaming : Mobilité CityBikes (Fréquence 2-3 min)
- [x] Validation du endpoint `api.citybik.es/v2/networks`
- [x] Identification des réseaux français cibles dans [config/cities.yml](../config/cities.yml) (`velib-metropole`, `velo-v`, `vlille`)
- [ ] Script d'interrogation récurrente (scheduler / worker micro-batch)
- [ ] Stockage brut **Bronze** avec partitionnement Hive : `citybikes/network=<id>/year=YYYY/month=MM/day=DD/snapshot_<HHMMSS>.json`
- [ ] Structuration en table **Silver** Parquet (`free_bikes`, `empty_slots`, `station_id`, `latitude`, `longitude`)
- [ ] Calcul des indicateurs **Gold** (taux de rupture, saturation, détection stations critiques)

### 🔹 Partie 3 — Flux IoT : Pollution atmosphérique OpenAQ
- [x] Diagnostic de l'API v2 vs v3
- [ ] Obtention et configuration de la variable d'environnement `OPENAQ_API_KEY`
- [ ] Cartographie des capteurs français et polluants disponibles (`PM2.5`, `PM10`, `NO2`, `O3`, `CO`)
- [ ] Collecte planifiée des mesures et stockage **Bronze** avec partitionnement Hive
- [ ] Nettoyage, harmonisation des unités (`µg/m³`, `ppm`) vers **Silver** Parquet
- [ ] Détection des anomalies et profils journaliers **Gold**

### 🔹 Partie 4 — Croisement Analytique Multi-sources
- [x] Définition de la clé de jointure commune : `(city_id, hour_utc)` (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#36-calcul-des-indicateurs-gold--jointure-multi-sources))
- [ ] Table Gold transversale : `kpis/city_hourly.parquet`
- [ ] Analyse croisée météo vs pollution (dispersion par le vent, inversion thermique)
- [ ] Analyse croisée météo vs mobilité douce (impact pluie / température sur le vélo)
- [ ] Synthèse des corrélations et seuils de criticité

### 🔹 Partie 5 — Restitution, Sécurité & Démonstrations (Rôle Seer - Membre 4)
- [x] Création de la stack Docker simple : `Dockerfile` et `docker-compose.yml` (MinIO Silo + Jupyter + Voilà)
- [x] Script d'initialisation automatique du Data Lake : `scripts/init_datalake.py` (création buckets et versioning)
- [x] Initialisation du squelette du Dashboard Voilà : `notebooks/05_dashboard.ipynb` (sélecteurs de villes et onglets)
- [ ] Configuration de l'utilisateur IAM restreint pour le frontend (cf. [policy_gold.json](../../policy_gold.json))
- [ ] Branchement des premiers KPI réels dans le dashboard dès réception des tables Gold
- [ ] Génération d'URLs pré-signées pour le partage de synthèses (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#37-partage-sécurisé-par-urls-pré-signées))
- [ ] Enregistrement vidéo 1 : `demos/Démo-UrbanHub-Partie1.mp4` (avec Rémi)
- [ ] Enregistrement vidéo 2 : `demos/Démo-UrbanHub-Partie2.mp4` (avec Conambot et Julie)

---

## 📅 3. Historique des Actions (Changelog)

- **19/11/2026** :
  - Restructuration du dossier `UrbanHub/` : création du dossier `docs/` et déplacement de `ENONCE.md` et `PLAN.md`.
  - Création du journal de bord `AVANCEMENT.md`.
  - Rédaction du [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md) capitalisant sur tous les acquis du cours (`notes.md`, `tp_datalake_partitionnement.ipynb`, etc.).
  - Audit d'infrastructure : test de MinIO (Silo), vérification du runtime Python uv (CPython 3.11), test de connectivité des APIs.
  - Identification du besoin de clé API pour OpenAQ v3 (v2 dépréciée).
  - Normalisation de tous les chemins en chemins relatifs au dépôt (`repo-relative`).
  - Création des répertoires et fichiers socles : `requirements.txt`, `.env.example`, `config/cities.yml`, `notebooks/`, `demos/`.
