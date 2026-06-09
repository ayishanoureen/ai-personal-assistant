# firebase_config.py
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import logging

logger = logging.getLogger(__name__)

db = None

try:
    cred_json = os.getenv("FIREBASE_CREDENTIALS")

    if cred_json:
        cred_dict = json.loads(cred_json)
        cred = credentials.Certificate(cred_dict)

        firebase_admin.initialize_app(cred)
        db = firestore.client()

        logger.info("Firebase initialized")

except Exception as e:
    logger.error(f"Firebase init failed: {e}")