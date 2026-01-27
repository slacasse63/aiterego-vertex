"""
hermes_modules/config.py - Configuration et constantes d'Hermès

Centralise tous les chemins et paramètres par défaut.
"""

from pathlib import Path

# === CHEMINS ===
DB_PATH = Path("~/Dropbox/aiterego_memory/metadata.db").expanduser()
TEXTE_BASE_PATH = Path("~/Dropbox/aiterego_memory/").expanduser()

# === POIDS PAR DÉFAUT ===
# Utilisés si aucun QueryProfile fourni
# Correspond à QueryProfile.default() : 30/30/30/0/10
POIDS_ROGET = 0.30
POIDS_EMOTION = 0.30
POIDS_TEMPOREL = 0.30
POIDS_PERSONNES = 0.00
POIDS_RESUME = 0.10

# === LIMITES ===
MAX_TEXT_LENGTH = 2000  # Limite de texte pour les requêtes
DEFAULT_TOP_K = 5       # Nombre de résultats par défaut
MAX_TOKENS_CONTEXT = 4000  # Limite pour le contexte formaté