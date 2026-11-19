# UrbanHub ROADMAP

**Les deux priorités :**

1. **Démarrer CityBikes dans les 30 premières minutes** pour accumuler des observations.
2. **Afficher un premier KPI réel dans le frontend avant la troisième heure** pour valider l’intégration tôt.

## 1. Architecture et choix du Data Lake

```text
NOAA (batch parallèle) ───────────┐
CityBikes (relevé toutes les 5 min) ├──► Bronze ───► Silver ──► Gold ──► Frontend Voilà
OpenAQ (collecte régulière) ────────┘     brut       Parquet     KPI       navigateur
                                                      │
                                               DuckDB / Athena
```

| Option | Stockage | Gestion et requêtes | Recommandation |
| --- | --- | --- | --- |
| **Local** | MinIO dans Docker, avec volume persistant | Console MinIO pour les objets et les accès ; DuckDB et vues SQL pour explorer les tables Parquet | Choix par défaut : vous l’avez déjà utilisé en TP et les quatre membres peuvent travailler sans attendre un compte cloud. |
| **Cloud avec catalogue managé** | Amazon S3 | AWS Glue Data Catalog pour les tables et schémas ; Athena pour les requêtes SQL | Si le cloud est obligatoire et que le compte est prêt. Pour la démo, cataloguez au moins une table Silver et une table Gold. |
| **Cloud compatible S3** | Scaleway Object Storage ou Cloudflare R2 | DuckDB pour les requêtes ; schémas déclarés dans le dépôt | Pertinent si vous avez déjà un accès. Cette option ne fournit pas, à elle seule, un catalogue de données. |

La console MinIO gère les objets ; DuckDB permet de les interroger ; Glue est un catalogue. Si « gestionnaire du Data Lake » désigne un catalogue obligatoire dans votre cours, faites valider ce point au départ. Même chose pour « Silo » : vérifiez le nom exact avant d’en faire une dépendance du projet.

### Services Docker

- **`minio`** : stockage local. Les notebooks utilisent `boto3` et une configuration commune pour pointer vers MinIO ou vers le cloud.
- **`jupyter`** : édition et exécution manuelle des notebooks.
- **`worker`** : exécution automatique des notebooks avec Papermill. Prévoyez un lancement ponctuel pour tester chaque collecte et des tâches indépendantes pour que le batch NOAA ne bloque pas CityBikes. Pour la collecte à cinq minutes, suivez les heures de passage et évitez que deux exécutions du même flux se chevauchent.
- **`frontend`** : Voilà sert le notebook de démo dans le navigateur. Il lit uniquement Gold, avec un accès en lecture seule. Si votre enseignant entend par *frontend* une application JavaScript séparée, validez ce point dès le départ : Voilà répond au besoin d’interface web, mais n’est pas un projet React distinct.

## 2. Organisation du dépôt

```text
urbanhub/
├── compose.yaml
├── Dockerfile
├── requirements.txt
├── .env.example
├── README.md
├── config/
│   └── cities.yml
├── notebooks/
│   ├── 01_noaa_batch.ipynb
│   ├── 02_citybikes_stream.ipynb
│   ├── 03_openaq_iot.ipynb
│   ├── 04_traitement_kpis.ipynb
│   └── 05_dashboard.ipynb
└── demos/
    ├── Démo-UrbanHub-Partie1.mp4
    └── Démo-UrbanHub-Partie2.mp4
```

### Contrat de données à fixer ensemble en 20 minutes

- **Bronze** : réponses CSV/JSON d’origine, rangées par source et par date. Gardez l’heure de la mesure et l’heure d’ingestion séparées.
- **Silver** : une table Parquet par source, avec colonnes typées, unités documentées, horodatages UTC et déduplication à la relance.
- **Gold** : tables d’indicateurs, par exemple `weather_daily`, `mobility_station_latest`, `pollution_hourly` et `city_hourly`. Publiez une petite sortie JSON pour les cartes KPI et du Parquet pour les séries et les cartes si nécessaire. Fixez leurs clés dès le début pour que le frontend puisse avancer en parallèle.
- **Jointure** : même `city_id`, même heure UTC. Agrégez chaque source séparément par **ville × heure** avant de joindre. Affichez ensuite les heures en heure locale dans le dashboard, ainsi que le nombre d’heures réellement communes.

