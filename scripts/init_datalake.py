"""
Script d'initialisation du Data Lake UrbanHub (S3 / MinIO).
- Création idempotente des buckets : bronze, silver, gold.
- Activation du versioning sur le bucket bronze.
- Prise en compte automatique de l'environnement (Docker ou Local).
"""

import os
import sys
from minio import Minio
from minio.error import S3Error
from minio.versioningconfig import VersioningConfig, ENABLED

def get_minio_client():
    # Détection automatique : 'minio:9000' dans Docker, 'localhost:9000' depuis l'hôte Windows
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    print(f"🔌 Tentative de connexion à MinIO sur : http://{endpoint}")
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure
    )

def init_datalake():
    client = get_minio_client()
    buckets = ["bronze", "silver", "gold"]

    print("\n📦 Initialisation des couches du Data Lake :")
    for bucket in buckets:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                print(f"  ✨ Bucket '{bucket}' créé avec succès.")
            else:
                print(f"  ✅ Bucket '{bucket}' existe déjà.")
        except Exception as e:
            print(f"  ❌ Erreur sur le bucket '{bucket}': {e}")
            sys.exit(1)

    # Activation du versioning sur la couche Bronze
    try:
        client.set_bucket_versioning("bronze", VersioningConfig(ENABLED))
        print("\n🛡️ Versioning activé avec succès sur le bucket 'bronze' !")
    except Exception as e:
        print(f"\n⚠️ Impossible d'activer le versioning sur 'bronze': {e}")

    print("\n🎉 Data Lake UrbanHub prêt pour l'ingestion (Bronze ➔ Silver ➔ Gold) !")

if __name__ == "__main__":
    init_datalake()
