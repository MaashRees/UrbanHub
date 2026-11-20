# <img src="assets/icons/clipboard.svg" width="18" height="18" alt=""> Reste à faire, répartition et budget de stockage

État au 20/11/2026. Ce document liste ce qui manque, qui le fait, et ce qu'il faut relancer. Les messages prêts à envoyer sont en fin de document.

## <img src="assets/icons/hard-drive.svg" width="18" height="18" alt=""> Budget de stockage (quota R2 : 10 Go)

Volumes mesurés le 20/11/2026 (octets exacts), sauf mention « estimation ».

| Élément | Volume | Dans R2 aujourd'hui ? |
| :--- | ---: | :--- |
| État actuel du lac (Bronze 83 Mo, Silver 81 Mo, Gold 6 Mo) | **0,17 Go** | oui |
| Open-Meteo 2022-2026 (Bronze 14,5 Mo, Silver 1,4 Mo, table horaire 1,4 Mo) | 17 Mo | non |
| OpenAQ 2022-2026 : Bronze (21 053 fichiers) | 12 Mo | non |
| OpenAQ : Silver et Gold historiques (estimation) | 10 Mo | non |
| **Sous-total Open-Meteo et OpenAQ, toutes couches** | **environ 40 Mo** | non |
| Archive CityBikes 2022-2026, Bronze (61 fichiers) | 946 Mo | non |
| Archive CityBikes 2025 seul, Bronze (36 fichiers) | 640 Mo | non |
| Séries horaires par station tirées de l'archive CityBikes (estimation) | 150 à 300 Mo pour 2025 | non |
| Collecte CityBikes en direct, Bronze JSON brut | **294 Mo par jour** | oui, en continu |
| Collecte CityBikes en direct, Silver | 59 Mo par jour | oui, en continu |
| Collecte CityBikes en direct, Bronze compressé en gzip (mesuré : facteur 5,3) | environ 56 Mo par jour | à implémenter |

**Lecture :** les archives OpenAQ et Open-Meteo sont négligeables. Le vrai risque est la **collecte en direct** : environ 350 Mo par jour, donc 10 Go atteints en 4 semaines et 5 Go en 2 semaines.

| Scénario | Total R2 |
| :--- | ---: |
| Aujourd'hui | 0,17 Go |
| + archives OpenAQ et Open-Meteo | 0,21 Go |
| + archive CityBikes 2025 (Bronze et séries horaires, estimation) | environ 1,2 Go |
| + 14 jours de collecte en direct brute | environ 6,1 Go |
| + 14 jours de collecte en direct compressée | environ 2,0 Go |
| + 28 jours de collecte brute | environ 11 Go : **dépasse le quota** |

**Mesures pour rester sous 10 Go :**
1. Compresser le Bronze CityBikes en gzip (divise le volume par 5).
2. Arrêter la collecte en direct après les vidéos et la date de rendu, ou la limiter à 10 jours.
3. Pour l'archive CityBikes, ne garder dans R2 que ce qui sert : 2025 seul, et conserver le Bronze brut en local (il se retélécharge depuis la source publique).
4. Supprimer l'ancien NOAA (`silver/weather/` 78 Mo) et les préfixes `sample/` (12 Mo) quand tout est validé.

## <img src="assets/icons/rocket.svg" width="18" height="18" alt=""> À relancer (commandes)

| Quand | Commande | Pourquoi |
| :--- | :--- | :--- |
| Dès que le téléchargement OpenAQ est fini | `python scripts/archives_to_gold.py` | produit les séries horaires et les tables Gold historiques |
| Ensuite | exécuter `notebooks/07_analyses_historiques.ipynb` | analyses sur 5 ans |
| Après validation | `python scripts/openmeteo_archive.py --upload`, `python scripts/openaq_archive.py --silver --upload`, `python scripts/archives_to_gold.py --upload` | publie dans les buckets existants (jamais de nouveau bucket) |
| Après la fusion de la branche | `docker compose --profile collect up -d --build` | les collecteurs prennent le nouveau code |
| Quand CityBikes a été transformé | notebooks 04 et 06, puis 07 | analyses de mobilité sur l'historique |
| Après chaque nouvelle collecte | notebook 03 | reconstruit `city_hourly` |

## <img src="assets/icons/wrench.svg" width="18" height="18" alt=""> Code à créer, par personne

