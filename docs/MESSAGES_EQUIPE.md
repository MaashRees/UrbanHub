# <img src="assets/icons/list.svg" width="18" height="18" alt=""> Messages à envoyer à l'équipe

Messages prêts à copier, un par personne. Ils s'appuient sur l'état du dépôt au 19/11/2026 (PR #8, [AVANCEMENT.md](AVANCEMENT.md)).

## À tout le monde

> Salut, la PR #8 contient : dashboard branché sur Gold avec fraîcheur et rafraîchissement automatique, correctif de la pagination OpenAQ, environnement `uv sync` réparé, Gold CityBikes recalculé depuis R2, analyses croisées réelles (notebooks 03 et 04) et la configuration pour tourner en continu (`docs/DEPLOIEMENT_CONTINU.md`).
> Après la fusion, faites `git pull --rebase` puis `uv sync`.
> **Règle importante :** une seule machine collecte vers R2. CityBikes limite les appels par adresse : en cas de test, utilisez `--storage local`, jamais l'API en direct en boucle. Dites-moi qui lance la collecte.

## À Thekorzeremi (fusion de la PR)

> Peux-tu fusionner la PR #8 (https://github.com/Thekorzeremi/UrbanHub/pull/8) ? Elle est fusionnable sans conflit et rebasée sur `main`. Elle touche `scripts/citybikes_stream.py` (Conambot), `src/openaq_pipeline.py` (Julie) et le dashboard : un coup d'oeil de leur part avant la fusion serait bien.

## À Rémi (météo)

> 1. **Visibilité** : le Gold météo n'a de visibilité qu'à partir de fin 2025 (10 144 heures par ville). L'API `historical-forecast` la fournit depuis 2022 si on ne fixe pas le modèle `ecmwf_ifs`. Peux-tu tester et, si possible, compléter ?
> 2. **Actualisation** : j'ai ajouté un service `collector-weather` (toutes les heures, `openmeteo_batch.py --upload`). Peux-tu confirmer que relancer `--upload` toutes les heures est sans risque pour les tables partagées ?
> 3. **Colonnes** : `weather_station_count` n'est plus dans `weather_hourly`. Aucun code ne l'utilise, mais note-le dans `docs/MIGRATION_OPENMETEO.md`.
> 4. Les sorties du notebook 01 Open-Meteo sont enregistrées : relis les conclusions de `RESULTATS_NOAA.md` pour les mettre à jour avec Open-Meteo.

## À Julie (pollution et croisement)

> 1. **Pagination** : l'ingestion ne lisait que les 300 mesures les plus anciennes de la fenêtre, donc rien de récent. C'est corrigé (`fetch_all_measurements`), la pollution va jusqu'à l'heure de l'exécution.
> 2. **Capteurs** : on ne retient que 2 capteurs par polluant et par ville (28 sur 149). Peux-tu augmenter `max_sensors_per_pollutant` et vérifier l'effet sur les classements ?
> 3. **Copie mobilité** : `harmonize_mobility_kpis` ne rafraîchissait jamais `kpis/mobility_*`, et `city_hourly` lisait cette copie périmée. C'est corrigé, `citybikes/kpis/` est le chemin canonique.
> 4. **Analyse croisée** : la cellule 11 simulée est remplacée par une vraie analyse (vent contre NO2 : rho -0,65 sur 970 h ; particules plus basses avec la pluie). Relis l'interprétation avant la vidéo.
> 5. **Service** : `collector-openaq` relance le pipeline toutes les 2 h avec une fenêtre de 12 h (`OPENAQ_LOOKBACK_HOURS`). Attention : `clean_and_transform_to_silver` relit tout le Bronze à chaque exécution, il faudra le rendre incrémental si les objets s'accumulent.
> 6. Le diagnostic JSON garde une clé `meteo_noaa` : à renommer en `meteo`.

## À Conambot (CityBikes)

> 1. **Gold depuis R2** : en ligne, `collect_once` recalcule maintenant le Gold depuis le Silver publié dans R2 (deux dernières heures, fusionnées avec le Gold publié) et plus depuis ton Silver local, qui écrasait les tables partagées. Hors ligne (`--storage local`), tout reste local. J'ai reconstruit le Gold publié avec `--rebuild-gold` : il avait 3 heures sans Silver en ligne.
> 2. **Quota** : au premier `429`, le script met en pause tous les appels jusqu'à `Retry-After`. Ne lance plus de tests en boucle depuis la même adresse.
> 3. **Intervalle** : on reste à 5 minutes (300 s).
> 4. **Notebook 04** : `notebooks/04_analyses_mobilite.ipynb` répond aux 5 questions de la Partie 2 et au volet vélos de la Partie 4. Il affiche des `[ATTENTION]` tant que la collecte est courte. Relis les règles (grille de 1 km, seuil de 30 %, 10 relevés minimum).
> 5. **Stockage** : environ 1 Mo de Bronze par cycle, soit environ 290 Mo par jour. Qui lance la collecte, et jusqu'à quand ? (Quota R2 : 10 Go.)
