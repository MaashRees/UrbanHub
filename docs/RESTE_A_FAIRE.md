# <img src="assets/icons/clipboard.svg" width="18" height="18" alt=""> Reste à faire et budget de stockage

État au 20/11/2026 en fin d'après-midi. Les trois parties du sujet sont réalisées sur les données et dans le Data Lake. Il reste l'enregistrement des vidéos et quelques finitions.

## <img src="assets/icons/check-circle.svg" width="18" height="18" alt=""> Ce qui est terminé

| Partie | Réalisé |
| :--- | :--- |
| Partie 1, météo | Open-Meteo sur 2020 à 2026, archive 2022 à 2026 avec visibilité, Bronze, Silver et Gold publiés, bilan de référence ([RESULTATS_NOAA.md](RESULTATS_NOAA.md)), notebooks 01 et 07 exécutés |
| Partie 2, mobilité | Collecte toutes les 5 minutes en continu, archive officielle CityBikes de novembre 2024 à septembre 2026 transformée en séries horaires (28,4 millions de lignes) et publiée, notebooks 02, 04 et 06 |
| Partie 3, pollution | Pipeline OpenAQ incrémental, archive 2022 à 2026 validée contre l'API (608 heures communes, écart nul), conclusions rédigées ([CONCLUSIONS_POLLUTION.md](CONCLUSIONS_POLLUTION.md)) |
| Partie 4, croisement | Table `city_hourly`, historique 5 ans, mobilité contre météo dans le dashboard et le notebook 04 |
| Restitution | Dashboard Voilà à 6 onglets (météo, mobilité, qualité de l'air, croisement, historique, analyses 5 ans) |

## <img src="assets/icons/hard-drive.svg" width="18" height="18" alt=""> Budget de stockage (quota R2 : 10 Go)

Mesuré le 20/11/2026 : **0,38 Go utilisés sur 10 (3,8 %)**.

| Couche | Volume | Contenu principal |
| :--- | ---: | :--- |
| Bronze | 197 Mo | collecte CityBikes 75 Mo, OpenAQ 75 Mo, archives Open-Meteo et OpenAQ 27 Mo, `sample/` 12 Mo |
| Silver | 168 Mo | archive CityBikes 69 Mo, ancien NOAA 78 Mo, collecte CityBikes 15 Mo, archives OpenAQ et Open-Meteo 6 Mo |
| Gold | 14 Mo | tables `kpis/`, historique `kpis/history/` |

La collecte CityBikes en direct ajoute environ 95 Mo par jour dans R2 (Bronze et Silver, mesuré sur 23 heures). Elle est arrêtée après les vidéos : les données déjà collectées restent.

**Nettoyage possible, sur décision de l'équipe :** l'ancien NOAA (`silver/weather/`, 78 Mo) et les préfixes `sample/` (12 Mo environ) ne servent plus. Le Bronze brut de l'archive CityBikes (environ 950 Mo) n'est pas dans R2 et se retélécharge depuis la source publique.

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> Ce qui reste

| Priorité | Tâche | Qui |
| :--- | :--- | :--- |
| 1 | Enregistrer les deux vidéos de démonstration (`demos/Démo-UrbanHub-Partie1.mp4` et `Partie2.mp4`) | Seer, avec Rémi pour la partie 1 et Conambot et Julie pour la partie 2 |
| 2 | Arrêter la collecte en direct après les vidéos : `docker compose --profile collect stop` | Seer |
| 3 | Relire les conclusions pollution ([CONCLUSIONS_POLLUTION.md](CONCLUSIONS_POLLUTION.md)), brouillon à ajuster ; vérifier les heures du profil journalier sur le graphique | Julie |
| 4 | Utilisateur IAM en lecture seule sur le Gold pour le dashboard (aujourd'hui les conteneurs montent le `.env` avec les clés d'écriture) | Seer |
| 5 | Nettoyer R2 (`sample/`, ancien NOAA) après accord de l'équipe | Seer |
| 6 | Si le temps le permet : URLs pré-signées pour partager des synthèses ([GUIDE_TECHNIQUE.md](GUIDE_TECHNIQUE.md#37-partage-sécurisé-par-urls-pré-signées)) | Seer |
| 7 | Retenir plus de 2 capteurs par polluant et par ville dans l'ingestion OpenAQ | Julie |

## <img src="assets/icons/rocket.svg" width="18" height="18" alt=""> Commandes utiles

| Quand | Commande | Pourquoi |
| :--- | :--- | :--- |
| Après la fusion de la branche | `git pull --rebase` puis `uv sync` | récupérer le code et l'environnement |
| Pour voir le dashboard | `docker compose up -d dashboard` puis [http://localhost:8866](http://localhost:8866) | restitution Voilà |
| Après chaque nouvelle collecte | notebook 03 | reconstruit `city_hourly` |
| Après les vidéos | `docker compose --profile collect stop` | arrête la collecte et la croissance du stockage |

**Ne pas relancer** : les téléchargements d'archives (Open-Meteo, OpenAQ, CityBikes) et leur publication. Ils sont faits et publiés dans R2 ; relancer ne ferait que les retélécharger.

## <img src="assets/icons/video.svg" width="18" height="18" alt=""> Vidéos

- **Partie 1** (météo) : batch Open-Meteo, Data Lake et vue météo du dashboard.
- **Partie 2** (streaming, pollution, croisement) : collecte CityBikes, pollution OpenAQ, croisements et dashboard avec les onglets Historique et Analyses 5 ans.

## <img src="assets/icons/info.svg" width="18" height="18" alt=""> Message à l'équipe (à envoyer quand tout est fusionné)

> Salut, tout est fusionné sur `main` : archives sur 5 ans, historique CityBikes, dashboard à 6 onglets, conclusions pollution et bilan météo. Faites `git pull --rebase` puis `uv sync`, et ne retéléchargez pas les archives : elles sont déjà dans R2. Il reste à enregistrer les deux vidéos de démonstration. Julie, peux-tu relire `docs/CONCLUSIONS_POLLUTION.md` avant ? On arrête la collecte en direct juste après les vidéos.
