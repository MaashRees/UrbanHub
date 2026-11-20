# <img src="assets/icons/wind.svg" width="18" height="18" alt=""> Conclusions : pollution et croisement avec la météo (2022-2026)

Brouillon rédigé à partir des résultats du notebook `07_analyses_historiques.ipynb` (sections 5 à 8), à relire et à ajuster par la personne en charge de la pollution. Les chiffres viennent des tables `kpis/history/` publiées dans le Data Lake : pollution OpenAQ validée contre l'API (voir plus bas), météo Open-Meteo.

## Questions de la Partie 3

**Quelles zones présentent les niveaux de pollution les plus élevés ?**
Les concentrations sont calculées par ville, sur les stations retenues (5 par ville au maximum). Elles ne décrivent donc pas toute l'agglomération, mais les emplacements choisis. À l'échelle des villes, Paris se distingue par le NO2 (polluant lié au trafic), Lille et Lyon par les particules fines PM2,5.

**Existe-t-il une variation journalière ?**
Oui. Le profil horaire moyen (notebook 07, section 6, heure locale) montre un cycle quotidien marqué. L'ozone suit l'ensoleillement, avec un maximum l'après-midi, alors que le NO2 et les particules suivent plutôt les heures de circulation. À vérifier sur le graphique avant de citer des heures précises.

**Quels polluants dominent ?**
On compare chaque polluant à sa ligne directrice OMS (ratio concentration moyenne sur seuil), car comparer des microgrammes de gaz et de particules n'aurait pas de sens. Le polluant le plus proche du seuil, ou au-dessus, est le **PM2,5 à Lille et à Lyon** et le **NO2 à Paris**.

Part des jours au-dessus de la ligne directrice OMS sur 24 h, toutes villes (la ligne 2021 est à ignorer : une seule heure du 31/12/2021 due au décalage horaire) :

| Année | NO2 | PM2,5 | PM10 | O3 |
| :--- | ---: | ---: | ---: | ---: |
| 2022 | 43,3 % | 33,0 % | 4,4 % | 0,0 % |
| 2023 | 31,4 % | 16,4 % | 2,6 % | 1,6 % |
| 2024 | 27,1 % | 15,2 % | 0,7 % | 0,3 % |
| 2025 | 27,6 % | 18,6 % | 2,4 % | 0,6 % |
| 2026 (partielle) | 25,5 % | 15,2 % | 1,8 % | 4,1 % |

Le NO2 dépasse la ligne directrice entre 25 % et 43 % des jours selon l'année : c'est le problème le plus persistant. Il baisse nettement entre 2022 et 2024, puis se stabilise. Les PM2,5 suivent la même tendance, avec un recul fort en 2023. Les PM10 dépassent rarement le seuil. L'ozone n'est pas un problème quotidien mais il progresse en 2026, année chaude.

**Peut-on identifier des épisodes de pollution anormale ?**
Oui : 200 épisodes d'au moins 2 jours consécutifs au-dessus du 95e percentile de la ville et du polluant. Les plus longs :
- **Épisodes d'ozone en été**, par exemple Paris du 08/07/2026 (11 jours, pic à 122 µg/m³), Paris en juin 2026, Lyon en juin 2026 et Lille en juin 2023. Ils coïncident avec les périodes chaudes.
- **Épisodes de NO2 et de PM2,5 en hiver**, par exemple Paris et Lyon à partir du 06-09/02/2023 (jusqu'à 11 jours) et Lyon en janvier 2024. Ce sont les situations où l'air stagne : c'est une explication plausible, à confirmer avec le vent et la pression de ces dates.

## Croisement avec la météo (Partie 4, question 1)

Corrélations de rang de Spearman sur 94 911 heures où pollution et météo sont toutes deux disponibles :

| Polluant | Vent | Température | Pluie | Pression |
| :--- | ---: | ---: | ---: | ---: |
| NO2 | -0,36 | -0,31 | -0,08 | 0,17 |
| PM2,5 | -0,33 | -0,26 | -0,19 | 0,33 |
| PM10 | -0,28 | -0,03 | -0,24 | 0,31 |
| O3 | 0,35 | 0,60 | 0,02 | -0,20 |

- **Le vent disperse la pollution de proximité.** Plus le vent est fort, plus le NO2 et les particules baissent (rho de -0,36 et -0,33).
- **La pluie nettoie les particules.** Médiane PM10 de 10,3 µg/m³ quand il pleut contre 15,7 sans pluie, PM2,5 de 5,9 contre 8,5. L'écart est statistiquement très net (test de Mann-Whitney, p très petit), vu le nombre d'heures (environ 14 500 avec pluie et 77 500 sans).
- **L'ozone suit la chaleur et le soleil** : corrélation de 0,60 avec la température, positive aussi avec le vent. C'est l'inverse des autres polluants.
- **Pression élevée, plus de pollution.** Les hautes pressions (temps stable) vont avec davantage de NO2 et de particules : cela rejoint l'idée de stagnation de l'air.

## Précautions de lecture

- **Corrélation, pas causalité.** Ces coefficients mesurent des associations. Le vent, la pluie et la température sont aussi liés entre eux et à la saison.
- **Couverture des mesures :** environ 71 à 73 % des heures pour le NO2 et les particules, 10 % pour le CO. Les statistiques ne portent que sur les heures mesurées.
- **Stations retenues, pas toute la ville.** Quelques capteurs par ville, donc un ordre de grandeur et non une carte de l'exposition.
- **Seuil de l'ozone.** La ligne directrice de l'OMS pour l'ozone porte sur la moyenne maximale sur 8 heures. La comparer à une moyenne journalière sous-estime les dépassements.
- **Météo modélisée** (Open-Meteo, aux coordonnées de la ville), pas mesurée sur le site des capteurs.
- **Deux semaines contre cinq ans.** Le notebook 03 (deux semaines de données en direct) donnait un lien vent-NO2 de -0,65 : ce chiffre n'est pas représentatif. Les valeurs de ce document, sur 5 ans, sont celles à citer.

## Validation de l'archive OpenAQ

Le notebook 03 compare l'archive publique d'OpenAQ à l'API sur 17 capteurs et 608 heures communes : erreur moyenne et biais nuls pour les cinq polluants, une fois l'archive décalée d'une heure (la date de l'archive marque la fin de la période horaire, celle de l'API le début). Les tables historiques du Data Lake sont donc cohérentes avec la source en direct.