## 3. Répartition pour quatre personnes

| Personne | Responsabilité | Résultat transmis au groupe |
| --- | --- | --- |
| **1 - Météo NOAA** | Identifier les stations françaises et lancer en parallèle les téléchargements station–année sur cinq ans. Décoder les champs météo, les unités et les valeurs manquantes. Garder la durée de mesure des précipitations. | Un petit échantillon utilisable rapidement, puis le bilan du téléchargement complet : réussites, absences et erreurs. Fournir la saisonnalité, les extrêmes et un graphique météo–visibilité. |
| **2 - Mobilité CityBikes** | Lancer la collecte toutes les 3 minutes, conserver les instantanés et calculer les indicateurs de disponibilité. | Deux instantanés horodatés pour valider le démarrage, puis disponibilité par heure et liste des stations vides, pleines ou souvent critiques. |
| **3 - Pollution OpenAQ et croisement** | Vérifier la clé API et la couverture, collecter les mesures des capteurs et normaliser les unités par polluant. Construire la jointure horaire avec les deux autres responsables de source. | Profils horaires et anomalies par polluant, bilan de couverture et première comparaison croisée sur les périodes communes. |
| **4 - Docker, intégration et frontend** | Monter Compose, définir les chemins communs, intégrer les transformations dans `04_traitement_kpis.ipynb` et construire le dashboard Voilà. | Une URL locale de démo, un premier KPI issu de Gold et un parcours de démonstration prêt avant l’enregistrement. |

La personne 4 intègre les traitements ; les trois autres restent responsables du nettoyage de leur source et de la définition de leurs KPI. Paris est la première ville candidate pour la démo. Ajoutez Lyon et Lille, ou d’autres villes mieux couvertes, dès que l’intersection des sources est confirmée. Le téléchargement météo vise la France sur cinq ans, indépendamment du nombre de villes affichées lors de la démo.

### Personne 1 - Météo NOAA : batch, qualité et indicateurs

**Fichier principal :** `notebooks/01_noaa_batch.ipynb`. **Paramètres :** fenêtre de dates, mode échantillon ou France, nombre de téléchargements simultanés.

- [ ] **0 h 00–0 h 30 :** récupérer le catalogue NOAA ISD, filtrer les stations françaises et construire les identifiants à partir des codes USAF/WBAN sans perdre les zéros initiaux. Vérifier les dates d’activité et tester un fichier récent pour une station proche de Paris. Noter les dates exactes des cinq années retenues.
- [ ] **0 h 30–1 h 15 :** lancer les couples station–année avec un pool borné (par exemple 8 téléchargements simultanés). Écrire les CSV dans `bronze/noaa/year=AAAA/<station_id>.csv`. Sauter les objets déjà présents selon le mode de reprise. Distinguer les fichiers absents des erreurs réseau, enregistrer les résultats dans un manifeste et lancer le lot France en arrière-plan après validation de l’échantillon.
- [ ] **1 h 15–2 h 30 :** lire les colonnes NOAA utiles (`DATE`, `TMP`, `WND`, `VIS`, `SLP`, `AA1` et autres champs de précipitation disponibles). Appliquer les codes manquants et les échelles du format NOAA ; produire température en °C, vent en m/s et degrés, pression en hPa, visibilité en m et précipitation en mm. Conserver la durée d’accumulation et ne sommer que des périodes non chevauchantes. Attribuer les stations proches aux villes avec le référentiel partagé ; conserver les autres pour l’analyse nationale. Écrire Silver par année et dédupliquer sur `(station_id, timestamp_utc)` avec une règle documentée en cas d’observations concurrentes.
- [ ] **2 h 30–4 h 00 :** fournir une série mensuelle par ville, une comparaison nationale avec nombre de stations couvertes, un nuage météo–visibilité et des jours extrêmes ou anormaux. Exemple : repérer les jours au-dessus du 95e percentile de température maximale **par ville et saison**, sur la période disponible, et afficher le seuil et le nombre de jours de référence.

**À remettre :** un échantillon Silver au plus tard à **2 h 30**, `weather_daily` et une sortie météo horaire par ville pour le croisement, puis le manifeste de téléchargement pour la vidéo 1. **Validation :** montrer des téléchargements simultanés, relire le Parquet, vérifier les conversions sur quelques lignes et annoncer la couverture réelle du lot France.

