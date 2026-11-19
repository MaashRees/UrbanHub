# 📊 Journal d'Avancement & Feuille de Route — UrbanHub

> **Dernière mise à jour :** 19 novembre 2026  
> **Statut global :** 🟡 En phase de cadrage et initialisation technique  
> **Documents associés :** [Cahier des charges (ENONCE.md)](ENONCE.md) | [Plan d'action (PLAN.md)](PLAN.md) | [Guide Technique & Recettes (GUIDE_TECHNIQUE.md)](GUIDE_TECHNIQUE.md)

Ce document recense l'état d'avancement des différentes composantes de la plateforme **UrbanHub**, les vérifications d'infrastructure réalisées, ainsi que les tâches restantes pour chaque flux.

---

## 🛠️ 1. État des Vérifications Techniques & Environnement

| Composant | Statut | Observations & Diagnostic | Référence / Solution |
| :--- | :---: | :--- | :--- |
| **Conteneur MinIO (Silo)** | 🟢 Opérationnel | Conteneur `silo3` actif (`Up 22h`), port API `9000`, console web `9001`. Health check HTTP 200 OK. | [docker-compose.yml](../../docker-compose.yml) |
| **Environnement Python (uv)** | 🟢 Opérationnel | `uv 0.11.14` configuré. Python 3.11 (`cpython-3.11.15`) fonctionnel et stable. Dépendances de base installées (`pandas`, `pyarrow`, `minio`, `requests`, `matplotlib`). | [requirements.txt](../requirements.txt) |
| **API CityBikes (Mobilité)** | 🟢 Accessible | Réponse HTTP 200 sur `http://api.citybik.es/v2/networks`. Prêt pour l'ingestion temps réel. | [config/cities.yml](../config/cities.yml) |
| **NOAA Data (Météo)** | 🟢 Accessible | Réponse HTTP 200 sur le portail NOAA Global Hourly. Prêt pour le téléchargement parallèle. | [GUIDE_TECHNIQUE.md (Section 3.2)](GUIDE_TECHNIQUE.md#32-téléchargement-parallèle-noaa-batch) |
| **API OpenAQ (Pollution)** | 🟠 Action requise | **Attention :** L'API v2 est dépréciée (`HTTP 410 Gone`). L'API v3 requiert impérativement une clé d'API (`HTTP 401 Unauthorized` sans header `X-API-Key`). Une clé gratuite doit être générée sur le site officiel OpenAQ et placée dans [.env](../.env.example). | [GUIDE_TECHNIQUE.md (Section 3.4)](GUIDE_TECHNIQUE.md#34-ingestion-capteurs-openaq-v3-iot) |
| **Structure du projet** | 🟢 Structuré | Dossier `docs/` créé avec [ENONCE.md](ENONCE.md), [PLAN.md](PLAN.md), [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md) et ce fichier [AVANCEMENT.md](AVANCEMENT.md). | Arborescence UrbanHub |

---

## 📋 2. Suivi Détaillé par Flux & Livrables

### 🔹 Partie 1 — Flux Batch : Météo NOAA (Stations France sur 5 ans)
- [x] Récupération et prise de connaissance du cahier des charges
- [x] Vérification de l'accessibilité du serveur NOAA
- [ ] Filtrage du catalogue des stations françaises (`isd-history.csv`)
- [ ] Développement du script de téléchargement parallèle avec `ThreadPoolExecutor` (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#32-téléchargement-parallèle-noaa-batch))
- [ ] Ingestion en zone **Bronze** : `noaa/year=AAAA/<station_id>.csv` (avec versioning activé)
- [ ] Pipeline de nettoyage vers **Silver** Parquet (déduplication, conversion unités, UTC, PyArrow en mémoire)
- [ ] Agrégations et questions métier **Gold** (saisonnalité, extrêmes, visibilité)

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

### 🔹 Partie 5 — Restitution, Sécurité & Démonstrations
- [ ] Configuration de l'utilisateur IAM restreint pour le frontend (cf. [policy_gold.json](../../policy_gold.json))
- [ ] Configuration de l'interface de visualisation (Voilà / Dashboard)
- [ ] Vues dédiées : Météo, Mobilité, Pollution, Analyses croisées
- [ ] Génération d'URLs pré-signées pour le partage de synthèses (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#37-partage-sécurisé-par-urls-pré-signées))
- [ ] Enregistrement vidéo 1 : `demos/Démo-UrbanHub-Partie1.mp4` (Batch NOAA & Data Lake)
- [ ] Enregistrement vidéo 2 : `demos/Démo-UrbanHub-Partie2.mp4` (Flux continus, Dashboard & Croisements)

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
