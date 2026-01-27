"""
config.py - Configuration AIter Ego Local
"""

import os
from pathlib import Path

# === ENVIRONNEMENT ===
ENV = os.environ.get("AITEREGO_ENV", "local")  # "local" ou "azure"

# === CHEMINS ===
# Code (dans aiterego/app/)
BASE_DIR = Path(__file__).parent

# Runtime (dans app/ - éphémère)
DATA_DIR = BASE_DIR / "data"
BUFFER_DIR = BASE_DIR / "buffer"

# Mémoire permanente (dans aiterego_memory/ - Dropbox)
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_DIR = MEMORY_DIR / "echanges"
METADATA_DB = MEMORY_DIR / "metadata.db"

# Créer les dossiers s'ils n'existent pas
DATA_DIR.mkdir(exist_ok=True)
BUFFER_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)
ECHANGES_DIR.mkdir(exist_ok=True)

# === LLM ===
LLM_PROVIDER = "ollama"  # "ollama" pour local, "azure" pour production
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "mistral"  # ou "llama3:70b", "mixtral:8x7b"

# === FENÊTRE DE CONTEXTE ===
CONTEXT_WINDOW = {
    "threshold": 30000,      # Tokens avant rotation
    "overlap": 7500,        # Tokens à garder lors de rotation
    "model": "gpt-4o",       # Modèle de référence pour le comptage
    "input_max": 112000,     # Limite input du modèle
    "output_max": 16000      # Limite output du modèle
}

# === FICHIERS ===
CONTEXTE_FILE = DATA_DIR / "contexte.txt"
SESSION_STATE_FILE = DATA_DIR / "session_state.json"
FENETRE_ACTIVE = DATA_DIR / "fenetre_active.txt"

# === SERVEUR ===
HOST = "0.0.0.0"
PORT = 8183

# === AZURE (pour plus tard) ===
AZURE_CONNECTION_STRING = os.environ.get("AZURE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.environ.get("AZURE_CONTAINER_NAME", "")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_ENGINE = os.environ.get("AZURE_OPENAI_ENGINE", "gpt-4o")