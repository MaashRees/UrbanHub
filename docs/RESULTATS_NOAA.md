# Rémi — Bilan météo Open-Meteo, 2022–2026

## Source et périmètre

Open-Meteo est la source météo de référence d’UrbanHub. Le changement a été validé avec l’enseignant : l’archive NOAA ISD s’arrête le **24 août 2025**, ce qui empêchait le croisement avec les collectes de 2026. De plus, le traitement NOAA ne retenait aucun cumul positif de pluie pour les trois villes. Le passage à Open-Meteo apporte des séries horaires plus récentes et des cumuls de précipitations exploitables. Le [dossier de migration](https://github.com/Thekorzeremi/UrbanHub/blob/0e93a5769af44b90dcce79655760d3803a9e574d/docs/MIGRATION_OPENMETEO.md) détaille cette décision ; le [bilan NOAA 2020–2024](ARCHIVE_RESULTATS_NOAA.md) est conservé comme archive.

Le [notebook 01](../notebooks/01_openmeteo_batch.ipynb) décrit le flux météo par ville : collecte Open-Meteo, horodatage UTC, agrégations horaires et journalières. Les chiffres ci-dessous reprennent les sorties du **volet météo (sections 1 à 4) du [notebook 07](https://github.com/Thekorzeremi/UrbanHub/blob/0e93a5769af44b90dcce79655760d3803a9e574d/notebooks/07_analyses_historiques.ipynb)**, qui exploite les archives historiques enrichies en visibilité. Celles-ci couvrent **5 352 jours-ville** à Paris, Lyon et Lille, du **1er janvier 2022 au 19 novembre 2026**. La fenêtre couvre cinq années civiles, dont **2026 est incomplète**. Les valeurs sont des estimations de modèle aux coordonnées des trois villes, pas des relevés de station ni une moyenne de la France entière.

## 1. Périodes météorologiques anormales

Le notebook recense **63 épisodes d’au moins trois jours consécutifs**, comptés par ville. Un jour est considéré comme inhabituellement chaud si son maximum dépasse le 95ᵉ percentile de sa ville et de sa saison, ou inhabituellement froid si son minimum passe sous le 5ᵉ percentile. Les seuils sont calculés sur la période étudiée : ils repèrent des écarts par rapport au lot et ne sont pas des seuils d’alerte officiels.

- **Septembre 2023 :** chaleur inhabituelle pendant **10 jours à Lyon** (3–12 septembre), **9 à Lille** (3–11) et **8 à Paris** (3–10).
- **Mai 2026 :** un autre épisode chaud touche les trois villes, avec **10 jours à Lyon** (22–31 mai) et **9 jours à Paris et Lille** (22–30 mai). Les seuils saisonniers permettent de repérer cette chaleur inhabituelle dès le printemps.
- **Juin 2024 :** à Paris et Lille, les minima restent sous le seuil saisonnier pendant **9 jours** (5–13 juin), avec des minima d’épisode de **6,0 °C** et **6,4 °C** respectivement. Il s’agit de nuits fraîches pour la saison, pas des minima absolus du lot.

## 2. Évolution saisonnière de la température

La courbe mensuelle du notebook montre le même cycle dans les trois villes : les températures montent du printemps à l’été, puis redescendent vers l’hiver. L’analyse mensuelle et les moyennes annuelles utilisent les **quatre années complètes 2022–2025** pour éviter de comparer 2026, à laquelle il manque la fin de l’année, à un millésime entier.

| Année | Lille | Lyon | Paris |
| --- | ---: | ---: | ---: |
| 2022 | 12,02 °C | 13,74 °C | 12,89 °C |
| 2023 | 12,03 °C | 13,52 °C | 12,96 °C |
| 2024 | 11,80 °C | 12,66 °C | 12,30 °C |
| 2025 | 11,89 °C | 13,20 °C | 12,87 °C |

Lyon est la plus chaude en moyenne annuelle et Lille la plus fraîche sur chacune des quatre années. **2024 est la plus fraîche des quatre dans les trois villes**, suivie d’un rebond en 2025. Cette courte série décrit la variabilité d’une année à l’autre ; elle ne permet pas de conclure à une tendance climatique.

## 3. Jours présentant des conditions extrêmes

| Ville | Température maximale | Température minimale | Vent horaire maximal | Plus fort cumul journalier de pluie |
| --- | --- | --- | --- | --- |
| Lille | 38,1 °C — 19/07/2022 | −5,9 °C — 10/01/2024 | 19,4 m/s — 18/02/2022 | 37,6 mm — 20/06/2023 |
| Lyon | 40,3 °C — 24/08/2023 | −7,3 °C — 01/01/2026 | 14,8 m/s — 09/10/2024 | 74,8 mm — 07/09/2024 |
| Paris | 40,3 °C — 24/06/2026 | −6,3 °C — 06/01/2026 | 13,1 m/s — 21/02/2022 et 02/11/2023 | 54,8 mm — 09/10/2024 |

Les deux plus fortes températures du lot sont donc identiques à Lyon et Paris, mais surviennent lors d’épisodes distincts. Lille présente le vent horaire le plus fort des trois villes, tandis que Lyon présente le cumul journalier de pluie le plus élevé. Les dates sont en UTC ; ces chiffres sont des extrêmes du modèle à la résolution du lot, pas des records mesurés en station.

## 4. Météo et visibilité

Le notebook calcule le **coefficient de Spearman** sur les paires horaires disponibles. La visibilité est modélisée et sa couverture varie selon la ville : Paris et Lyon disposent de données dès janvier 2022, Lille seulement à partir du **26 juin 2024**. Les heures manquantes ne sont pas remplacées.

| Ville | Pluie | Température | Vent | Pression | Heures disponibles | Première heure disponible (date UTC) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Lille | −0,16 | +0,18 | −0,01 | +0,11 | 21 048 | 26/06/2024 |
| Lyon | −0,18 | +0,34 | +0,09 | −0,01 | 42 816 | 01/01/2022 |
| Paris | −0,19 | +0,33 | −0,08 | +0,08 | 42 816 | 01/01/2022 |

La pluie est associée à une visibilité plus faible dans les trois villes, mais la relation est **faible**. La température est positivement associée à la visibilité, surtout à Lyon et Paris ; les associations avec le vent et la pression sont faibles ou proches de zéro. Ces corrélations ne montrent pas de causalité, et les coefficients de Lille ne se comparent pas directement à ceux des deux autres villes sur une fenêtre identique.

**À retenir pour la démo :** montrer le cycle saisonnier, puis l’épisode chaud de septembre 2023 et la couverture inégale de la visibilité. Pour reproduire les chiffres de ce bilan, utiliser le notebook 07 : le notebook 01 reste la référence pour le flux et ses livrables Gold (`kpis/weather_hourly.parquet` et `kpis/weather_daily.parquet`). Source des données météo : **Open-Meteo.com (CC BY 4.0)**.
