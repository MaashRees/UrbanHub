# Archive — Bilan météo NOAA ISD, France 2020–2024

Ce document conserve le bilan du premier lot NOAA. Les chemins et volumes R2 ci-dessous décrivent l’état au moment de sa publication ; le relevé après migration indique que le Bronze NOAA a depuis été retiré de R2. Pour les résultats météo de référence du projet, voir le [bilan Open-Meteo 2022–2026](RESULTATS_NOAA.md).

## Couverture et qualité

**1 029 fichiers sur 1 048 candidats (98,2 %)**, pour **211 stations distinctes** et **12 483 296 observations Silver** après nettoyage. Les 19 fichiers station–année absents étaient en HTTP 404 ; aucune erreur de transfert n’est restée dans le manifeste. Les heures sans observation ne sont pas interpolées.

| Année | CSV récupérés | CSV absents | Lignes Silver |
| --- | ---: | ---: | ---: |
| 2020 | 205 | 6 | 2 576 318 |
| 2021 | 206 | 5 | 2 447 380 |
| 2022 | 204 | 5 | 2 565 529 |
| 2023 | 206 | 3 | 2 552 330 |
| 2024 | 208 | 0 | 2 341 739 |

Les cinq fichiers Silver ont été relus sans doublon sur `(station_id, timestamp_utc)`. Gold couvre Paris-Orly, Lyon–Saint-Exupéry et Lille–Lesquin : **129 809 heures-ville** et **5 450 jours-ville**, sans doublons sur `(city_id, hour_utc)` ni sur `(city_id, day_utc)`. Ces stations d’aéroport servent de référence aux villes ; elles ne mesurent pas directement le centre urbain.

## Réponses aux quatre questions météo

1. **Saisonnalité.** À l’échelle du réseau français, la moyenne des températures mensuelles de janvier est de **5,7 °C**, contre **21,3 °C en août** sur 2020–2024. Le calcul donne le même poids à chaque station disponible dans un mois (162 à 186 stations selon le mois), puis à chacun des cinq mois de janvier ou d’août. Ce n’est pas une moyenne pondérée par la surface du territoire. En août, les moyennes des heures disponibles atteignent **19,8 °C à Lille, 20,9 °C à Paris et 23,1 °C à Lyon**.
2. **Périodes inhabituelles.** Début septembre 2023, les maxima horaires journaliers ont dépassé le 95e percentile automnal **10 jours de suite à Lyon** (3–12 septembre), **9 à Paris** (2–10) et **8 à Lille** (4–11). À l’inverse, Paris présente **8 jours consécutifs** sous le 5e percentile estival des minima (6–13 juin 2024). Les seuils sont calculés par ville et saison, avec au moins 30 jours de référence et au moins 18 heures de température par jour retenu. Ils décrivent 2020–2024 et ne constituent pas une normale climatique.
3. **Jours extrêmes.** Parmi les jours ayant au moins 18 heures de température, le maximum de la moyenne horaire atteint **39,9 °C à Paris le 19 juillet 2022**, **38,95 °C à Lille le même jour** et **39,0 °C à Lyon le 24 août 2023**. Les minima horaires les plus bas sont **−7,75 °C à Lille le 19 janvier 2024**, **−6,10 °C à Paris le 18 décembre 2022** et **−5,20 °C à Lyon le 14 janvier 2022**. Ce sont des extrêmes de moyennes horaires, pas des records instantanés.
4. **Visibilité.** Sur les paires horaires mesurées, la température est positivement associée à la visibilité : Pearson **0,21 à Lille**, **0,38 à Paris** et **0,48 à Lyon** (environ 43 000 paires par ville). L’association avec la vitesse du vent est plus faible (**0,05 à 0,20**). Ces chiffres ne démontrent pas de causalité. **Aucune corrélation pluie–visibilité n’est calculable** : les cumuls horaires retenus pour les trois villes sont renseignés dans 78 445 lignes (60,4 %), mais tous valent zéro. Un contrôle des CSV d’Orly 2024 montre des valeurs positives portant le code de condition `3` (« début de période d’accumulation » selon la spécification ISD), écartées par le filtre. Le zéro du Gold ne permet donc pas de conclure à une absence de pluie. Julie et Seer doivent écarter cet indicateur de leurs analyses et graphiques.

