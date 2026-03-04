import json
import base64
from app.config import settings

import firebase_admin
from firebase_admin import credentials, messaging


def init_firebase():
    firebase_key = settings.FIREBASE_KEY_BASE64.replace("\n", "").replace("\r", "")
    firebase_json = json.loads(base64.b64decode(firebase_key))


    cred = credentials.Certificate(firebase_json)
    firebase_admin.initialize_app(cred)
    print(f"Firebase initialized {firebase_admin.get_app().name}")

    print("firebase json file>>>>>>>>>>> ",firebase_json)