### Personne 2 - CityBikes : collecte toutes les cinq minutes et KPI mobilité

**Fichier principal :** `notebooks/02_citybikes_stream.ipynb`. **Paramètres :** villes ou réseaux, heure de collecte et mode « un seul relevé » pour Papermill. Le worker gère la répétition.

- [ ] **0 h 00–0 h 30 :** lister les réseaux français depuis `/v2/networks`, relever leurs identifiants et tester un appel par réseau. Démarrer Paris dès que l’écriture dans Bronze fonctionne. Ajouter les autres réseaux vérifiés sans interrompre la collecte initiale.
- [ ] **0 h 30–1 h 15 :** écrire un JSON brut par réseau et créneau UTC sous `bronze/citybikes/network=<id>/date=AAAA-MM-JJ/<créneau>.json`. Configurer le worker à **3 minutes**, avec délai d’attente réseau, journal des erreurs par réseau et créneaux sans chevauchement. Vérifier deux captures de données consécutives avant de passer à l’analyse.
- [ ] **1 h 15–2 h 30 :** mapper `id`, `name`, `latitude`, `longitude`, `timestamp`, `free_bikes` et `empty_slots` vers les champs Silver. Garder `network_id`, `city_id`, l’heure de la source et l’heure du relevé. Dédupliquer les relances sur `(network_id, station_id, créneau_utc)` ; conserver les vrais relevés successifs même si le stock n’a pas changé. Signaler les coordonnées ou stocks absents et exclure les stations hors service des taux si ce statut est fourni.
- [ ] **2 h 30–4 h 00 :** calculer le taux de rupture `relevés valides à zéro vélo / relevés valides`, et le taux de saturation de la même manière pour les places libres. Afficher le dernier stock et le nombre de relevés. Pour la carte, proposer une règle réglable, par exemple « souvent vide ou pleine » à partir de **30 % des relevés et au moins 10 relevés valides**. Comparer des zones avec une grille simple et signaler les cellules peu couvertes. Pour les heures de pointe, afficher les heures les plus tendues **sur la période observée**, sans extrapoler à une journée type.

**À remettre :** une preuve des deux premiers créneaux, `mobility_station_latest` et `mobility_hourly` avec nombre de relevés et de stations. **Validation :** vérifier qu’une relance du même créneau ne double pas les données et qu’une station sans mesure valide n’est pas affichée comme vide. Les variations de stock, si utilisées pour classer les stations, restent un indicateur indirect d’activité.

### Personne 3 - OpenAQ : capteurs, contrôle des unités et analyse croisée

**Fichier principal :** `notebooks/03_openaq_iot.ipynb`. **Paramètres :** villes, polluants, intervalle, borne de rattrapage ; la clé `OPENAQ_API_KEY` vient de l’environnement.

- [ ] **0 h 00–0 h 30 :** vérifier l’accès à OpenAQ v3, découvrir les sites français puis les capteurs autour des villes retenues. Relever les identifiants, le dernier horodatage, les coordonnées et les unités. Faire une matrice **ville × polluant disponible** pour PM2.5, PM10, O₃, CO et NO₂ ; signaler les absences au groupe tôt.
- [ ] **0 h 30–1 h 30 :** charger un historique court pour les capteurs retenus, puis lancer un relevé régulier à une cadence compatible avec l’API (par exemple 15 min). Prévoir pagination, reprise après erreur `429` et une petite fenêtre de recouvrement pour récupérer les mesures tardives. Garder les réponses brutes horodatées dans `bronze/openaq/`. Avancer le point de reprise après écriture réussie.
- [ ] **1 h 30–2 h 30 :** produire `sensor_id`, `pollutant`, `timestamp_utc`, `latitude`, `longitude`, `value`, `unit` et `city_id` en Silver. Dédupliquer par `(sensor_id, timestamp_utc)` pour la série et la granularité retenues. Conserver l’unité avec la valeur et séparer les séries d’unités incompatibles. Documenter le traitement des valeurs manquantes et des mesures signalées par la source.
- [ ] **2 h 30–4 h 00 :** produire `pollution_hourly` et un classement des zones **pour un même polluant et une même unité**. Pour les anomalies, utiliser un seuil documenté par polluant, ville et unité si l’historique est suffisant ; sinon montrer les pics observés avec la couverture. Pour comparer la « dominance » entre polluants, utiliser un ratio à une référence documentée de même unité et durée, si elle existe ; sinon présenter les profils séparément.
- [ ] **À partir de 3 h 00 :** avec les personnes 1 et 2, aligner les trois sorties horaires sur `(city_id, hour_utc)` et publier `city_hourly`. Compter les heures météo–pollution, météo–vélos et communes aux trois sources. Graphiques prioritaires : vent–pollution et pluie/température–disponibilité ; comparer si possible des heures locales similaires et donner la taille de l’échantillon. Si les dates ne se recouvrent pas assez, publier le diagnostic plutôt qu’interpoler ou fabriquer des données.

