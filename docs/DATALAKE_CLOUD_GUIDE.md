# <img src="assets/icons/cloud.svg" width="18" height="18" alt=""> Guide de Déploiement & Bascule Data Lake Cloud

> **Objectif :** Ce guide explique pas-à-pas comment créer un Data Lake S3 en ligne **gratuit** (Cloudflare R2 ou Backblaze B2) et comment basculer l'ensemble de la plateforme UrbanHub dessus en modifiant uniquement le fichier `.env`, sans changer une seule ligne de code Python.

---

## <img src="assets/icons/list.svg" width="18" height="18" alt=""> Sommaire

1. [Le Principe : Architecture 100% Agnostique S3](#1-le-principe--architecture-100-agnostique-s3)
2. [Option 1 (Recommandée) : Cloudflare R2 (10 Go gratuits, 0 € de bande passante)](#2-option-1-recommandée--cloudflare-r2-10-go-gratuits-0--de-bande-passante)
3. [Option 2 : Backblaze B2 (10 Go gratuits à vie)](#3-option-2--backblaze-b2-10-go-gratuits-à-vie)
4. [Option 3 : AWS S3 (Si AWS est explicitement requis)](#4-option-3--aws-s3-si-aws-est-explicitement-requis)
5. [Comment basculer en 1 minute (Le Switch `.env`)](#5-comment-basculer-en-1-minute-le-switch-env)
6. [Initialisation & Test de Validation Cloud](#6-initialisation--test-de-validation-cloud)

---

## 1. Le Principe : Architecture 100% Agnostique S3

Dans UrbanHub, tous les scripts Python et notebooks utilisent le protocole universel **Amazon S3 API** via le SDK `minio` et `boto3`.

```text
 ┌────────────────────────────────────────────────────────┐
 │            Code Python UrbanHub (Agnostique)           │
 │  (01_noaa, 02_citybikes, 03_openaq, 04_kpis, 05_dash)  │
 └──────────────────────────┬─────────────────────────────┘
                            │
              Variables dans le fichier .env
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
  ┌───────────────────┐           ┌───────────────────┐
  │  Data Lake Local  │           │  Data Lake Cloud  │
  │  (MinIO Docker)   │           │  (Cloudflare R2)  │
  │  localhost:9000   │           │  *.r2.cloudflarestorage.com
  └───────────────────┘           └───────────────────┘
```

<img src="assets/icons/arrow-right.svg" width="18" height="18" alt=""> **Conséquence :** Pour passer du local au cloud, **aucun code n'est modifié**. On change simplement les identifiants de connexion dans `.env`.

---

## 2. Option 1 (Recommandée) : Cloudflare R2 (10 Go gratuits, 0 € de bande passante)

Cloudflare R2 est le meilleur choix pour un projet étudiant :
- **10 Go de stockage gratuit** à vie.
- **1 000 000 d'opérations d'écriture (Class A) par mois.**
- **10 000 000 d'opérations de lecture (Class B) par mois.**
- **0 € de frais d'egress** (la bande passante sortante est totalement gratuite, aucun risque de mauvaise surprise financière).

### Étapes de configuration sur Cloudflare :

1. Rendez-vous sur [cloudflare.com](https://dash.cloudflare.com/) et connectez-vous (ou créez un compte gratuit).
2. Dans le menu de gauche, cliquez sur **R2 Object Storage**.
3. Cliquez sur **Create Bucket** et créez 3 buckets privés :
   - `urbanhub-bronze`
   - `urbanhub-silver`
   - `urbanhub-gold`
4. Dans le menu de droite de la page R2, cliquez sur **Manage R2 API Tokens**.
5. Cliquez sur **Create API Token** :
   - Nom du token : `urbanhub-token`
   - Permissions : **Object Read & Write** (ou Admin Read & Write).
   - Appliquez à : **All buckets** (ou spécifiquement vos 3 buckets).
   - Cliquez sur **Create API Token**.
6. **Sauvegardez précieusement les informations affichées :**
   - **Access Key ID** (ex: `e8f9...`)
   - **Secret Access Key** (ex: `a1b2c3d4...`)
   - **Jurisdiction-specific endpoint / S3 API URL** :  
     `https://<VOTRE_ACCOUNT_ID>.r2.cloudflarestorage.com`

---

## 3. Option 2 : Backblaze B2 (10 Go gratuits à vie)

Backblaze B2 est une alternative réputée et très rapide à configurer sans carte bancaire :
1. Créez un compte sur [backblaze.com/b2](https://www.backblaze.com/b2).
2. Allez dans **Buckets** ➔ **Create a Bucket** :
   - `urbanhub-bronze` (Private)
   - `urbanhub-silver` (Private)
   - `urbanhub-gold` (Private)
3. Allez dans **App Keys** ➔ **Add a New Application Key** :
   - Nom : `urbanhub-app`
   - Permissions : **Read and Write**.
   - Notez la `keyID` (Access Key) et l'`applicationKey` (Secret Key).
4. L'endpoint S3 est de la forme : `s3.<region>.backblazeb2.com` (ex: `s3.eu-central-003.backblazeb2.com`).

---

## 4. Option 3 : AWS S3 (Si AWS est explicitement requis)

Si l'école ou le professeur exige impérativement AWS S3 :
1. Connectez-vous à la [Console AWS](https://aws.amazon.com/).
2. Créez vos 3 buckets S3 : `urbanhub-bronze-<prenom>`, etc.
3. Dans **IAM** ➔ Créez un utilisateur programmatique `urbanhub-user` avec la politique `AmazonS3FullAccess`.
4. Récupérez la clé d'accès et la clé secrète.
5. L'endpoint sera : `s3.<region>.amazonaws.com` (ex: `s3.eu-west-3.amazonaws.com`).
> <img src="assets/icons/alert.svg" width="18" height="18" alt=""> **Alerte quota AWS :** L'offre gratuite AWS ne comprend que **2 000 requêtes PUT/mois**. Si votre script CityBikes fait un relevé toutes les 2 minutes, vous atteindrez 720 écritures par jour et dépasserez le quota gratuit en moins de 3 jours. Préférez Cloudflare R2 si le cloud n'est pas imposé comme étant AWS.

---

## 5. Comment basculer en 1 minute (Le Switch `.env`)

À la racine de `UrbanHub/`, éditez votre fichier `.env` selon le mode souhaité :

### Mode A : Data Lake Local (MinIO Docker)
```ini
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_SECURE=false
MINIO_BUCKET_BRONZE=bronze
MINIO_BUCKET_SILVER=silver
MINIO_BUCKET_GOLD=gold
OPENAQ_API_KEY=votre_cle_openaq
```

### Mode B : Data Lake Cloud (Cloudflare R2)
```ini
# Remplacer <VOTRE_ACCOUNT_ID> par votre identifiant Cloudflare (sans le https://)
MINIO_ENDPOINT=<VOTRE_ACCOUNT_ID>.r2.cloudflarestorage.com
MINIO_ACCESS_KEY=votre_r2_access_key_id
MINIO_SECRET_KEY=votre_r2_secret_access_key
MINIO_SECURE=true
MINIO_BUCKET_BRONZE=urbanhub-bronze
MINIO_BUCKET_SILVER=urbanhub-silver
MINIO_BUCKET_GOLD=urbanhub-gold
OPENAQ_API_KEY=votre_cle_openaq
```

---

## 6. Initialisation & Test de Validation Cloud

Pour vérifier immédiatement que la connexion vers votre Data Lake Cloud fonctionne :

### 1. Initialiser les buckets à distance avec notre script :
```powershell
uv run python scripts/init_datalake.py
```
Le script lira les variables du `.env`, se connectera en HTTPS sécurisé sur votre cloud, créera les buckets manquants et activera le versioning.

### 2. Tester l'écriture et la relecture d'un fichier test :
Exécutez ce one-liner pour valider le flux :
```powershell
uv run python -c "
import os, io
from minio import Minio
from dotenv import load_dotenv
load_dotenv()

client = Minio(
    os.getenv('MINIO_ENDPOINT'),
    access_key=os.getenv('MINIO_ACCESS_KEY'),
    secret_key=os.getenv('MINIO_SECRET_KEY'),
    secure=os.getenv('MINIO_SECURE', 'false').lower() == 'true'
)

# Test upload dans Bronze
bucket = os.getenv('MINIO_BUCKET_BRONZE', 'bronze')
client.put_object(bucket, 'test_cloud.txt', io.BytesIO(b'Connexion Cloud OK!'), 19)
print(f'[OK] Succès : fichier écrit dans {bucket} sur le Cloud !')

# Lecture
resp = client.get_object(bucket, 'test_cloud.txt')
print('Contenu relu :', resp.read().decode('utf-8'))
resp.close()
"
```

Dès que ce test affiche `Connexion Cloud OK!`, **toute l'équipe (Rémi, Conambot, Julie, Seer) est automatiquement connectée au même Data Lake partagé dans le Cloud !**
