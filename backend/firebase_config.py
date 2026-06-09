import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
import logging

logger = logging.getLogger(__name__)

db = None
firebase_initialized = False

try:
    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS")
        if cred_json:
            try:
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin initialized from FIREBASE_CREDENTIALS env var.")
            except Exception as env_err:
                logger.error(f"Failed to initialize Firebase from FIREBASE_CREDENTIALS env var: {env_err}")
                raise env_err
        else:
            # Try to resolve firebase_key.json relative to this file
            base_dir = os.path.dirname(os.path.abspath(__file__))
            key_path = os.path.join(base_dir, "firebase_key.json")
            if os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
                logger.info(f"Firebase Admin initialized from local key file at: {key_path}")
            else:
                firebase_admin.initialize_app()
                logger.info("Firebase Admin initialized with default application credentials.")
    else:
        logger.info("Firebase Admin already initialized.")

    db = firestore.client()
    firebase_initialized = True
    logger.info("Firestore client initialized successfully.")

except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")