**À remettre :** l’échantillon Silver, `pollution_hourly`, `city_hourly` et le diagnostic de couverture pour le frontend. **Validation :** relire des mesures réelles, vérifier unités et doublons, vérifier que les jointures ne multiplient pas les lignes. Si la clé ou la couverture bloque, documenter l’erreur ou les dates réellement disponibles ; le dashboard affiche cet état.

### Personne 4 - Docker, intégration et frontend Voilà

**Fichiers principaux :** `compose.yaml`, `Dockerfile`, `.env.example`, `README.md`, `notebooks/04_traitement_kpis.ipynb` et `notebooks/05_dashboard.ipynb`. Les responsables de source restent propriétaires de leurs notebooks et de leurs formules.

- [ ] **0 h 00–0 h 30 :** démarrer MinIO avec volume persistant et Jupyter, ou tester immédiatement le bucket cloud si obligatoire. Partager l’endpoint utilisable **depuis Docker**, le bucket, les préfixes et un test d’écriture/relecture. Séparer le rôle d’écriture du pipeline du compte frontend, limité à `gold/`.
- [ ] **0 h 30–1 h 15 :** lancer le worker Papermill avec tâches indépendantes pour que NOAA ne retarde pas CityBikes. Faire écrire les notebooks exécutés dans un répertoire de résultats distinct des sources. Démarrer Voilà dans le navigateur avec les filtres ville et période, puis préparer quatre vues avec des états « en attente de données ».
- [ ] **1 h 15–2 h 45 :** intégrer les tables Silver dans `04_traitement_kpis.ipynb` et figer les chemins Gold. Connecter d’abord **un KPI réel** de la première source disponible, idéalement la carte CityBikes. Vérifier qu’il est cohérent avec la table Gold et que les filtres fonctionnent. Laisser les propriétaires fournir leurs autres agrégats et les définitions des indicateurs.
- [ ] **2 h 45–4 h 00 :** brancher météo, pollution et croisement, ajouter unités, fraîcheur, période, nombre d’observations et messages de données insuffisantes. Si le cloud avec catalogue est retenu, vérifier une requête sur une table Silver et une table Gold. Préparer le README : démarrage, configuration, réexécution et provenance des KPI.
- [ ] **4 h 00–4 h 45 :** tester un redémarrage, l’accès depuis un autre poste ou navigateur et la démo sur la dernière période Gold conservée. Figer une période lisible pour l’enregistrement et vérifier qu’aucun écran ne dépend d’un appel API en direct pour afficher les résultats.

**À remettre :** URL de démonstration, commandes de lancement, dashboard branché sur Gold et checklist d’enregistrement. **Validation :** un membre qui n’a pas monté Compose peut lancer et ouvrir le frontend avec le README ; les filtres modifient les vues et un filtre sans données donne un message clair.

### Passages de relais et validations en binôme

| Échéance | Passage de relais | Critère concret |
| --- | --- | --- |
| **0 h 20** | **4 → 1, 2, 3** : configuration et conventions | Même endpoint/bucket, mêmes `city_id`, mêmes dates UTC. Aucun secret dans le dépôt. |
| **1 h 15** | **2 + 4** vérifient le worker ; **1 + 3** comparent la couverture | Deux relevés CityBikes espacés ; une station météo et un capteur de pollution géographiquement et temporellement compatibles, ou un écart identifié. |
| **2 h 30** | **1, 2, 3 → 4** : échantillons Silver et contrats Gold | Pour chaque table : chemin, colonnes, types, unité, clé de déduplication, période disponible et nombre de lignes. Un échantillon réel se lit avec la configuration commune. |
| **3 h 30** | **1 + 3** valident météo–pollution ; **2 + 4** valident le frontend mobilité | Comptage des heures communes, contrôle de l’absence de jointures plusieurs-à-plusieurs ; un KPI affiché correspond à la valeur calculée dans Gold. |
| **4 h 45** | **Tous** : répétition, puis enregistrement en binômes | **1 + 4** pilotent la vidéo 1 ; **2 + 3** pilotent la vidéo 2 avec l’aide de 4 pour le frontend. Chacun prépare une interprétation et une limite vérifiable de sa partie. |

