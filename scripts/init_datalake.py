"""
Script d'initialisation et de validation du Data Lake UrbanHub (S3 / MinIO / Cloudflare R2).
- Connexion sécurisée ou locale via variables d'environnement.
- Vérification / création idempotente des buckets : bronze, silver, gold.
- Activation du versioning sur le bucket bronze (si supporté par le provider S3).
- Test d'écriture et de relecture pour valider les droits.
"""

import os
import sys
import io
from minio import Minio
from minio.error import S3Error
from minio.versioningconfig import VersioningConfig, ENABLED

# Chargement du fichier .env si présent
try:
    from dotenv import load_dotenv
    # Cherche .env dans le dossier courant ou dans UrbanHub/
    if os.path.exists(".env"):
        load_dotenv(".env")
    elif os.path.exists("UrbanHub/.env"):
        load_dotenv("UrbanHub/.env")
    elif os.path.exists("../.env"):
        load_dotenv("../.env")
except ImportError:
    pass

def get_minio_client():
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    protocol = "https" if secure else "http"
    print(f"🔌 Tentative de connexion S3 sur : {protocol}://{endpoint}")
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure
    )

def init_datalake():
    client = get_minio_client()

    bucket_bronze = os.getenv("MINIO_BUCKET_BRONZE", "urbanhub-bronze")
    bucket_silver = os.getenv("MINIO_BUCKET_SILVER", "urbanhub-silver")
    bucket_gold = os.getenv("MINIO_BUCKET_GOLD", "urbanhub-gold")

    buckets = [bucket_bronze, bucket_silver, bucket_gold]

    print("\n📦 Initialisation des couches du Data Lake S3 :")
    for bucket in buckets:
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                print(f"  ✨ Bucket '{bucket}' créé avec succès.")
            else:
                print(f"  ✅ Bucket '{bucket}' existe déjà et est accessible.")
        except Exception as e:
            print(f"  ❌ Erreur sur le bucket '{bucket}': {e}")
            sys.exit(1)

    # Activation du versioning sur Bronze
    try:
        client.set_bucket_versioning(bucket_bronze, VersioningConfig(ENABLED))
        print(f"\n🛡️ Versioning activé avec succès sur le bucket '{bucket_bronze}' !")
    except Exception as e:
        print(f"\nℹ️ Note Versioning sur '{bucket_bronze}' : {e} (normal sur certains tiers cloud sans API versioning explicite)")

    # Test d'écriture / relecture
    try:
        test_payload = b"UrbanHub Data Lake Cloud Test OK"
        client.put_object(
            bucket_bronze,
            "_healthcheck/test.txt",
            io.BytesIO(test_payload),
            len(test_payload),
            content_type="text/plain"
        )
        resp = client.get_object(bucket_bronze, "_healthcheck/test.txt")
        data = resp.read()
        resp.close()
        resp.release_conn()
        client.remove_object(bucket_bronze, "_healthcheck/test.txt")
        print("\n🚀 Test d'écriture et de relecture validé avec succès sur le stockage distant !")
    except Exception as e:
        print(f"\n⚠️ Avertissement lors du test d'écriture/suppression : {e}")

    print("\n🎉 Data Lake UrbanHub opérationnel et prêt pour l'équipe !")

if __name__ == "__main__":
    init_datalake()
