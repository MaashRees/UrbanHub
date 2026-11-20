# <img src="assets/icons/clipboard.svg" width="18" height="18" alt=""> Reste à faire, répartition et budget de stockage

État au 20/11/2026. Ce document liste ce qui manque, qui le fait, et ce qu'il faut relancer. Les messages prêts à envoyer sont en fin de document.

## <img src="assets/icons/hard-drive.svg" width="18" height="18" alt=""> Budget de stockage (quota R2 : 10 Go)

Volumes mesurés le 20/11/2026 (octets exacts), sauf mention « estimation ».

| Élément | Volume | Dans R2 aujourd'hui ? |
| :--- | ---: | :--- |
| État du lac après publication des archives (Bronze 115 Mo, Silver 87 Mo, Gold 13 Mo) | **0,215 Go** | oui |
| Open-Meteo 2022-2026 (Bronze 14,5 Mo, Silver 1,4 Mo, table horaire 1,4 Mo) | 17 Mo | oui, publié |
| OpenAQ 2022-2026 : Bronze (21 053 fichiers) | 12 Mo | oui, publié |
| OpenAQ : Silver (4,1 Mo) et Gold historiques (tables `kpis/history/` et `pollution_monthly`) | environ 10 Mo | oui, publié |
| **Sous-total Open-Meteo et OpenAQ, toutes couches** | **environ 40 Mo** | oui, publié |
| Archive CityBikes 2022-2026, Bronze (61 fichiers) | 946 Mo | non |
| Archive CityBikes 2025 seul, Bronze (36 fichiers) | 640 Mo | non |
| Séries horaires par station tirées de l'archive CityBikes (estimation) | 150 à 300 Mo pour 2025 | non |
| Collecte CityBikes en direct, Bronze JSON brut | **294 Mo par jour** | oui, en continu |
| Collecte CityBikes en direct, Silver | 59 Mo par jour | oui, en continu |

**Lecture :** les archives OpenAQ et Open-Meteo sont négligeables. Le vrai risque est la **collecte en direct** : environ 350 Mo par jour, donc 10 Go atteints en 4 semaines et 5 Go en 2 semaines.

| Scénario | Total R2 |
| :--- | ---: |
| Avant les archives | 0,17 Go |
| + archives OpenAQ et Open-Meteo (déjà publiées) | 0,215 Go |
| + archive CityBikes 2025 (Bronze et séries horaires, estimation) | environ 1,2 Go |
| + 14 jours de collecte en direct brute | environ 6,1 Go |
| + 28 jours de collecte brute | environ 11 Go : **dépasse le quota** |

**Mesures pour rester sous 10 Go :**
1. **Arrêter la collecte en direct après les vidéos** (décidé). Les données déjà collectées restent dans R2.
2. Pour l'archive CityBikes, ne garder dans R2 que ce qui sert : 2025 seul, et conserver le Bronze brut en local (il se retélécharge depuis la source publique).
3. Supprimer l'ancien NOAA (`silver/weather/` 78 Mo) et les préfixes `sample/` (12 Mo) quand tout est validé.

## <img src="assets/icons/rocket.svg" width="18" height="18" alt=""> À relancer (commandes)

| Quand | Commande | Pourquoi |
| :--- | :--- | :--- |
| Dès que le téléchargement OpenAQ est fini | `python scripts/archives_to_gold.py` | produit les séries horaires et les tables Gold historiques |
| Ensuite | exécuter `notebooks/07_analyses_historiques.ipynb` | analyses sur 5 ans |
| Déjà fait le 20/11/2026 | `openmeteo_archive.py --upload`, `openaq_archive.py --silver --upload`, `archives_to_gold.py --upload` | publié et vérifié dans R2 (buckets existants, aucun créé). Ne pas relancer |
| Après la fusion de la branche | `docker compose --profile collect up -d --build` | les collecteurs prennent le nouveau code |
| Quand CityBikes a été transformé | notebooks 04 et 06, puis 07 | analyses de mobilité sur l'historique |
| Après chaque nouvelle collecte | notebook 03 | reconstruit `city_hourly` |

## <img src="assets/icons/wrench.svg" width="18" height="18" alt=""> Code à créer, par personne