Pour éviter les conflits sur les `.ipynb`, gardez **un seul éditeur par notebook**. Les autres transmettent une table, une définition de KPI ou un retour de vérification plutôt que d’éditer en parallèle `04_traitement_kpis.ipynb` et `05_dashboard.ipynb`.

## 4. Frontend de démonstration

Faites **un seul dashboard Voilà**, avec un filtre **ville**, un filtre **période** et quatre vues :

| Vue | Ce qu’on montre à l’écran |
| --- | --- |
| **Météo** | Températures par mois, jours extrêmes selon une règle documentée et graphique reliant la visibilité à la température ou à la pluie. |
| **Mobilité** | Carte des stations, nombre de vélos disponibles, part de relevés où chaque station est vide ou pleine et courbe horaire sur la période observée. |
| **Pollution** | Carte et série horaire par polluant, avec l’unité et le nombre de capteurs. Évitez de comparer directement les valeurs brutes de polluants différents pour dire lequel « domine ». |
| **Analyse croisée** | Graphique météo–pollution ou météo–disponibilité des vélos, avec le nombre d’heures communes. Si la période commune est trop courte, affichez le diagnostic de couverture plutôt qu’une corrélation peu défendable. |

Sur chaque vue, affichez la période couverte et la dernière mise à jour. Pour les vélos, nommez les indicateurs « disponibilité » ou « pression sur les stations » : CityBikes fournit des stocks observés, pas un comptage des trajets. Pour la démo, le frontend doit pouvoir s’ouvrir et montrer la dernière période collectée même si une API est indisponible à ce moment-là.

## 5. Planning des six heures

| Temps | Travail | Point de contrôle |
| --- | --- | --- |
| **0 h 00–0 h 30** | Valider local/cloud, démarrer Compose, tester la clé OpenAQ et fixer le contrat Bronze/Silver/Gold. Lancer CityBikes dès que le stockage répond. | Un objet écrit puis relu, un premier relevé vélos et une ville candidate. Si le cloud est obligatoire, vérifier l’accès maintenant. |
| **0 h 30–1 h 15** | Lancer le batch NOAA parallèle et la collecte OpenAQ. Monter la page Voilà pendant que les collecteurs tournent. | Deux relevés CityBikes espacés, un CSV météo et des mesures OpenAQ. Frontend accessible dans le navigateur. |
| **1 h 15–2 h 45** | Nettoyer les trois sources et écrire Silver. Produire un premier indicateur Gold et le connecter au frontend. | Premier parcours vérifié : **objet brut → Parquet → KPI → graphique visible**. |
| **2 h 45–4 h 00** | Compléter les KPI, la carte des stations, la série pollution et la vue croisée. | Le filtre ville fonctionne ; les périodes, unités et effectifs sont affichés. |
| **4 h 00–4 h 45** | Tester le redémarrage, la persistance et la relance sans doublons ; figer une période de démo. | Démo répétée de bout en bout. Résultats et limites notés dans `README.md`. |
| **4 h 45–6 h 00** | Enregistrer et vérifier les deux vidéos. | Les deux fichiers MP4 sont lisibles et suivent le parcours ci-dessous. |

### Parcours des vidéos

1. **`Démo-UrbanHub-Partie1.mp4`** : téléchargement NOAA en parallèle, Data Lake et vue météo.
2. **`Démo-UrbanHub-Partie2.mp4`** : collectes régulières, frontend interactif, mobilité, pollution et analyse croisée.

> **Si vous prenez du retard :** gardez une ville qui traverse réellement les trois couches, un KPI vérifiable par source, un écran de recouvrement pour le croisement et les deux vidéos. Si le batch France n’est pas terminé, montrez sa couverture réelle. Privilégiez les vues branchées sur des données dont vous pouvez expliquer la provenance et les limites.
