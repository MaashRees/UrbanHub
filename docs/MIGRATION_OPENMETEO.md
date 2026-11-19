# <img src="assets/icons/thermometer.svg" width="18" height="18" alt=""> Changement de direction : météo NOAA vers Open-Meteo

| | |
| :--- | :--- |
| **Décision** | 19 novembre 2026 |
| **Responsable de la mise en oeuvre** | Rémi (Membre 1, flux météo) |
| **Statut** | <img src="assets/icons/dot-green.svg" width="18" height="18" alt=""> Livré par Rémi (PR #9) : [script](../scripts/openmeteo_batch.py), [notebook](../notebooks/01_openmeteo_batch.ipynb) et Gold basculé le 19/11/2026. Reste : planifier le rafraîchissement, la visibilité avant 2025, la validation par l'enseignant et la reconstruction de `city_hourly`. |
| **Déjà fait** | Vérification des API et simulation de raccord (section 6), puis mise en oeuvre par Rémi. Le prototype de simulation n'est pas dans le dépôt. |

Ce document sert de cahier des charges pour Rémi et de mémoire de la décision. Il remplace la partie « source » de la Partie 1 de [ENONCE.md](ENONCE.md) ; le reste de l'énoncé est inchangé.

---

## <img src="assets/icons/info.svg" width="18" height="18" alt=""> 1. Pourquoi changer

| Constat | Preuve |
| :--- | :--- |
| L'archive NOAA ISD est arrêtée depuis le **24 août 2025** | [RESULTATS_NOAA.md](RESULTATS_NOAA.md), `LAST_ISD_YEAR = 2025` dans `scripts/noaa_batch.py` |
| Aucun recouvrement possible avec les flux de 2026 | Pollution : 5 → 19 novembre 2026. Vélos : 19 novembre 2026. Météo NOAA : jusqu'en 2024. |
| La précipitation NOAA est inutilisable | Dans `kpis/weather_hourly.parquet`, **0 heure de pluie sur 129 809** (max 0,0 mm). Les questions « météo et vélos » et « météo et pollution par la pluie » ne peuvent pas être traitées. |
| Besoin de données **toujours fraîches** | Exigence de l'équipe : le tableau de bord doit refléter la météo de l'heure courante. |

<img src="assets/icons/alert.svg" width="18" height="18" alt=""> **Écart avec l'énoncé.** La Partie 1 nomme NOAA et demande de télécharger en parallèle des fichiers de stations françaises. À faire valider par l'enseignant avant la remise. Arguments : archive arrêtée, croisement impossible avec NOAA, précipitation absente. Garder le lot NOAA 2020-2024 déjà publié comme preuve de réalisation (voir section 7).

---

## <img src="assets/icons/search.svg" width="18" height="18" alt=""> 2. Ce qui a été vérifié sur Open-Meteo

Tests réels du 19 novembre 2026, Paris, 6 variables, 5 ans.

| API | Rôle | Constat |
| :--- | :--- | :--- |
| `archive-api.open-meteo.com/v1/archive` (ERA5) | Historique de référence | 43 728 heures sur 5 ans, **sans valeur manquante** pour température, vent, direction, pression, précipitation. **Visibilité : 0 valeur sur 43 728** (non fournie). Décalage d'environ 5 à 6 jours. |
| `historical-forecast-api.open-meteo.com/v1/forecast` | Visibilité et derniers jours | Visibilité disponible du **1er janvier 2022** jusqu'à hier (42 792 heures, de 40 m à 83 km). |
| `api.open-meteo.com/v1/forecast` avec `past_days` | **Fraîcheur** | Renvoie l'heure courante : à 14:00 UTC, la dernière heure passée est 14:00 UTC, **0 valeur manquante**, visibilité incluse. |

Conséquence : une seule API ne suffit pas. Il faut combiner l'archive (valeurs prioritaires), l'API historical-forecast (visibilité) et l'API forecast (données du jour).

Conditions d'usage : gratuit, usage non commercial, attribution obligatoire (licence CC BY 4.0, [open-meteo.com](https://open-meteo.com)). Les quotas gratuits sont publiés sur le site ; les relire avant le lot complet. Le test de 33 requêtes (3 villes, 5 ans) a pris 82 secondes sans refus.

---

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> 3. Correspondance des variables de l'énoncé

| Variable de l'énoncé | Paramètre Open-Meteo | Unité | Remarque |
| :--- | :--- | :--- | :--- |
| `timestamp` | `time` avec `timezone=UTC` | UTC | Heure pile. |
| `temperature` | `temperature_2m` | °C | |
| `wind_speed` | `wind_speed_10m` avec `wind_speed_unit=ms` | m/s | Sans `wind_speed_unit=ms` l'API renvoie des km/h. |
| `wind_direction` | `wind_direction_10m` | degrés | |
| `pressure` | `pressure_msl` | hPa | Niveau de la mer, comme NOAA `SLP`. |
| `precipitation` | `precipitation` | mm | Cumul de l'heure **précédente** (voir section 4). |
| `visibility` | `visibility` | m | Estimation de modèle (voir section 6). |
| `station_id` | aucun | | Open-Meteo renvoie une maille, pas une station. Proposition : `openmeteo-<city_id>`. |

---

## <img src="assets/icons/database.svg" width="18" height="18" alt=""> 4. Contrat de sortie à respecter

Le but est que **Julie et Seer ne changent rien** : mêmes chemins, mêmes colonnes, mêmes clés.

| Objet | Chemin | Clé | Notes |
| :--- | :--- | :--- | :--- |
| Bronze | `bronze/openmeteo/<api>/city=<id>/year=AAAA.json` | | Réponses brutes, une par ville, année et API. Manifeste `bronze/openmeteo/manifest.json`. |
| Silver | `silver/weather_openmeteo/year=AAAA/weather_france.parquet` | `(station_id, timestamp_utc)` | Préfixe distinct de `weather/` pour ne pas mélanger les deux sources. |
| Gold horaire | `gold/kpis/weather_hourly.parquet` | `(city_id, hour_utc)` | Colonnes actuelles : `city_id, hour_utc, temperature, wind_speed, pressure, visibility, weather_station_count, precipitation`. **Ajouter** `wind_direction` en dernière colonne. |
| Gold journalier | `gold/kpis/weather_daily.parquet` | `(city_id, day_utc)` | Colonnes identiques à aujourd'hui. |

Règles de cohérence :
- Tout en **UTC**. Colonnes temporelles avec fuseau `UTC`.
- **Précipitation** : Open-Meteo donne la somme de l'heure précédente. La valeur reçue à `T` doit être rangée sur `hour_utc = T - 1 h`, comme le fait déjà le code NOAA (`city_hourly`).
- `weather_station_count` vaut 1 (une maille par ville).
- Priorité des sources pour une même heure : archive, puis historical-forecast, puis forecast.

---

## <img src="assets/icons/refresh.svg" width="18" height="18" alt=""> 5. Données toujours fraîches (spécification)

### Principe
1. **Remplissage initial** (une fois) : 5 ans glissants, par ville et par année, en parallèle, avec reprise sur les fichiers déjà présents.
2. **Rafraîchissement incrémental** (en continu) : toutes les heures, un appel à l'API forecast avec `past_days=2&forecast_days=1` par ville, en ne gardant que les heures `<= maintenant`. Fusion dans Gold sur `(city_id, hour_utc)`, la ligne la plus récente remplace l'ancienne.
3. **Réconciliation** (une fois par nuit) : retélécharger les 7 derniers jours depuis historical-forecast (puis archive quand elle les couvre) et remplacer les valeurs provisoires.

### Exécution
- Un service dédié dans `docker-compose.yml` (par exemple `weather-refresh`) qui boucle avec un intervalle, sur le modèle de `scripts/citybikes_stream.py` (`--interval-seconds`). Aujourd'hui rien n'est planifié : chaque flux ne se met à jour que si quelqu'un le relance.
- **Un seul écrivain** par table Gold : lire, fusionner, republier le fichier entier. Deux écrivains simultanés perdraient des lignes.
- Même schéma de rafraîchissement à prévoir pour CityBikes (180 s) et OpenAQ (15 min), pour que `city_hourly` se reconstruise sans action manuelle.

### Affichage
- Le tableau de bord affiche la **dernière heure disponible** de chaque source (`max(hour_utc)`) et un état « à jour » si l'écart est inférieur à 2 h.
- Rafraîchissement automatique de la page à intervalle fixe. Aujourd'hui il faut cliquer sur « Actualiser les KPI ».

### Latence attendue
| Source | Fraîcheur visée |
| :--- | :--- |
| Météo (forecast `past_days`) | heure courante |
| CityBikes | 3 minutes |
| OpenAQ | 15 minutes |
| `city_hourly` | après chaque cycle de rafraîchissement |

---

## <img src="assets/icons/flask.svg" width="18" height="18" alt=""> 6. Simulation de raccord avec l'existant

**Méthode.** Prototype exécuté en local (3 villes de `cities.yml`, du 19/11/2021 au 18/11/2026, 33 requêtes), sans publication. Comparaison avec les tables Gold réelles de R2, en lecture seule. Le prototype n'est pas dans le dépôt.

### <img src="assets/icons/check-circle.svg" width="18" height="18" alt=""> Ce qui se raccorde
| Test | Résultat |
| :--- | :--- |
| Colonnes de `weather_hourly` et `weather_daily` | Identiques, plus `wind_direction` en option. |
| Clé `(city_id, hour_utc)` unique | Oui, 131 472 lignes. |
| Jointure pollution × météo | **922 heures communes sur 923**, contre **0 avec NOAA**. Aucune multiplication de lignes. |
| Température (80 477 heures communes 2022-2024) | Corrélation **0,986**, écart moyen -0,6 °C |
| Pression | Corrélation **0,999**, écart moyen -0,05 hPa |
| Vent | Corrélation 0,85, écart moyen -0,3 m/s |
| Maximum du 19/07/2022 à Paris | 39,1 °C contre 39,9 °C (NOAA) |
| Précipitation | 20 726 heures de pluie sur 131 469 contre **0** pour NOAA |

### <img src="assets/icons/alert.svg" width="18" height="18" alt=""> Ce qui ne se raccorde pas encore
| Test | Résultat | Solution |
| :--- | :--- | :--- |
| Jointure vélos × météo | **0 heure commune** : vélos du 19/11 à 10-11 h UTC, météo simulée jusqu'au 18/11 | Le rafraîchissement de la section 5 apporte les heures du jour. L'API forecast couvre bien 11 h et 12 h UTC le 19/11. |
| Visibilité | Corrélation **0,22** avec NOAA, médiane 24 km contre 16 km | Estimation de modèle, pas une mesure. Voir section 7. |
| Heures triples (météo + pollution + vélos) | 0 | Se règle avec le point précédent et quelques jours de collecte vélos. |

---

## <img src="assets/icons/alert.svg" width="18" height="18" alt=""> 7. Limites à écrire dans les résultats

- **Visibilité modélisée** : Open-Meteo fournit une estimation et non une mesure d'aéroport. À indiquer dans l'analyse « météo et visibilité », et à ne pas présenter comme comparable à NOAA.
- **Maille et non station** : la position renvoyée est celle de la maille (Paris : 48,89 N, 2,29 E), pas Paris-Orly.
- **Ancienneté de la visibilité** : absente avant le 1er janvier 2022. Les premières semaines de la fenêtre de 5 ans n'en ont pas.
- **Valeurs provisoires** : les derniers jours viennent de modèles de prévision et sont remplacés par la réanalyse quand elle est disponible.
- **Villes** : un appel par ville. Pour « stations françaises », élargir à une liste de grandes villes (le prototype en prévoyait 10) et le justifier.

---

## <img src="assets/icons/clipboard.svg" width="18" height="18" alt=""> 8. Travail de Rémi

> État après la PR #9 : le script, le notebook, la publication dans Gold et la mise à jour des résultats sont faits. Restent le rafraîchissement planifié, la validation par l'enseignant et la visibilité avant 2025.

- [ ] Faire valider le changement de source par l'enseignant.
- [ ] `scripts/openmeteo_batch.py` : requêtes parallèles par ville et année, reprise sur fichiers présents, manifeste, reprise sur 429 et 5xx, options `--mode`, `--start-date`, `--end-date`, `--upload`.
- [ ] Respecter le contrat de la section 4, en particulier le décalage d'une heure de la précipitation et l'UTC.
- [ ] Mode rafraîchissement (section 5) et service dans `docker-compose.yml`.
- [ ] Lancer le remplissage 5 ans **sans** `--upload`, vérifier avec le diagnostic ci-dessous, prévenir Julie et Seer, puis publier.
- [ ] Mettre à jour `notebooks/01_noaa_batch.ipynb` (renommer, nouvelle source, vraie pluie, visibilité signalée comme modélisée) et remplacer [RESULTATS_NOAA.md](RESULTATS_NOAA.md) par un bilan Open-Meteo. Conserver l'ancien comme historique.
- [ ] Reprendre les quatre questions météo avec les nouvelles données.

**Contrôle d'acceptation** (à relancer avant et après publication) :
1. Mêmes colonnes et même clé que l'actuel `weather_hourly.parquet`.
2. Aucune ligne dupliquée sur `(city_id, hour_utc)`.
3. Dernière `hour_utc` au plus 2 h avant l'heure courante.
4. Heures communes avec `pollution_hourly` supérieures à 0, jointure sans multiplication.
5. Au moins une heure de pluie.

---

## <img src="assets/icons/folder.svg" width="18" height="18" alt=""> 9. Fichiers du dépôt à adapter

| Fichier | Changement |
| :--- | :--- |
| `src/openaq_pipeline.py` lignes 540-553 | Libellés « Météo NOAA » vers Open-Meteo ; retirer le repli sur `sample/2025-2025/kpis/weather_hourly.parquet` ; ajouter `wind_direction` à `w_cols` (ligne 583) pour l'analyse vent et pollution. |
| `notebooks/05_dashboard.ipynb` | Texte « Historique massif sur 5 ans (2020-2024) » et « NOAA » ; afficher la fraîcheur ; rafraîchissement automatique. |
| `config/cities.yml` | `noaa_station_filter` devient inutile après la migration ; le supprimer en dernier. |
| `README.md`, `docs/PLAN.md`, `docs/GUIDE_TECHNIQUE.md` (section 3.2) | Source, commandes, schéma. |
| `docs/AVANCEMENT.md` | Section Partie 1 : voir la nouvelle sous-section ajoutée. |
| `scripts/noaa_batch.py` | À conserver comme preuve de réalisation du batch parallèle NOAA. |

---

## <img src="assets/icons/hard-drive.svg" width="18" height="18" alt=""> 10. Audit du stockage en ligne (Cloudflare R2)

Relevé en lecture seule du 19 novembre 2026. **Rien n'a été supprimé.**

| Bucket | Préfixe | Objets | Taille | Décision proposée |
| :--- | :--- | ---: | ---: | :--- |
| Bronze | `noaa/` | 1 030 | 6 040 Mo | **Supprimer après migration validée.** Reproductible depuis l'archive publique (manifeste conservé), 98 % du stockage utilisé. |
| Bronze | `sample/2025-2025/` | 4 | 12 Mo | Supprimer après migration (échantillon). |
| Bronze | `openaq/` | 176 | 32 Mo | **Garder.** Historique non rejouable à l'identique. |
| Bronze | `citybikes/` | 6 | 2 Mo | **Garder, ne jamais supprimer.** L'API n'a aucun historique : ces relevés sont irremplaçables. |
| Silver | `weather/` (NOAA) | 5 | 77 Mo | Archiver en local puis supprimer après migration. |
| Silver | `sample/2025-2025/` | 1 | 0,2 Mo | Supprimer après migration. |
| Silver | `citybikes/`, `pollution/` | 8 | 0,5 Mo | Garder. |
| Gold | `kpis/weather_*` | 4 | 2,8 Mo | **Écrasés** par la publication Open-Meteo. Sauvegarder les anciens en local avant. |
| Gold | `kpis/mobility_*` et `citybikes/kpis/mobility_*` | 4 | 0,4 Mo | **Doublons identiques.** Garder les deux tant que `src/openaq_pipeline.py` (lit `kpis/`) et le dashboard (lit `citybikes/kpis/` d'abord) n'ont pas un chemin unique. Choisir un chemin canonique, aligner le code, puis supprimer l'autre. |
| Gold | `sample/2025-2025/kpis/` | 2 | 0,1 Mo | Supprimer après migration. |

**Total actuel : 6,17 Go sur 10 Go gratuits.** Le quota n'est donc pas menacé, y compris avec les JSON bruts Open-Meteo. Supprimer NOAA n'est pas urgent : c'est un choix de cohérence (une seule source météo dans le lac) et de marge.

**Ordre conseillé** :
1. Rémi publie Open-Meteo et la validation de la section 8 est faite.
2. Sauvegarde locale de Gold et de Silver (environ 80 Mo) et du manifeste NOAA.
3. Suppression des préfixes `sample/` et de `silver/weather/`.
4. Suppression de `bronze/noaa/` seulement si l'équipe n'en a plus besoin pour la démonstration NOAA.

<img src="assets/icons/alert.svg" width="18" height="18" alt=""> Le versioning n'est pas disponible sur R2 : une suppression est définitive.

---

## <img src="assets/icons/hard-drive.svg" width="18" height="18" alt=""> 11. Relevé du lac après la bascule (19/11/2026, 14:30 UTC)

Relevé en lecture seule avec les clés du `.env`. Il **remplace l'audit de la section 10**, établi avant la bascule. Un contrôle d'écriture et de suppression sur un objet témoin a été fait puis annulé.

### <img src="assets/icons/check-circle.svg" width="18" height="18" alt=""> Ce qui est en place
| Contrôle | Résultat |
| :--- | :--- |
| Accès | Les trois buckets `urbanhub-bronze`, `urbanhub-silver` et `urbanhub-gold` répondent. Écriture, lecture et suppression : OK sur les trois. Le jeton est limité aux buckets (la liste des buckets du compte est refusée) et le versioning est refusé : normal sur R2. |
| Volume | **0,14 Go sur 10 Go** (Bronze 55 Mo, Silver 79 Mo, Gold 5 Mo). Le Bronze NOAA de 6 Go n'existe plus. |
| `kpis/weather_hourly.parquet` | Open-Meteo, **181 050 lignes**, du 01/01/2020 au 19/11/2026 13:00 UTC : à jour de l'heure courante. Aucun doublon sur `(city_id, hour_utc)`. 28 103 heures de pluie. |
| `kpis/weather_daily.parquet` | 7 545 lignes jusqu'au 19/11/2026. Colonnes lues par le dashboard présentes. |
| Sauvegarde NOAA | `kpis/noaa/weather_hourly.parquet` (129 809 lignes) et `kpis/noaa/weather_daily.parquet`. |
| Bronze Open-Meteo | `openmeteo/year=AAAA/city_id=<id>` (21 fichiers de 0,4 Mo) et un manifeste. |
| Jointures avec la météo actuelle | Pollution : **923 heures sur 923**. Vélos : **6 sur 6**. Sans multiplication de lignes. |

### <img src="assets/icons/alert.svg" width="18" height="18" alt=""> Écarts à traiter
| Écart | Détail | Action |
| :--- | :--- | :--- |
| **`city_hourly` périmé** | Toujours 130 738 lignes, écrit à 14:03, avant la bascule : 129 823 `meteo_seule`, 909 `pollution_seule`, 6 `mobilite_seule`. Le dashboard n'affiche donc encore aucun croisement. | Relancer `notebooks/03_openaq_iot.ipynb` (étape 5). |
| **Visibilité absente avant fin 2025** | 0 valeur en 2020-2024, 7 203 en 2025, complète en 2026 (30 429 sur 181 050). La question « météo et visibilité » ne porte que sur environ un an. Mon test avait trouvé la visibilité dès 2022 avec l'API historical-forecast : le modèle utilisé ici (`ecmwf_ifs`) n'en fournit pas avant. | À vérifier avec Rémi, quitte à interroger l'API sans fixer le modèle. |
| Colonnes hors contrat | `weather_station_count` absent ; `source`, `weather_model` et `wind_direction` ajoutés. Le code actuel ne lit que des colonnes nommées, donc rien ne casse. | Documenter la décision, ou aligner. |
| Fenêtre de 6,9 ans | Données depuis le 01/01/2020, au-delà des 5 ans demandés. | Aucune, sauf si l'on veut s'aligner sur 5 ans. |
| Triple recouvrement | Pollution (jusqu'au 19/11 01:00) et vélos (19/11 10-11 h) ne se recoupent pas entre eux : 0 heure commune aux trois. | Laisser tourner CityBikes et OpenAQ. |
| Résidus NOAA | `silver/weather/` (78 Mo) et les trois préfixes `sample/` (12 Mo) existent encore ; le code `src/openaq_pipeline.py` lit toujours `sample/2025-2025/...` en repli. | Supprimer après sauvegarde locale, une fois `city_hourly` reconstruit. |
| Rafraîchissement | La météo est à jour de l'heure courante, mais rien n'indique un service planifié dans le dépôt. | Vérifier avec Rémi comment elle est actualisée (section 5). |