| Qui | Tâche | Taille |
| :--- | :--- | :--- |
| **Conambot** | Transformer l'archive CityBikes en séries horaires par ville (et par station pour 2025) au même format que le Silver en direct, après lecture du schéma réel (notebook 06) | moyenne |
| **Conambot** | Étendre le notebook 04 avec l'historique (pics journaliers, stations critiques sur un an) | moyenne |
| **Julie** | Retenir plus de capteurs par polluant (`max_sensors_per_pollutant`) et valider l'archive OpenAQ contre l'API sur 2 ou 3 jours | petite |
| **Julie** | Rendre le Silver OpenAQ incrémental (il relit tout le Bronze à chaque exécution) | moyenne |
| **Julie** | Relire l'interprétation pollution du notebook 07 et rédiger les conclusions | petite |
| **Rémi** | Décider quoi publier de la météo avec visibilité (`weather_hourly_visibility`) et l'intégrer au Gold si accepté ; Lille n'a de visibilité que depuis le 26/06/2024 | petite |
| **Rémi** | Mettre à jour `RESULTATS_NOAA.md` en bilan Open-Meteo sur 5 ans | petite |
| **Seer** | Nettoyer R2 (`sample/`, ancien NOAA), créer l'utilisateur en lecture seule pour le dashboard | petite |
| **Seer** | Dashboard : onglet mobilité historique une fois les tables publiées | petite |
| **Seer** | README final, guide, coordination des vidéos | petite |

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> Décisions à prendre

1. **Décidé : la collecte en direct est coupée après l'enregistrement des vidéos** (`docker compose --profile collect stop`). Reste à fixer la machine, une seule, qui la fait tourner d'ici là, et à désactiver la mise en veille du PC.
2. Télécharger l'archive CityBikes en entier (946 Mo) ou 2025 seul (640 Mo).
3. Publier dans R2 le Bronze de l'archive CityBikes, ou le garder en local.

## <img src="assets/icons/video.svg" width="18" height="18" alt=""> Vidéos

- **Partie 1** (météo) : prête à enregistrer avec Open-Meteo, 5 ans et visibilité.
- **Partie 2** (streaming, pollution, croisement) : à enregistrer après la publication des tables historiques, pour montrer le dashboard avec l'onglet Historique rempli.

## <img src="assets/icons/info.svg" width="18" height="18" alt=""> Messages à envoyer

**À tout le monde**

> Salut, point d'étape. Les archives sur 5 ans (2022 à 2026) sont écrites : météo avec visibilité, pollution OpenAQ, et le plan CityBikes. Les tables historiques sont déjà dans R2 : ne retéléchargez pas les archives, faites `git pull --rebase` puis `uv sync`. Stockage R2 : 0,215 Go sur 10 ; la collecte CityBikes en direct ajoute environ 350 Mo par jour, on l'arrête après les vidéos. Voici la répartition pour après les vidéos, chacun sur sa branche, jamais sur `main`. Détail dans `docs/RESTE_A_FAIRE.md`.

**À Conambot**

> 1) Peux-tu transformer l'archive CityBikes en séries horaires par ville (et par station pour 2025) dans le même format que le Silver en direct ? Pour lire le schéma sans tout télécharger : `python scripts/citybikes_archive.py --years 2025 --networks vlille` (40 Mo, un seul réseau). Une seule personne télécharge l'archive complète.
> 2) Étends le notebook 04 avec l'historique.
> 3) La collecte en direct sera coupée après les vidéos. Qui la fait tourner d'ici là ? Une seule machine, sans mise en veille.

**À Julie**

> 1) Peux-tu retenir plus de capteurs par polluant et comparer l'archive OpenAQ à l'API sur 2 ou 3 jours ? J'ai trouvé que l'archive donne la fin de la période, donc un décalage de -1 h par rapport à notre Silver.
> 2) Rends le Silver incrémental (il relit tout le Bronze).
> 3) Relis l'interprétation pollution du notebook 07 et rédige les conclusions.

**À Rémi**

> 1) La visibilité : Paris et Lyon l'ont depuis 2022 avec l'API `historical-forecast`, Lille seulement depuis le 26/06/2024. Veux-tu publier cette table dans le Gold ?
> 2) Mets à jour le bilan météo (`RESULTATS_NOAA.md`) avec les 5 ans Open-Meteo.

**À Seer (moi)**

> Je publie dans R2 après vérification, je nettoie `sample/` et l'ancien NOAA, je crée l'utilisateur en lecture seule du dashboard, j'ajoute l'onglet mobilité historique, et je coordonne les vidéos.
