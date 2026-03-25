import base64
import binascii
import json
from app.config import settings

import firebase_admin
from firebase_admin import credentials


def init_firebase():
    if firebase_admin._apps:
        return True

    firebase_key = settings.FIREBASE_KEY_BASE64.replace("\n", "").replace("\r", "").strip()
    if not firebase_key:
        print("Firebase initialization skipped: FIREBASE_KEY_BASE64 is empty.")
        return False

    try:
        firebase_json = json.loads(base64.b64decode(firebase_key))
        cred = credentials.Certificate(firebase_json)
        firebase_admin.initialize_app(cred)
        print(f"Firebase initialized {firebase_admin.get_app().name}")
        return True
    except (binascii.Error, json.JSONDecodeError, ValueError) as exc:
        print(f"Firebase initialization skipped: invalid credentials configuration. {exc}")
        return False


def is_firebase_initialized():
    return bool(firebase_admin._apps)
