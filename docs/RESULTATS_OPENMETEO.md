# Rémi — Premier lot Open-Meteo : Paris, Lyon et Lille

Ce document conserve l’analyse du premier lot ECMWF IFS. Pour le livrable et les chiffres du notebook 07, voir le [bilan météo de référence 2022–2026](RESULTATS_NOAA.md).

## Source et couverture

Le premier lot utilise l’[API historique Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api), avec le modèle **ECMWF IFS** pour toute la période. Les données sont des estimations du modèle aux coordonnées des trois villes, pas des relevés de stations ni une moyenne de la France entière. Les résultats ci-dessous sont calculés sur les Parquets Gold de ce lot ; l’[ancien bilan NOAA](ARCHIVE_RESULTATS_NOAA.md) reste disponible séparément.

- **Période :** du 1er janvier 2020 à 00 h au 19 novembre 2026 à 13 h, en UTC.
- **Volume :** 181 050 heures-ville (60 350 par ville) et 7 545 jours-ville, sans doublons sur leurs clés. La dernière journée est partielle : 14 heures par ville.
- **Méthode :** saisonnalité, extrêmes et cumuls annuels calculés sur les six années civiles complètes **2020–2025**. Pour la visibilité, l’analyse utilise toutes les paires disponibles jusqu’au 19 novembre 2026.

## Résultats météo

### 1. Saisonnalité des températures

Janvier est le mois le plus froid et août le plus chaud en moyenne dans les trois villes sur 2020–2025. Lyon présente le contraste le plus marqué entre les deux mois : environ **19,1 °C d’écart**, contre **15,8 °C à Paris** et **15,0 °C à Lille**.

| Ville | Janvier, moyenne horaire | Août, moyenne horaire |
| --- | ---: | ---: |
| Lille | 4,2 °C | 19,2 °C |
| Lyon | 3,6 °C | 22,7 °C |
| Paris | 4,7 °C | 20,5 °C |

### 2. Périodes inhabituelles

Début septembre 2023, les maxima journaliers ont dépassé le **95ᵉ percentile automnal** pendant **10 jours consécutifs à Lyon** (3–12 septembre) et **8 jours à Paris** (3–10 septembre) comme **à Lille** (4–11 septembre). Du **5 au 13 juin 2024**, les minima journaliers sont restés sous le **5ᵉ percentile estival** à Paris et à Lille pendant neuf jours.

Les seuils sont calculés par ville et saison sur 2020–2025. Ils repèrent des épisodes inhabituels **dans ce lot** ; ils ne constituent ni une normale climatique ni un seuil d’alerte officiel.

### 3. Journées extrêmes

| Ville | Plus haut maximum horaire | Plus bas minimum horaire |
| --- | --- | --- |
| Lille | **38,1 °C**, le 19 juillet 2022 | **−7,6 °C**, le 9 février 2021 |
| Lyon | **40,3 °C**, le 24 août 2023 | **−7,0 °C**, le 14 février 2021 |
| Paris | **39,1 °C**, le 19 juillet 2022 | **−6,1 °C**, le 20 janvier 2024 |

Dates en UTC. Ces valeurs sont les extrêmes des températures horaires modélisées sur 2020–2025, pas des records instantanés mesurés en station.

### 4. Pluie et visibilité

Sur les années complètes du lot, **2024 est l’année la plus pluvieuse à Lyon (1 230,3 mm) et à Paris (1 129,3 mm)** ; **2023** arrive en tête **à Lille (995,7 mm)**. Ces cumuls portent sur la pluie liquide modélisée. Chaque valeur horaire est rattachée au début de l’intervalle qu’elle couvre : une pluie rapportée à 14 h par l’API est jointe à l’heure de 13 h UTC.

| Ville | Pluie–visibilité | Température–visibilité | Vent–visibilité | Paires par calcul |
| --- | ---: | ---: | ---: | ---: |
| Lille | −0,390 | +0,063 | −0,107 | 10 143 |
| Lyon | −0,343 | +0,281 | +0,168 | 10 143 |
| Paris | −0,407 | +0,129 | −0,084 | 10 143 |

Dans les trois villes, **les heures plus pluvieuses sont associées à une visibilité plus faible**. La température est positivement associée à la visibilité, surtout à Lyon ; le signe de l’association avec le vent varie selon la ville. Ces corrélations de Pearson sont descriptives et ne prouvent pas de causalité. La visibilité n’est renseignée que pour **30 429 heures-ville (16,8 % du lot)** : aucune valeur en 2020–2024, une couverture partielle en 2025 et une couverture complète sur les heures incluses de 2026. Les valeurs absentes n’ont pas été imputées.

## Livrables et passage de relais

| Données | Chemin R2 |
| --- | --- |
| Bronze : réponses API et manifeste | `s3://urbanhub-bronze/openmeteo/year=AAAA/city_id=VILLE/archive.json` et `s3://urbanhub-bronze/openmeteo/manifest.json` |
| Silver : Parquets annuels | `s3://urbanhub-silver/weather/openmeteo/year=AAAA/weather_hourly.parquet` |
| Gold : jointure horaire pour Julie | `s3://urbanhub-gold/kpis/weather_hourly.parquet` — clé `(city_id, hour_utc)` en UTC |
| Gold : dashboard pour Seer | `s3://urbanhub-gold/kpis/weather_daily.parquet` — clé `(city_id, day_utc)` en UTC |

Lors de la validation du lot du 19 novembre, **6 clés météo–CityBikes** et **923 clés météo–OpenAQ** se recouvraient. **Aucune clé n’était commune aux trois** : les créneaux des collectes vélo et pollution ne se recouvraient pas dans les tables vérifiées. Recalculer ces intersections avant de produire une analyse croisée.

Pour la démo, ouvrir le [notebook Open-Meteo](../notebooks/01_openmeteo_batch.ipynb), montrer la courbe mensuelle, commenter l’épisode chaud de septembre 2023, puis présenter le déficit de couverture de la visibilité. Le flux se rafraîchit avec `python scripts/openmeteo_batch.py --upload` ; le bilan ci-dessus reste daté du lot analysé.
