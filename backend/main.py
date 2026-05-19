from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import os

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model=genai.GenerativeModel("gemini-2.5-flash")
cred=credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)
print(firebase_admin.get_app().project_id)

db=firestore.client()


app=FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def home():
    return {
        "message": "FastAPI backend is running successfully!"
    }

@app.post("/chat")
async def chat(request: ChatRequest):
    user_message=request.message
    response=model.generate_content(user_message)
    ai_reply=response.text

    #db.collection("chat_history").add({
    #   "user_message": user_message,
    #    "ai_reply": ai_reply
    #})
    return {
        "reply":ai_reply
    }