## Passage de relais à Julie et Seer

| Objet | Chemin R2 | Utilisation |
| --- | --- | --- |
| Bronze | `s3://urbanhub-bronze/noaa/year=AAAA/station_id=….csv` (`AAAA` de 2020 à 2024) | 1 029 CSV sources, sans préfixe `sample/`. La colonne `STATION` contient l’identifiant de station. |
| Manifeste | `s3://urbanhub-bronze/noaa/manifest.json` | Suivi des 1 048 couples station–année et des 404. Dans `path`, le premier composant `bronze/` désigne la couche ; la clé R2 commence à `noaa/`. |
| Silver | `s3://urbanhub-silver/weather/year=AAAA/weather_france.parquet` (`AAAA` de 2020 à 2024) | Observations nettoyées de la France, clé `(station_id, timestamp_utc)`. |
| Gold horaire archivé | `s3://urbanhub-gold/kpis/noaa/weather_hourly.parquet` | Clé `(city_id, hour_utc)`, en UTC. Les chemins Gold officiels utilisent désormais Open-Meteo. |
| Gold journalier archivé | `s3://urbanhub-gold/kpis/noaa/weather_daily.parquet` | Séries historiques par `(city_id, day_utc)` en UTC. |

Le manifeste et les sept Parquets ont été relus sur R2 et leurs empreintes SHA‑256 comparées aux fichiers locaux. Les **1 029 CSV bruts (6,04 Go)** ont été publiés sur R2 avec contrôle MD5 ; l’inventaire distant confirme la présence, la taille et l’empreinte des 1 029 objets. Une copie reste dans `data/noaa-france-2020-2024/bronze/noaa/`.

### Stockage et rétention

Après publication, les trois buckets UrbanHub totalisent **6,15 Go**, soit environ **3,85 Go de marge** sur 10 Go selon leur inventaire. Si le groupe doit libérer de l’espace, archiver localement les CSV puis retirer du cloud une partition annuelle Bronze complète, par exemple `noaa/year=2020/` (**1,24 Go**), après accord avec Seer. Garder les Parquets Silver et Gold pour préserver la couverture historique du dashboard, et indiquer dans le bilan quelles années brutes restent disponibles sur R2. Pour scanner toutes les années officielles avec DuckDB, utiliser le motif `noaa/year=*/station_id=*.csv` : `year` est la partition Hive, `station_id=….csv` est le nom de fichier.

La température est en °C, le vent en m/s, la pression au niveau de la mer en hPa, la visibilité en m et les durées de pluie Silver en heures. Les `city_id` sont `lille`, `lyon`, `paris`. L’archive historique ne recouvre pas les collectes récentes : en l’absence d’heures communes, signaler cette limite et présenter les flux séparément.

## Démo de Rémi

1. Montrer le script parallèle et le manifeste : **1 029 réussites, 19 absences**. Expliquer la reprise depuis le cache, sans relancer un téléchargement de plusieurs gigaoctets pendant la vidéo.
2. Ouvrir [le notebook](../notebooks/01_noaa_batch.ipynb) en mode `france` avec `REBUILD = False`. La [copie exécutée](../data/noaa-france-2020-2024/01_noaa_batch.executed.ipynb) contient déjà les graphiques et tableaux sur la machine qui a lancé le lot.
3. Montrer les fichiers Silver et Gold sur R2, puis commenter le graphique saisonnier et l’épisode commun de septembre 2023. Conclure sur la portée des mesures d’aéroport et sur la limite de la pluie.
