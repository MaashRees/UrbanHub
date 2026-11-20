# <img src="assets/icons/bar-chart.svg" width="18" height="18" alt=""> Journal d'Avancement & Feuille de Route - UrbanHub

> **Dernière mise à jour :** 19 novembre 2026  
> **Statut global :** <img src="assets/icons/dot-orange.svg" width="18" height="18" alt=""> Les trois flux sont dans le Data Lake et le croisement fonctionne sur une période courte. Restent la collecte vélos en continu, la planification, la sécurité et les vidéos.  
> **Documents associés :** [Cahier des charges (ENONCE.md)](ENONCE.md) | [Plan d'action (PLAN.md)](PLAN.md) | [Guide Technique & Recettes (GUIDE_TECHNIQUE.md)](GUIDE_TECHNIQUE.md)

Ce document recense l'état d'avancement des différentes composantes de la plateforme **UrbanHub**, les vérifications d'infrastructure réalisées, ainsi que les tâches restantes pour chaque flux.

---

## <img src="assets/icons/wrench.svg" width="18" height="18" alt=""> 1. État des Vérifications Techniques & Environnement

| Composant | Statut | Observations & Diagnostic | Référence / Solution |
| :--- | :---: | :--- | :--- |
| **Data Lake Cloud (Cloudflare R2)** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Opérationnel & Validé | Connexion HTTPS validée sur `*.r2.cloudflarestorage.com`. Buckets `urbanhub-bronze`, `urbanhub-silver`, `urbanhub-gold` accessibles. Test d'écriture/lecture réussi. | [DATALAKE_CLOUD_GUIDE.md](DATALAKE_CLOUD_GUIDE.md) |
| **Data Lake Local (MinIO / Silo)** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Opérationnel | Conteneur `urbanhub-minio` actif sur ports `9000` (API) et `9001` (Console Web). | [docker-compose.yml](../docker-compose.yml) |
| **Dashboard Voilà Dédié** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Opérationnel | Service autonome `urbanhub-dashboard` actif sur le port `8866`. Endpoint validé HTTP 200 OK. | [http://localhost:8866](http://localhost:8866) |
| **Environnement Python (uv)** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Opérationnel | Python 3.11 avec `duckdb`, `pyarrow`, `pandas`, `minio`, `boto3`, `folium`, `seaborn`, `ipywidgets`, `scipy`. | [requirements.txt](../requirements.txt) |
| **API CityBikes (Mobilité)** | <img src="assets/icons/dot-orange.svg" width="18" height="18" alt=""> Collecte partielle | Script de collecte toutes les 5 min sur `main` ([citybikes_stream.py](../scripts/citybikes_stream.py)) et [notebook 02](../notebooks/02_citybikes_stream.ipynb). Au 19/11/2026, seulement 2 cycles ont été collectés dans R2. L'API répond `HTTP 429` si on la sollicite trop vite. | [config/cities.yml](../config/cities.yml) |
| **NOAA Data (Météo)** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Validé | Archive ISD Global Hourly accessible via NODD ; lot France 2020–2024 téléchargé et publié. | [Résultats NOAA](RESULTATS_NOAA.md) |
| **API OpenAQ (Pollution)** | <img src="assets/icons/dot-orange.svg" width="18" height="18" alt=""> Action requise | **Attention :** L'API v2 est dépréciée (`HTTP 410 Gone`). L'API v3 requiert impérativement une clé d'API (`HTTP 401 Unauthorized` sans header `X-API-Key`). Une clé gratuite doit être générée sur le site officiel OpenAQ et placée dans [.env](../.env.example). | [GUIDE_TECHNIQUE.md (Section 3.4)](GUIDE_TECHNIQUE.md#34-ingestion-capteurs-openaq-v3-iot) |
| **Structure du projet** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Structuré | Dossier `docs/` créé avec [ENONCE.md](ENONCE.md), [PLAN.md](PLAN.md), [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md), [DATALAKE_CLOUD_GUIDE.md](DATALAKE_CLOUD_GUIDE.md) et ce fichier [AVANCEMENT.md](AVANCEMENT.md). | Arborescence UrbanHub |

---

## <img src="assets/icons/clipboard.svg" width="18" height="18" alt=""> 2. Suivi Détaillé par Flux & Livrables

### <img src="assets/icons/diamond.svg" width="18" height="18" alt=""> Partie 1 - Flux Batch : Météo Open-Meteo (source officielle)
- [x] [Collecte Open-Meteo](../scripts/openmeteo_batch.py) sur Paris, Lyon et Lille depuis 2020 avec le même modèle ECMWF IFS.
- [x] Bronze JSON et Silver Parquet Open-Meteo publiés. Gold horaire et quotidien publiés aux chemins partagés `kpis/weather_hourly.parquet` et `kpis/weather_daily.parquet` ; archives NOAA conservées sous `kpis/noaa/`.
- [x] Relecture et vérification du Gold : jointure `(city_id, hour_utc)` en UTC, pluie alignée sur le début de chaque heure et visibilité laissée manquante quand absente de l’API. Au 19/11/2026, 181 050 heures-ville, 6 clés communes avec le Gold mobilité et 923 avec le Gold pollution ; aucune clé commune aux trois à cet instant.
- [x] [Notebook du flux Open-Meteo](../notebooks/01_openmeteo_batch.ipynb) exécuté et [bilan météo de référence 2022–2026](RESULTATS_NOAA.md) rédigé à partir du notebook 07 : périodes inhabituelles, saisonnalité, extrêmes et visibilité.
- [ ] Planifier l’actualisation météo et rejouer le calcul de la table croisée lorsque les collectes mobilité et pollution se recouvrent.
- [x] [Script Open-Meteo 2022 à 2026 avec visibilité](../scripts/openmeteo_archive.py) : ERA5 pour les mesures, `historical-forecast` pour la visibilité, 30 requêtes en parallèle, table `weather_hourly_visibility.parquet` au même contrat que le Gold, **sans toucher au Gold partagé**. Vérifié avec 2 requêtes réelles d'un jour (visibilité 24 valeurs sur 24) ; non lancé en entier. À Rémi de décider de la publication

#### Archive NOAA ISD - lot France 2020–2024
- [x] Récupération et prise de connaissance du cahier des charges
- [x] Vérification de l’accessibilité des CSV NOAA ISD via le miroir public NODD.
- [x] Filtrage du catalogue `isd-history.csv` sur `CTRY=FR` et les dates d’activité ; identifiants `USAF + WBAN` conservés comme texte. Le lot inclut 211 stations distinctes.
- [x] Développement et exécution du [script de téléchargement parallèle](../scripts/noaa_batch.py) avec `ThreadPoolExecutor` : 1 029 fichiers récupérés sur 1 048 candidats, 19 absences HTTP 404 consignées dans le manifeste.
- [x] Ingestion **Bronze** : 1 029 CSV bruts du lot France 2020–2024 publiés et vérifiés sous `noaa/year=AAAA/station_id=<identifiant>.csv` sur R2.
- [ ] Versioning natif **Bronze** : bloqué sur Cloudflare R2, dont l’[API S3 ne prend pas en charge le versioning de bucket](https://developers.cloudflare.com/r2/api/s3/api/#unimplemented-bucket-level-operations). Les CSV restent disponibles en copie locale et leurs empreintes ont été vérifiées sur R2. Si le versioning natif est exigé pour la démo, le valider sur un bucket MinIO/Silo séparé.
- [x] Nettoyage **Silver** : données traitées en mémoire par année avec pandas, conversion des unités et de l’horodatage en UTC, déduplication par station et instant ; cinq Parquets écrits avec PyArrow et vérifiés sur R2 (12 483 296 observations).
- [x] Agrégations **Gold** et questions métier : `weather_hourly.parquet` (129 809 heures-ville) et `weather_daily.parquet` (5 450 jours-ville) publiés et relus sur R2 ; notebook France exécuté et conclusions rédigées sur la saisonnalité, les périodes inhabituelles, les extrêmes et la visibilité. [Résultats NOAA archivés](ARCHIVE_RESULTATS_NOAA.md).
- [ ] Filmer la séquence de démo NOAA avec Seer

### <img src="assets/icons/diamond.svg" width="18" height="18" alt=""> Partie 2 - Flux Streaming : Mobilité CityBikes (Fréquence 5 min)
- [x] Validation du endpoint `api.citybik.es/v2/networks` et identification des réseaux dans [config/cities.yml](../config/cities.yml) (`velib`, `velov`, `vlille`)
- [x] [Script de collecte](../scripts/citybikes_stream.py) avec reprise sur erreurs serveur et sans rejeu automatique des `429`. Intervalle de 5 minutes (300 s, valeur par défaut), retenu par l'équipe alors que l'énoncé indique 2 à 3 minutes
- [x] [Notebook de pilotage](../notebooks/02_citybikes_stream.ipynb) (PR #10) ; il est livré sans sorties enregistrées
- [x] **Bronze**, **Silver** et **Gold** publiés dans R2 : 2 248 stations, 6 relevés, `mobility_station_latest` et `mobility_hourly`
- [ ] Collecte **continue** sur plusieurs jours : au 19/11/2026, 2 cycles seulement (11:09 et 11:39 UTC). Sans elle, ni pics journaliers ni déséquilibres géographiques ne sont démontrables
- [x] [Script](../scripts/citybikes_archive.py) et [notebook 06](../notebooks/06_archives_citybikes.ipynb) pour télécharger les **archives officielles CityBikes** (data.citybik.es, ODbL, un Parquet par réseau et par mois) sur 5 ans, 2022 à 2026 : plan, reprise, vérification de taille et de lecture Parquet, publication optionnelle dans Bronze. Plan réel : **61 fichiers, 946 Mo**, car l'archive commence en novembre 2024 (2022 et 2023 absents, mois manquants signalés). Testé sur un serveur factice ; **aucun fichier téléchargé à ce jour**
- [ ] Télécharger les archives, lire leur schéma, les transformer en séries horaires (même forme que le Silver en direct) puis relancer le notebook 04 sur cet historique
- [x] Gold calculé depuis le Silver **publié** quand on est en ligne (R2/MinIO), et tout en local avec `--storage local` : le Silver local d'une machine n'entre plus jamais dans le Gold partagé. Seules les deux dernières heures sont relues puis fusionnées avec le Gold publié
- [x] Gold publié reconstruit le 19/11/2026 avec `--rebuild-gold` : 3 lignes horaires et 2 247 stations, compteurs identiques à ceux du Silver publié (l'ancien Gold, qui avait 6 lignes dont 3 heures sans Silver en ligne, est sauvegardé en local)
- [ ] Relancer le notebook 03 pour que `kpis/mobility_*` (copie harmonisée) et `city_hourly` suivent le nouveau Gold mobilité
- [x] Services de collecte en continu prêts dans `docker-compose.yml` (profil `collect`, voir [DEPLOIEMENT_CONTINU.md](DEPLOIEMENT_CONTINU.md)) ; reste à les démarrer sur une machine toujours allumée, **une seule**
- [x] Reprise du quota CityBikes : au premier `429`, plus aucun appel jusqu'à la fin de l'attente demandée par l'API
- [x] [Notebook d'analyses 04](../notebooks/04_analyses_mobilite.ipynb) : les 5 questions métier de la Partie 2 et le volet vélos de la Partie 4, avec messages de couverture ; sections en attente de plusieurs jours de collecte

### <img src="assets/icons/diamond.svg" width="18" height="18" alt=""> Partie 3 - Flux IoT : Pollution atmosphérique OpenAQ
- [x] Diagnostic de l'API v2 vs v3 ; clé `OPENAQ_API_KEY` valide (une clé de 64 caractères hexadécimaux, la précédente était refusée en `401`)
- [x] Cartographie : 149 capteurs sur Paris, Lyon et Lille, les 5 polluants (`PM2.5`, `PM10`, `NO2`, `O3`, `CO`) disponibles partout
- [x] Ingestion **Bronze** partitionnée par ville et par jour. **Correctif du 19/11/2026** : l'ingestion ne lisait que la première page de 300 mesures (les plus anciennes) et perdait les plus récentes ; `fetch_all_measurements` lit désormais toutes les pages
- [x] **Silver** : unités harmonisées en µg/m³, dédoublonnage sur `(sensor_id, timestamp_utc)` ; 5 719 observations
- [x] **Gold** `pollution_hourly` (3 732 heures, du 05/11 au 19/11/2026 12:00 UTC), classement des zones, profil journalier, dominance rapportée aux seuils OMS, 292 anomalies au-dessus du 95e percentile
- [x] Service `collector-openaq` : pipeline relancé toutes les 2 h avec une fenêtre de 12 h (`OPENAQ_LOOKBACK_HOURS`), filtre des capteurs actifs sur 30 jours au lieu de l'année 2026 écrite en dur
- [ ] Retenir plus de 2 capteurs par polluant et par ville (28 sur 149) et rendre le Silver incrémental (il relit tout le Bronze à chaque exécution)
- [x] [Script d'archive OpenAQ](../scripts/openaq_archive.py) : liste l'archive publique S3 (`openaq-data-archive`, un `csv.gz` par jour et par emplacement), télécharge avec reprise et contrôle, convertit en Silver (mêmes colonnes et règles que le pipeline en direct, ppb et ppm convertis en µg/m³). Plan réel testé : 2 emplacements sur 2022 à 2026 = 3 028 fichiers, 2 Mo. Testé sur serveur factice ; **rien de réel téléchargé**. À régler après comparaison avec l'API : le décalage d'horodatage (`--shift-hours`)
- [ ] Télécharger l'archive OpenAQ, produire `kpis/pollution_monthly.parquet` (colonnes `city_id`, `month`, `pollutant`, `value_mean`) : le dashboard l'affichera dans l'onglet Historique

### <img src="assets/icons/diamond.svg" width="18" height="18" alt=""> Partie 4 - Croisement Analytique Multi-sources
- [x] Clé de jointure commune : `(city_id, hour_utc)` (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#36-calcul-des-indicateurs-gold--jointure-multi-sources))
- [x] Table Gold transversale `kpis/city_hourly.parquet` reconstruite avec la météo Open-Meteo : 181 050 lignes sans doublon, dont **963 heures pollution et météo** et **6 heures à trois sources**
- [x] Météo contre pollution (969 heures) : corrélation du vent avec le NO2 de **−0,61** et avec les PM2,5 de **−0,57** ; pluie contre PM10 de −0,16. Période courte (2 semaines de pollution), à présenter comme un premier résultat
- [ ] Météo contre mobilité douce : seulement 6 heures communes, en attente de la collecte vélos continue
- [x] Cellule simulée du notebook 03 remplacée par une analyse réelle : vent contre NO2 rho -0,65 (970 heures), vent contre PM2,5 rho -0,67 (742 heures), PM10 médiane 11,3 µg/m³ avec pluie contre 19,1 sans (p < 1e-8), ozone corrélé positivement au vent et à la température (ces valeurs portent sur 2 semaines de données en direct : elles ne sont pas représentatives)
- [x] Archives 2022-2026 publiées dans R2 (Open-Meteo avec visibilité, OpenAQ Bronze, Silver et Gold historiques) et analysées dans le notebook 07 : sur 5 ans, vent contre NO2 rho -0,36 (94 297 heures), vent contre PM2,5 rho -0,33, PM10 médiane 10,3 µg/m³ avec pluie contre 15,7 sans, PM2,5 5,9 contre 8,5
- [ ] Synthèse finale des corrélations et seuils de criticité, quand la collecte vélos couvrira plusieurs jours

### <img src="assets/icons/diamond.svg" width="18" height="18" alt=""> Partie 5 - Restitution, Sécurité & Démonstrations (Rôle Seer - Membre 4)
- [x] Stack Docker (`Dockerfile`, `docker-compose.yml` : MinIO Silo, Jupyter, Voilà) et script `scripts/init_datalake.py`
- [x] Dashboard Voilà [05_dashboard](../notebooks/05_dashboard.ipynb) branché sur les tables Gold réelles : KPI météo, carte OpenStreetMap des stations, pollution avec seuils OMS, onglet jumeau numérique. Textes passés à Open-Meteo, périodes affichées calculées depuis les données
- [x] Correctif de l'onglet « Jumeau & Croisement » (`TypeError` sur une colonne entière)
- [x] Icônes SVG à la place des emojis dans les documents, les notebooks et les scripts
- [x] Dashboard : tableau de fraîcheur par source (à jour ou en retard), rafraîchissement automatique de la page toutes les 5 minutes avec la ville conservée, adresse du lac masquée
- [x] Dashboard : onglet **Historique** (température et pluie par mois sur 2020 à 2026, part des jours avec visibilité, historique de pollution quand `kpis/pollution_monthly.parquet` existe, couverture par source, état des trois archives dans le Data Lake) ; Voilà n'affiche plus de trace d'erreur
- [x] Changement de source météo validé avec l'enseignant
- [ ] Configuration de l'utilisateur IAM restreint en lecture seule sur Gold (cf. [policy_gold.json](../../policy_gold.json)) ; aujourd'hui Jupyter n'a pas de mot de passe et les conteneurs montent le `.env` avec les clés d'écriture
- [ ] Génération d'URLs pré-signées pour le partage de synthèses (cf. [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#37-partage-sécurisé-par-urls-pré-signées))
- [ ] Enregistrement vidéo 1 : `demos/Démo-UrbanHub-Partie1.mp4` (avec Rémi)
- [ ] Enregistrement vidéo 2 : `demos/Démo-UrbanHub-Partie2.mp4` (avec Conambot et Julie)

---

## <img src="assets/icons/calendar.svg" width="18" height="18" alt=""> 3. Historique des Actions (Changelog)

- **19/11/2026** :
  - Bascule météo NOAA vers Open-Meteo : script, notebook 01 et Gold publiés (PR #9) ; cahier des charges et simulation de raccord dans [MIGRATION_OPENMETEO.md](MIGRATION_OPENMETEO.md).
  - Dashboard : textes Open-Meteo, périodes affichées calculées, correctif de l'onglet croisement, icônes SVG (PR #8).
  - Correctif de pagination OpenAQ : les mesures vont maintenant jusqu'à l'heure courante ; `city_hourly` reconstruit avec la nouvelle météo (963 heures pollution et météo, 6 heures à trois sources).
  - Sorties à jour pour les notebooks 01 (Open-Meteo), 03 (OpenAQ) et 04 (mobilité).
  - Lancement en continu : services Docker de collecte, respect du quota CityBikes, documents [DEPLOIEMENT_CONTINU.md](DEPLOIEMENT_CONTINU.md) et [MESSAGES_EQUIPE.md](MESSAGES_EQUIPE.md).
  - Restructuration du dossier `UrbanHub/` : création du dossier `docs/` et déplacement de `ENONCE.md` et `PLAN.md`.
  - Création du journal de bord `AVANCEMENT.md`.
  - Rédaction du [GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md) capitalisant sur tous les acquis du cours (`notes.md`, `tp_datalake_partitionnement.ipynb`, etc.).
  - Audit d'infrastructure : test de MinIO (Silo), vérification du runtime Python uv (CPython 3.11), test de connectivité des APIs.
  - Identification du besoin de clé API pour OpenAQ v3 (v2 dépréciée).
  - Normalisation de tous les chemins en chemins relatifs au dépôt (`repo-relative`).
  - Création des répertoires et fichiers socles : `requirements.txt`, `.env.example`, `config/cities.yml`, `notebooks/`, `demos/`.
