from flask import Flask, request, jsonify
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from bs4 import BeautifulSoup
import tiktoken  # For GPT-4-compatible tokenization
import faiss
import numpy as np
import json
from openai import OpenAI
import os
import spacy
from datetime import datetime
from dotenv import load_dotenv
from flask_cors import CORS

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*CUDA initialization.*")

app = Flask(__name__)
CORS(app)

SYSTEM_PROMPT_BASE = """
You are a medical assistant helping a general practitioner (GP) by conducting a structured pre-consultation with a patient.
Your goal is to ask appropriate questions to gather all relevant medical details about the patient's symptoms, history, medications, and other concerns.
Ask one clear, natural question at a time. Use layman's terms when possible.

Once enough information is gathered, stop asking questions and say: "Thank you. I will now summarize your information for the doctor."

After that, output a structured summary in this JSON format:

{
  "chief_complaint": "...",
  "symptom_details": {
    "onset": "...",
    "duration": "...",
    "severity": "...",
    "location": "...",
    "associated_symptoms": [...]
  },
  "past_medical_history": [...],
  "medications": [...],
  "allergies": [...],
  "review_of_systems": {
    ...
  }
}
"""

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
index = None
metadata = []
nlp = None

def initialize():
    global index, metadata, nlp
    load_dotenv()

    # Scrape guidelines
    url = "https://www.nice.org.uk/guidance/ng130"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    content = soup.find_all(['p', 'h2', 'li'])
    guideline_content = "\n".join([tag.get_text().strip() for tag in content])

    # Chunk and embed
    enc = tiktoken.get_encoding("cl100k_base")
    sentences = guideline_content.split(". ")
    chunks, current_chunk = [], ""
    for sentence in sentences:
        if len(enc.encode(current_chunk + sentence)) < 500:
            current_chunk += sentence + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "
    chunks.append(current_chunk.strip())

    index = faiss.IndexFlatL2(1536)
    embeddings = [embed_text(client, chunk) for chunk in chunks]
    index.add(np.array(embeddings).astype('float32'))
    metadata = [{"text": chunk, "source": "NICE chest pain"} for chunk in chunks]

    try:
        nlp = spacy.load("en_core_sci_sm")
    except OSError:
        raise OSError("scispaCy model 'en_core_sci_sm' is not installed.")

def embed_text(client, text: str):
    if not isinstance(text, str):
        raise ValueError(f"[embed_text] Expected string for embedding input, got {type(text)}: {text}")

    text = text.strip()
    if not text:
        raise ValueError("[embed_text] Cannot embed empty string.")

    try:
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[embed_text] OpenAI embedding error: {e}")
        raise

def fetch_patient_medical_history(patient_id):
    load_dotenv(override=True)
    id_token = os.getenv("GOOGLE_ID_TOKEN")
    if not id_token:
        raise RuntimeError("GOOGLE_ID_TOKEN is missing from .env!")
    
    print("🔐 GOOGLE_ID_TOKEN (JWT):", id_token)

    url = f"http://localhost:5000/api/v1/patient/{patient_id}/medical-history"
    headers = {"Authorization": f"Bearer {id_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Failed to fetch medical history: {e}")
        return {}

def get_time_based_greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Dobré ráno"
    elif hour < 18:
        return "Dobrý deň"
    else:
        return "Dobrý večer"

def generate_greeting(patient_name=None, returning=False):
    greeting = get_time_based_greeting()
    name_part = f", {patient_name}" if patient_name else ""
    intro = "Vitajte späť" if returning else "Som váš virtuálny zdravotný asistent"
    return f"{greeting}{name_part}. {intro}. Ako sa dnes cítite? Môžete mi opísať svoje zdravotné ťažkosti?"

def build_prompt(symptom_context="", patient_medical_history=""):
    prompt = SYSTEM_PROMPT_BASE
    if patient_medical_history:
        prompt += f"\n\nPatient's medical history:\n{patient_medical_history}"
    if symptom_context:
        prompt += "\n\nUse the following medical guidelines to inform your questioning:\n" + symptom_context
    return prompt

def translate_slovak_to_english(text_sk):
    prompt = f"Translate the following Slovak text to English:\n\n{text_sk}"
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response.choices[0].message.content.strip()

def extract_medical_keywords(text_en):
    doc = nlp(text_en)
    return list({ent.text.lower() for ent in doc.ents})

def retrieve_relevant_chunks(query, top_k=3):
    query_embedding = embed_text(client, query)
    D, I = index.search(np.array([query_embedding]).astype('float32'), top_k)
    return [metadata[i]["text"] for i in I[0]]

def call_gpt4(conversation):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=conversation,
        temperature=0.4
    )
    return response.choices[0].message.content

def translate_english_to_slovak(text_en):
    prompt = f"Translate the following English text to Slovak:\n\n{text_en}"
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response.choices[0].message.content.strip()

@app.route("/start-consultation/<int:patient_id>", methods=["GET"])
def start_consultation(patient_id):
    patient_data = fetch_patient_medical_history(patient_id)
    if not patient_data:
        return jsonify({"error": "Unable to fetch patient data."}), 500
    greeting = generate_greeting(patient_data.get("firstName"), returning=True)
    return jsonify({"greeting": greeting, "conversation": [{"role": "assistant", "content": greeting, "content_sk": greeting}]})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_input = data.get("input")
    conversation = data.get("conversation", [])

    translated_input = translate_slovak_to_english(user_input)
    print (f"User input (translated to English): {translated_input}")
    if not translated_input:
        return jsonify({"error": "Invalid input."}), 400    
    keywords = extract_medical_keywords(translated_input)

    guideline_context = ""
    if len(keywords) > 0:
        guideline_context = "\n\n".join(retrieve_relevant_chunks(", ".join(keywords)))
    system_prompt = build_prompt(guideline_context)

    conversation = [msg for msg in conversation if msg['role'] != 'system']
    conversation.insert(0, {"role": "system", "content": system_prompt})
    conversation.append({"role": "user", "content": user_input})

    assistant_reply = call_gpt4(conversation)
    assistant_reply_sk = translate_english_to_slovak(assistant_reply)

    conversation.append({"role": "assistant", "content": assistant_reply, "content_sk": assistant_reply_sk})
    return jsonify({"conversation": conversation})    

if __name__ == "__main__":
    initialize()
    app.run(host="0.0.0.0", port=8000, debug=True)
