from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
import asyncio 
from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
import google.generativeai as genai
import fitz
import shutil
import os
import json
import random

app = FastAPI()

# --- CONFIGURATION ---
API_KEY = "AIzaSyBhwkkRfEvhAPAC_c4PSwN276oqh2sx_SY" 
genai.configure(api_key=API_KEY)


current_model_name = "models/gemini-1.5-flash" 
document_context = ""
questions_cache = []

print(f"🚀 MODE PRÉSENTATION ACTIVÉ : Utilisation de {current_model_name}")

try:
    # On force la recherche de la version 1.5 Flash qui a de meilleurs quotas
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    if "models/gemini-1.5-flash" in available_models:
        current_model_name = "models/gemini-1.5-flash"
    elif "models/gemini-1.5-flash-latest" in available_models:
        current_model_name = "models/gemini-1.5-flash-latest"
    else:
        current_model_name = available_models[0]
        
    print(f"✅ Modèle stable sélectionné : {current_model_name}")
except Exception as e:
    current_model_name = "gemini-1.5-flash" # Fallback par défaut
    print(f"⚠️ Erreur liste modèles, utilisation par défaut : {current_model_name}")

def generate_content_sync(prompt):
    model = genai.GenerativeModel(current_model_name)
    response = model.generate_content(prompt)
    return response.text

# --- ANALYSE DU PDF ---
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    global document_context, questions_cache
    try:
        path = "temp.pdf"
        with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
        doc = fitz.open(path)
        document_context = "".join([page.get_text() for page in doc])
        doc.close()
        
        questions_cache = [] # Vider le cache
        
        # Extraction de concepts clés pour l'affichage (hashtags)
        words = [w.strip(".,() ") for w in document_context.split() if len(w) > 7]
        concepts = list(set(random.sample(words, min(len(words), 5)))) if words else ["Révision"]
        
        return {"message": "Analyse réussie !", "concepts": concepts}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

# --- GÉNÉRATION DE QUIZ (GROUPE DE 10) ---
@app.get("/generate_full_quiz")
async def generate_full_quiz(lang: str = Query("fr")):
        global document_context, questions_cache
        
        if not document_context:
            return JSONResponse(status_code=400, content={"error": "Document non chargé."})

        if len(questions_cache) > 0:
            return questions_cache.pop(0)

        prompt = f"""
        Tu es un professeur expert. Analyse ce texte et génère un examen de 10 questions QCM en Français.
        Chaque question doit avoir 4 options et une réponse exacte.
        Réponds UNIQUEMENT avec un tableau JSON (Array) contenant 10 objets.
        Format attendu : [ {{"question": "...", "options": ["a", "b", "c", "d"], "answer": "..."}}, ... ]
        Texte du cours : {document_context[:4000]}
        """

        model = genai.GenerativeModel(current_model_name)
        
        # On tente 3 fois en cas de quota atteint
        for tentative in range(3):
            try:
                raw_text = await run_in_threadpool(model.generate_content, prompt)
                text = raw_text.text.strip()
                if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
                
                new_questions = json.loads(text)
                if isinstance(new_questions, list) and len(new_questions) > 0:
                    questions_cache = new_questions
                    return questions_cache.pop(0)
            except Exception as e:
                if "429" in str(e):
                    print(f"⏳ Quota quiz atteint, attente 3s (essai {tentative+1})...")
                    await asyncio.sleep(3)
                    continue
                print(f"❌ Erreur Quiz : {e}")
                break

        # Secours final
        return {
            "question": "L'IA prépare encore les questions. Quel est l'objectif principal du document ?",
            "options": ["Analyse de données", "Révision du cours", "Introduction au sujet", "Conclusion"],
            "answer": "Révision du cours"
        }
# --- POSER UNE QUESTION (AVEC GESTION QUOTA) ---
# --- Modifier la route /ask dans main.py ---

@app.post("/ask")
async def ask_question(action: str = Form(...)): # On change 'question' par 'action'
    if not document_context:
        return {"answer": "Veuillez d'abord charger un document PDF."}
    
    model = genai.GenerativeModel(current_model_name)
    
    # On définit le prompt selon l'action demandée
    if action == "resume":
        prompt = f"""Analyse ce cours et fais-en un résumé structuré et pédagogique en Français. 
        Utilise des listes à puces pour les points clés.
        Texte : {document_context[:8000]}"""
    elif action == "imports":
        prompt = f"""Extrait uniquement la liste des bibliothèques, librairies, packages ou 'imports' 
        mentionnés dans ce document technique (ex: java.util, import torch, #include, etc.). 
        Explique brièvement l'utilité de chaque import trouvé.
        Texte : {document_context[:8000]}"""
    else:
        return {"answer": "Action non reconnue."}
    
    for tentative in range(3):
        try:
            res = await run_in_threadpool(model.generate_content, prompt)
            # On remplace les caractères Markdown par des balises HTML simples si besoin, 
            # mais Gemini renvoie du texte clair lisible.
            return {"answer": res.text}
        except Exception as e:
            if "429" in str(e):
                await asyncio.sleep(2)
                continue
            return {"answer": "L'IA est occupée, réessayez."}
    
    return {"answer": "le temps d'attente est dépassé. Attendez une minute."}
# --- SERVIR LES FICHIERS STATIQUES ---
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

# --- LANCEMENT DU SERVEUR ---
if __name__ == "__main__":
    import uvicorn
    print("🚀 Serveur démarré sur http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
