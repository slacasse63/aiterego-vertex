"""
web.py - Interface web PWA pour AIter Ego / MOSS
Serveur Flask avec support Progressive Web App.

Version: 2.0.0
- Support PWA complet (manifest, service worker)
- Icônes et splash screens
- Optimisé pour mobile
"""

import os
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory
import requests

# Optionnel: Whisper pour transcription locale
try:
    import whisper
    WHISPER_AVAILABLE = True
    whisper_model = None
except ImportError:
    WHISPER_AVAILABLE = False
    whisper_model = None

# === CONFIGURATION ===
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8182")
WHISPER_MODEL_SIZE = "medium"
PORT = int(os.environ.get("PORT", 5050))

app = Flask(__name__, 
            static_folder=str(STATIC_DIR),
            static_url_path='/static')


def get_whisper_model():
    """Charge le modèle Whisper à la demande (lazy loading)."""
    global whisper_model
    if WHISPER_AVAILABLE and whisper_model is None:
        print(f"🎤 Chargement du modèle Whisper ({WHISPER_MODEL_SIZE})...")
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        print("✅ Whisper prêt!")
    return whisper_model


# === ROUTES PWA ===

@app.route("/")
def index():
    """Page principale."""
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    """Manifest PWA."""
    return send_from_directory(BASE_DIR, "manifest.json", mimetype='application/manifest+json')


@app.route("/service-worker.js")
def service_worker():
    """Service Worker pour PWA."""
    return send_from_directory(BASE_DIR, "service-worker.js", mimetype='application/javascript')


@app.route("/offline.html")
def offline():
    """Page hors-ligne."""
    return render_template("offline.html")


# === ROUTES API ===

@app.route("/send", methods=["POST"])
def send_message():
    """Envoie un message au backend FastAPI (MOSS)."""
    data = request.get_json()
    message = data.get("message", "")
    
    if not message.strip():
        return jsonify({"error": "Message vide"}), 400
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/alterego",
            json={"message": message},
            timeout=120  # Gemini peut prendre du temps avec gros contexte
        )
        
        if response.ok:
            result = response.json()
            return jsonify({
                "response": result.get("message", "(aucune réponse)"),
                "timestamp": result.get("timestamp", ""),
                "metadata": result.get("metadata", {})
            })
        else:
            return jsonify({"error": f"Erreur backend: {response.status_code}"}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Backend non accessible. Lancez: python main.py"}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout - le serveur met trop de temps à répondre"}), 504
    except Exception as e:
        return jsonify({"error": f"Erreur: {str(e)}"}), 500


@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """Transcrit l'audio via Whisper local."""
    if not WHISPER_AVAILABLE:
        return jsonify({"error": "Whisper non installé. pip install openai-whisper"}), 501
    
    if 'audio' not in request.files:
        return jsonify({"error": "Aucun fichier audio"}), 400
    
    audio_file = request.files['audio']
    temp_path = "/tmp/temp_audio.wav"
    audio_file.save(temp_path)
    
    try:
        model = get_whisper_model()
        result = model.transcribe(temp_path, language="fr")
        transcription = result.get("text", "")
        
        return jsonify({"transcription": transcription.strip()})
        
    except Exception as e:
        return jsonify({"error": f"Erreur transcription: {str(e)}"}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route("/health")
def health():
    """Vérifie la santé du backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if response.ok:
            return jsonify({"status": "ok", "backend": "connected"})
        else:
            return jsonify({"status": "degraded", "backend": "error"}), 500
    except:
        return jsonify({"status": "degraded", "backend": "unreachable"}), 503


# === DÉMARRAGE ===
if __name__ == "__main__":
    # Créer le dossier static/icons si nécessaire
    icons_dir = STATIC_DIR / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    
    # Obtenir l'IP locale pour affichage
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "127.0.0.1"
    
    print("=" * 60)
    print("🧠 AIter Ego - Interface Web PWA")
    print("=" * 60)
    print(f"🌐 Local:    http://localhost:{PORT}")
    print(f"📱 Réseau:   http://{local_ip}:{PORT}")
    print(f"🔗 Backend:  {BACKEND_URL}")
    print(f"🎤 Whisper:  {'✅ Disponible' if WHISPER_AVAILABLE else '❌ Non installé'}")
    print("=" * 60)
    print("📲 Pour installer sur mobile:")
    print(f"   1. Ouvrir http://{local_ip}:{PORT} sur votre téléphone")
    print("   2. iOS: Partager → Sur l'écran d'accueil")
    print("   3. Android: Menu → Installer l'application")
    print("=" * 60)
    
    app.run(debug=True, host="0.0.0.0", port=PORT)
