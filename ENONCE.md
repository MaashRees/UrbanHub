# UrbanHub :

## Contexte :

Une **Smart City** génère en permanence des données provenant de multiples sources :

- Capteurs `IoT`
- pollution, bruit, incidents
- Consommation énergétique
- Données environnementales et météorologiques

- Flux de trafic : *routier*, *ferroviaire*, *mobilité douce*, etc.
- Evénements urbains
- …

Ces données doivent être **collectées, stockées, analysées et exploitées** afin de produire des indicateurs utiles aux décideurs publics ! 

L’objectif du projet est de développer **la plateforme UrbanHub** capable d’ingérer et d’analyser ces données. **UrbanHub** est, en effet, ce qu’on appelle un jumeau numérique urbain permettant d'observer et d’analyser le fonctionnement d’une ville moderne.

## Architecture cible :

 provenant de ces **trois types de flux typiques d’un système Big Data réel : 3 types de flux de données (Batch / Streaming / IoT).** 

1. **Flux Batch** (données historiques massives)
2. **Flux Streaming** (données temps réel)
3. **Flux IoT** (données capteurs)

Les données doivent être intégrées dans une architecture proche d’une plateforme Smart City :

```
Sources de données
      │
      ▼
Ingestion (API / Scraping / Download)
      │
      ▼
Stockage Data Lake
      │
      ▼
Traitement Data Engineering
      │
      ▼
Analyse Data / IA
      │
      ▼
Indicateurs urbains
```

---

# Partie 1 – Flux Batch : analyse météorologique urbaine

- **Source de données :**

Index of /data/global-hourly/access/

*Ces données contiennent les observations météorologiques horaires de stations météo situées dans le monde entier* : NOAA Global Hourly Weather Data

## Travail demandé

- Ecrire un `script` qui permet de télécharger <u>parallèlement</u> les fichiers correspondant aux stations météorologiques situées en France ****(pas de téléchargement des fichiers un par un) ****
- **Dimension temporelle : les 5 dernières années; Variables à extraire :**
    
    
    - `station_id`
    - `wind_speed`
    - `pressure`
    
    - `timestamp`
    - `wind_direction`
    - `precipitation`
    
    - `temperature`
    - `visibility`
    
- Mettre en place les éventuels nettoyages possibles sur les données : *valeurs manquantes*, *conversion des unités*, du *timestamp*, etc.

## **Questions métier**

1. Peut-on identifier des **périodes météorologiques anormales** ?
2. Existe-t-il une corrélation entre **conditions météorologiques et visibilité** ?
3. Quelle est l’évolution **saisonnière de la température** en France ; dans les principales villes ?
4. Quels sont les **jours présentant des conditions météorologiques extrêmes** ?

---

# Partie 2 – Flux Streaming : mobilité urbaine

- **Source de données :**

Documentation | CityBikes API

**CityBikes API** : *Cette API fournit des informations **temps réel sur les stations de vélos en libre-service dans le monde***

## Travail demandé

- Mettre en place un système de récupération **automatique toutes les 2-3 minutes** des données de stations des principales villes de France ; Extraire les variables suivantes pour chaque station (depuis l’existence de réseau velib) :
    
    
    - `station_id`
    - `longitude`
    - `free_slots`
    
    - `station_name`
    - `timestamp`
    
    - `latitude`
    - `bikes_available`
    

## Questions métier

1. Quelles stations présentent **le plus fort taux d’utilisation** ?
2. Peut-on identifier des **zones où l’offre de vélos est insuffisante** ?
3. Quels sont les **pics d’utilisation journaliers** du réseau de vélos ?
4. Existe-t-il des **déséquilibres géographiques dans la disponibilité des vélos** ?
5. Peut-on détecter des **stations critiques nécessitant un rééquilibrage des vélos** ?

---

# Partie 3 – Flux IoT : pollution urbaine

- **Source de données :**
    
    
    OpenAQ REST API
    
    `OpenAQ` – pollution atmosphérique : *Cette API fournit des données issues de capteurs de pollution installés dans plusieurs villes du monde*
    

## Travail demandé

- Collecter les données de la France, notamment les principales villes.
- Mettre en place une ingestion régulière simulant un flux IoT ; Variables à extraire :
    
    
    - `sensor_id`
    - `longitude`
    - `unit`
    
    - `pollutant`
    - `timestamp`
    
    - `latitude`
    - `value`
    
- **Polluants principaux :**
    
    
    - PM2.5
    - O3
    
    - PM10
    - CO
    
    - NO2
    
- **Questions métier :**
    1. Quelles zones présentent les **niveaux de pollution les plus élevés** ?
    2. Existe-t-il une **variation journalière de la pollution** ?
    3. Quels polluants sont **les plus dominants dans la ville étudiée** ?
    4. Peut-on identifier des **épisodes de pollution anormale** ?

---

# Partie 4 – Analyse croisée des données

Les différentes sources doivent être croisées afin de produire des analyses urbaines.

- **Questions métier :**
    1. Existe-t-il une relation entre **conditions météorologiques et pollution** ?
    2. Les **conditions météo influencent-elles l’utilisation des vélos urbains** ?
    3. Peut-on identifier des **conditions météorologiques favorables à la mobilité douce** ?
    4. Existe-t-il des périodes où **mobilité, pollution et météo interagissent fortement** ?

---

# Livrables attendus

Les étudiants devront produire :

1. Scripts de collecte des données
2. Stockage structuré des données
3. Pipeline de traitement
4. Analyses exploratoires
5. Visualisations
6. Interprétation des résultats
7. Démo-UrbanHub-Partie1.mp4 ; Démo-UrbanHub-Partie2.mp4

---