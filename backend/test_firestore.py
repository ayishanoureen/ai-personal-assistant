import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

print("Connected to project:", firebase_admin.get_app().project_id)

db.collection("test").add({
    "message": "hello"
})

print("Data added successfully!")