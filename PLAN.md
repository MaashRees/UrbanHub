# UrbanHub ROADMAP

**Les deux priorités :**

1. **Démarrer CityBikes dans les 30 premières minutes** pour accumuler des observations.
2. **Afficher un premier KPI réel dans le frontend avant la troisième heure** pour valider l’intégration tôt.

## 1. Architecture et choix du Data Lake

```text
NOAA (batch parallèle) ───────────┐
CityBikes (relevé toutes les 3 min) ├──► Bronze ──► Silver ──► Gold ──► Frontend Voilà
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
- **`worker`** : exécution automatique des notebooks avec Papermill. Prévoyez un lancement ponctuel pour tester chaque collecte et des tâches indépendantes pour que le batch NOAA ne bloque pas CityBikes. Pour la collecte à trois minutes, suivez les heures de passage et évitez que deux exécutions du même flux se chevauchent.
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
| **1 — Météo NOAA** | Identifier les stations françaises et lancer en parallèle les téléchargements station–année sur cinq ans. Décoder les champs météo, les unités et les valeurs manquantes. Garder la durée de mesure des précipitations. | Un petit échantillon utilisable rapidement, puis le bilan du téléchargement complet : réussites, absences et erreurs. Fournir la saisonnalité, les extrêmes et un graphique météo–visibilité. |
| **2 — Mobilité CityBikes** | Lancer la collecte toutes les 3 minutes, conserver les instantanés et calculer les indicateurs de disponibilité. | Deux instantanés horodatés pour valider le démarrage, puis disponibilité par heure et liste des stations vides, pleines ou souvent critiques. |
| **3 — Pollution OpenAQ et croisement** | Vérifier la clé API et la couverture, collecter les mesures des capteurs et normaliser les unités par polluant. Construire la jointure horaire avec les deux autres responsables de source. | Profils horaires et anomalies par polluant, bilan de couverture et première comparaison croisée sur les périodes communes. |
| **4 — Docker, intégration et frontend** | Monter Compose, définir les chemins communs, intégrer les transformations dans `04_traitement_kpis.ipynb` et construire le dashboard Voilà. | Une URL locale de démo, un premier KPI issu de Gold et un parcours de démonstration prêt avant l’enregistrement. |

La personne 4 intègre les traitements ; les trois autres restent responsables du nettoyage de leur source et de la définition de leurs KPI. Paris est la première ville candidate pour la démo. Ajoutez Lyon et Lille, ou d’autres villes mieux couvertes, dès que l’intersection des sources est confirmée. Le téléchargement météo vise la France sur cinq ans, indépendamment du nombre de villes affichées lors de la démo.

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
