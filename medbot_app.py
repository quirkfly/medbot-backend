from flask import Flask, request, jsonify
import os
from openai import OpenAI
from dotenv import load_dotenv
from flask_cors import CORS
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*CUDA initialization.*")

app = Flask(__name__)
CORS(app)

# ---- Multilingual greeting templates (now explicitly ask for patient's name) ----
GREETING_TEMPLATES = {
    "Slovak": (
        "Dobrý deň, som virtuálny asistent vášho všeobecného lekára. "
        "Ako sa dnes cítite? Môžete mi opísať svoje zdravotné ťažkosti? "
        "Ako sa, prosím, voláte?"
    ),
    "English": (
        "Hello, I am the virtual assistant for your general practitioner. "
        "How are you feeling today? Can you describe your health concerns? "
        "What is your full name, please?"
    ),
    "German": (
        "Guten Tag, ich bin der virtuelle Assistent Ihres Hausarztes. "
        "Wie fühlen Sie sich heute? Können Sie mir Ihre Beschwerden beschreiben? "
        "Wie ist bitte Ihr vollständiger Name?"
    ),
    "Spanish": (
        "Hola, soy el asistente virtual de su médico de cabecera. "
        "¿Cómo se siente hoy? ¿Puede describirme sus problemas de salud? "
        "¿Cuál es su nombre completo, por favor?"
    ),
}

def build_system_prompt(patient_language: str) -> str:
    """
    System prompt:
    - Converse entirely in patient_language
    - Ask patient's name early (if unknown) and use it respectfully thereafter
    - Keep interview concise (10–15 questions)
    - Include Guideline Prioritization Rules
    - Final JSON: English keys, values in patient_language, and include patient.name
    """
    return f"""
You are a medical assistant helping a general practitioner (GP) by conducting a structured pre-consultation with a patient.

Your goals:
- Ask only the most clinically relevant questions to gather essential information.
- Keep the conversation concise: aim for 10–15 total questions (unless urgent safety issues require clarification).
- Always prefer brevity and efficiency over exhaustive detail.
- Use layman’s terms and an empathetic tone.
- Ask one question at a time.

--- Language policy ---
- Use **{patient_language}** for ALL interaction with the patient (greetings, questions, confirmations, recap).
- The FINAL JSON summary must have **English keys** but **values in {patient_language}**.

--- Patient name capture ---
- If the patient's name is not known, ask for it early (ideally in the first turn).
- Use the patient’s stated name respectfully in subsequent questions (e.g., addressing them by first name).
- In the final JSON, include the patient's name under: "patient": {{"name": "<value in {patient_language}>"}}.

--- Guideline Prioritization Rules ---
When asking follow-up questions or deciding which red flags to explore, prioritize guideline sources as follows:
1. Chest pain, dyspnea, palpitations, syncope → ESC first, then NICE.
2. Fever, cough, sore throat, diarrhea, rash, travel exposure, vaccination → CDC first, then NICE; WHO if travel/outbreak-related.
3. Common GP complaints (headache, back pain, urinary symptoms, dyspepsia, musculoskeletal, dermatology) → NICE first.
4. Antibiotic selection and stewardship → IDSA first, then NICE for primary-care indications.
5. Pediatrics (fever, cough, diarrhea, growth, vaccines) → WHO (IMCI) first, then CDC for immunizations, then NICE.
6. Chronic disease (hypertension, diabetes, asthma, COPD) → NICE first; consult ESC for cardiometabolic overlap.
7. Women’s health (pregnancy, contraception, STI screening) → NICE first, then CDC for STI specifics.

--- Red flag overrides ---
Escalate immediately if patient mentions:
- Chest pain with diaphoresis, radiation, or syncope
- Severe dyspnea, hypoxia, or altered mental status
- Focal neurological deficit, sudden “worst” headache, or neck stiffness
- Sepsis indicators: fever with hypotension, tachycardia, or rigors

--- Context modifiers ---
- Travel/migration history → increase priority of CDC/WHO.
- Outbreak terms (measles, dengue, COVID) → CDC/WHO highest.
- EU/UK context → favor NICE/ESC.
- Antibiotic resistance terms → favor IDSA.

--- Conversation flow ---
- Start with the greeting in {patient_language} and ask for the patient's name if unknown.
- Ask one concise question at a time in {patient_language}.
- Periodically recap to confirm accuracy in {patient_language}.
- Stop when sufficient detail is collected (normally within 10–15 questions) and say (in {patient_language}) the equivalent of:
  "Thank you. I will now summarize your information for the doctor."

--- Final output ---
After the stop phrase, output ONLY the JSON summary with:
- English keys
- All values in {patient_language}
- No extra commentary, no markdown, no code fences.
  The required structure is:

{{
  "patient": {{
    "name": "..."
  }},
  "chief_complaint": "...",
  "symptom_details": {{
    "onset": "...",
    "duration": "...",
    "severity": "...",
    "location": "...",
    "associated_symptoms": [...]
  }},
  "past_medical_history": [...],
  "medications": [...],
  "allergies": [...],
  "review_of_systems": {{
    ...
  }}
}}
"""

# OpenAI client
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def call_gpt(conversation):
    """Generic chat call—expects a messages list with 'system' already present."""
    response = client.chat.completions.create(
        model="gpt-5",  # keep aligned with your deployment
        messages=conversation
        # No temperature parameter: gpt-5 requires default temperature
    )
    return response.choices[0].message.content

# ------------------- ROUTES -------------------

@app.route("/start-consultation/<patient_language>", methods=["GET"])
def start_consultation(patient_language):
    """
    Starts a consultation using patient_language. Returns a localized greeting
    and an initialized conversation (system prompt + assistant greeting).
    The greeting now also asks the patient's name.
    """
    system_prompt = build_system_prompt(patient_language)
    greeting = GREETING_TEMPLATES.get(patient_language, GREETING_TEMPLATES["English"])

    conversation = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": greeting}
    ]
    return jsonify({
        "greeting": greeting,
        "patient_language": patient_language,
        "conversation": conversation
    })

@app.route("/chat", methods=["POST"])
def chat():
    """
    Continues the consultation:
    - Builds conversation list from previous messages and appends user_input
    - Calls GPT and returns updated conversation
    """
    data = request.get_json()
    user_input = data.get("input")
    conversation = data.get("conversation", [])

    if not isinstance(conversation, list):
        return jsonify({"error": "conversation must be a list of message dicts"}), 400
    if not user_input or not isinstance(user_input, str):
        return jsonify({"error": "invalid input"}), 400

    # Append the user's latest turn
    conversation.append({"role": "user", "content": user_input})

    # Call the model with the full history (system should already be present)
    assistant_reply = call_gpt(conversation)

    # Append assistant turn
    conversation.append({"role": "assistant", "content": assistant_reply})

    return jsonify({"conversation": conversation})

# ------------------- MAIN -------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