| Qui | Tâche | Taille |
| :--- | :--- | :--- |
| **Conambot** | Transformer l'archive CityBikes en séries horaires par ville (et par station pour 2025) au même format que le Silver en direct, après lecture du schéma réel (notebook 06) | moyenne |
| **Conambot** | Compresser en gzip le Bronze CityBikes dans `collect_once` (`write_bronze`) | petite, environ 10 lignes |
| **Conambot** | Étendre le notebook 04 avec l'historique (pics journaliers, stations critiques sur un an) | moyenne |
| **Julie** | Retenir plus de capteurs par polluant (`max_sensors_per_pollutant`) et valider l'archive OpenAQ contre l'API sur 2 ou 3 jours | petite |
| **Julie** | Rendre le Silver OpenAQ incrémental (il relit tout le Bronze à chaque exécution) | moyenne |
| **Julie** | Relire l'interprétation pollution du notebook 07 et rédiger les conclusions | petite |
| **Rémi** | Décider quoi publier de la météo avec visibilité (`weather_hourly_visibility`) et l'intégrer au Gold si accepté ; Lille n'a de visibilité que depuis le 26/06/2024 | petite |
| **Rémi** | Mettre à jour `RESULTATS_NOAA.md` en bilan Open-Meteo sur 5 ans | petite |
| **Seer** | Publier dans R2, nettoyer (`sample/`, ancien NOAA), créer l'utilisateur en lecture seule pour le dashboard | petite |
| **Seer** | Dashboard : onglet mobilité historique une fois les tables publiées | petite |
| **Seer** | README final, guide, coordination des vidéos | petite |

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> Décisions à prendre

1. Quelle machine fait tourner la collecte (une seule), et jusqu'à quelle date.
2. Télécharger l'archive CityBikes en entier (946 Mo) ou 2025 seul (640 Mo).
3. Publier dans R2 le Bronze de l'archive CityBikes, ou le garder en local.

## <img src="assets/icons/video.svg" width="18" height="18" alt=""> Vidéos

- **Partie 1** (météo) : prête à enregistrer avec Open-Meteo, 5 ans et visibilité.
- **Partie 2** (streaming, pollution, croisement) : à enregistrer après la publication des tables historiques, pour montrer le dashboard avec l'onglet Historique rempli.

## <img src="assets/icons/info.svg" width="18" height="18" alt=""> Messages à envoyer

**À tout le monde**

> Salut, point d'étape. Les archives sur 5 ans (2022 à 2026) sont écrites : météo avec visibilité, pollution OpenAQ, et le plan CityBikes. Stockage R2 : 0,17 Go sur 10, mais la collecte CityBikes en direct ajoute environ 350 Mo par jour, donc 10 Go en 4 semaines. On compresse le Bronze et on arrête la collecte après les vidéos. Voici la répartition pour après les vidéos, chacun sur sa branche, jamais sur `main`. Détail dans `docs/RESTE_A_FAIRE.md`.

**À Conambot**

> 1) Quand j'aurai téléchargé l'archive CityBikes, peux-tu la transformer en séries horaires par ville (et par station pour 2025) dans le même format que le Silver en direct ? Le notebook 06 affiche le schéma.
> 2) Peux-tu compresser en gzip le Bronze dans `write_bronze` ? Je mesure un facteur 5 : de 294 à 56 Mo par jour.
> 3) Étends le notebook 04 avec l'historique.
> 4) Qui lance la collecte, et jusqu'à quelle date ?

**À Julie**

> 1) Peux-tu retenir plus de capteurs par polluant et comparer l'archive OpenAQ à l'API sur 2 ou 3 jours ? J'ai trouvé que l'archive donne la fin de la période, donc un décalage de -1 h par rapport à notre Silver.
> 2) Rends le Silver incrémental (il relit tout le Bronze).
> 3) Relis l'interprétation pollution du notebook 07 et rédige les conclusions.

**À Rémi**

> 1) La visibilité : Paris et Lyon l'ont depuis 2022 avec l'API `historical-forecast`, Lille seulement depuis le 26/06/2024. Veux-tu publier cette table dans le Gold ?
> 2) Mets à jour le bilan météo (`RESULTATS_NOAA.md`) avec les 5 ans Open-Meteo.

**À Seer (moi)**

> Je publie dans R2 après vérification, je nettoie `sample/` et l'ancien NOAA, je crée l'utilisateur en lecture seule du dashboard, j'ajoute l'onglet mobilité historique, et je coordonne les vidéos.
