"""
context_window.py - Gestion de la fenêtre de contexte tournante

v1.1.0 - 2026-01-09
- FIX: L'archive ne contient plus le SYSTEM_CONTEXT (évite indexation du system prompt par Scribe)
"""

import tiktoken
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, List

# === CONFIGURATION ===
THRESHOLD = 30000      # Tokens avant rotation
OVERLAP = 7500         # Tokens à garder lors de rotation
MODEL = "gpt-4o"       # Modèle de référence pour le comptage
MAX_INPUT = 180000     # Maximum absolu (2 fenêtres)

# === INSTRUCTIONS SYSTÈME (Template Injection) ===
SYSTEM_PROMPT_FILE = Path.home() / "Dropbox" / "aiterego_memory" / "config" / "agent_system_prompt.txt"
MNEMOSYNE_NOTES_FILE = Path.home() / "Dropbox" / "aiterego_memory" / "config" / "mnemosyne_notes.md"
SYSTEM_CONTEXT_VERSION = "v3"


def load_system_instructions() -> str:
    """Charge les instructions système pour injection dans la fenêtre."""
    result = ""
    
    # 1. Instructions système de base
    try:
        if SYSTEM_PROMPT_FILE.exists():
            result = SYSTEM_PROMPT_FILE.read_text(encoding='utf-8')
    except Exception:
        pass
    
    # 2. Rétroactions Mnémosyne (si disponibles)
    try:
        if MNEMOSYNE_NOTES_FILE.exists():
            notes = MNEMOSYNE_NOTES_FILE.read_text(encoding='utf-8')
            if notes.strip():
                result += f"\n\n# RÉTROACTIONS MNÉMOSYNE\n{notes}\n"
    except Exception:
        pass
    
    # Wrapper avec marqueurs
    if result:
        return f"[SYSTEM_CONTEXT: {SYSTEM_CONTEXT_VERSION}]\n{result}\n[/SYSTEM_CONTEXT]\n---\n"
    return ""


def _strip_system_context(contenu: str) -> str:
    """
    Retire le bloc [SYSTEM_CONTEXT]...[/SYSTEM_CONTEXT] d'un texte.
    Utilisé pour l'archivage et l'extraction d'overlap.
    
    Returns:
        Le contenu sans les instructions système
    """
    if "[SYSTEM_CONTEXT:" not in contenu:
        return contenu
    
    end_marker = "[/SYSTEM_CONTEXT]"
    end_pos = contenu.find(end_marker)
    if end_pos == -1:
        return contenu
    
    # Chercher le séparateur "---" après le marqueur de fin
    separator_pos = contenu.find("---", end_pos)
    if separator_pos == -1:
        # Pas de séparateur, retirer juste jusqu'au marqueur
        return contenu[end_pos + len(end_marker):].lstrip()
    
    # Retirer tout jusqu'après le séparateur
    return contenu[separator_pos + 3:].lstrip()


def count_tokens(text: str) -> int:
    """Compte le nombre de tokens dans un texte."""
    try:
        encoding = tiktoken.encoding_for_model(MODEL)
        return len(encoding.encode(text, disallowed_special=()))
    except Exception:
        # Fallback: estimation grossière (1 token ≈ 4 caractères)
        return len(text) // 4


def get_timestamp_zulu() -> str:
    """Retourne timestamp au format Zulu (UTC)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def should_rotate(current_tokens: int, incoming_tokens: int) -> bool:
    """Vérifie si on doit faire une rotation."""
    return (current_tokens + incoming_tokens) > THRESHOLD


def validate_input_size(text: str) -> Tuple[bool, str]:
    """
    Valide que l'input ne dépasse pas la capacité maximale.
    
    Returns:
        (is_valid, error_message)
    """
    tokens = count_tokens(text)
    if tokens > MAX_INPUT:
        return False, f"Message trop volumineux: {tokens} tokens. Maximum autorisé: {MAX_INPUT} tokens (environ {MAX_INPUT * 4} caractères)."
    return True, ""


def chunk_large_input(text: str, chunk_size: int = None) -> List[str]:
    """
    Découpe un texte volumineux en chunks de taille maximale chunk_size.
    Essaie de couper aux sauts de ligne pour préserver la cohérence.
    
    Returns:
        Liste de chunks
    """
    if chunk_size is None:
        chunk_size = THRESHOLD - OVERLAP  # 22.5K par défaut
    
    tokens_total = count_tokens(text)
    
    # Si ça tient en un chunk, pas besoin de découper
    if tokens_total <= chunk_size:
        return [text]
    
    encoding = tiktoken.encoding_for_model(MODEL)
    tokens = encoding.encode(text, disallowed_special=())
    
    chunks = []
    start = 0
    
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = encoding.decode(chunk_tokens)
        
        # Essayer de couper à un saut de ligne si possible
        if end < len(tokens):
            last_newline = chunk_text.rfind('\n')
            if last_newline > len(chunk_text) // 2:  # Si on trouve un \n dans la 2e moitié
                chunk_text = chunk_text[:last_newline + 1]
                # Recalculer combien de tokens on a vraiment pris
                actual_tokens = len(encoding.encode(chunk_text))
                end = start + actual_tokens
        
        chunks.append(chunk_text)
        start = end
    
    return chunks


def extract_overlap(text: str) -> str:
    """Extrait les derniers OVERLAP tokens du texte."""
    encoding = tiktoken.encoding_for_model(MODEL)
    tokens = encoding.encode(text, disallowed_special=())
    
    if len(tokens) <= OVERLAP:
        return text
    
    # Garder les derniers OVERLAP tokens
    overlap_tokens = tokens[-OVERLAP:]
    return encoding.decode(overlap_tokens)


def _add_token_offsets(contenu: str) -> str:
    """
    Ajoute les token offsets au début de chaque ligne d'échange.
    
    Transforme:
        [2026-01-10T13:29:20.000Z] User: Bonjour
        [2026-01-10T13:29:21.000Z] Iris: Salut!
    
    En:
        0|[2026-01-10T13:29:20.000Z] User: Bonjour
        15|[2026-01-10T13:29:21.000Z] Iris: Salut!
    """
    import re
    
    lines = contenu.split('\n')
    result_lines = []
    token_offset = 0
    
    # Pattern pour détecter une ligne d'échange (commence par [ suivi d'un timestamp)
    exchange_pattern = re.compile(r'^\[(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\]')
    
    for line in lines:
        if exchange_pattern.match(line):
            # C'est une ligne d'échange, ajouter le token offset
            result_lines.append(f"{token_offset}|{line}")
            # Compter les tokens de cette ligne pour le prochain offset
            token_offset += count_tokens(line)
        else:
            # Ligne de continuation (contenu multi-ligne), garder telle quelle
            result_lines.append(line)
            # Compter aussi ces tokens
            if line.strip():
                token_offset += count_tokens(line)
    
    return '\n'.join(result_lines)


def rotate_window(fenetre_path: Path, buffer_dir: Path, echanges_dir: Path = None) -> dict:
    """
    Effectue la rotation de la fenêtre de contexte.
    
    v1.2.0 - 2026-01-10:
    - Retire le SYSTEM_CONTEXT avant archivage
    - Ajoute les token offsets à chaque ligne d'échange
    
    1. Sauvegarde la fenêtre (SANS SYSTEM_CONTEXT, AVEC token offsets) dans echanges/
    2. Extrait l'overlap (SANS SYSTEM_CONTEXT)
    3. Réinitialise la fenêtre avec INSTRUCTIONS + OVERLAP
    
    Returns:
        dict avec infos sur la rotation
    """
    # Lire la fenêtre actuelle
    if not fenetre_path.exists():
        return {"status": "skip", "reason": "Fenêtre vide"}
    
    contenu = fenetre_path.read_text(encoding='utf-8')
    tokens_avant = count_tokens(contenu)
    
    # Créer le nom du fichier d'archive avec timestamp
    now = datetime.now(timezone.utc)
    timestamp = now.strftime('%Y-%m-%dT%H-%M-%S')
    archive_name = f"{timestamp}.txt"
    
    # === FIX v1.1.0: Retirer le SYSTEM_CONTEXT AVANT archivage ===
    contenu_sans_instructions = _strip_system_context(contenu)
    
    # === NEW v1.2.0: Ajouter les token offsets ===
    contenu_avec_offsets = _add_token_offsets(contenu_sans_instructions)
    
    # Sauvegarder dans echanges/YYYY/MM/ (mémoire permanente)
    archive_path = None
    if echanges_dir:
        year_month_dir = echanges_dir / str(now.year) / f"{now.month:02d}"
        year_month_dir.mkdir(parents=True, exist_ok=True)
        archive_path = year_month_dir / archive_name
        archive_path.write_text(contenu_avec_offsets, encoding='utf-8')
    else:
        # Fallback: buffer local (ancien comportement)
        buffer_dir.mkdir(exist_ok=True)
        archive_path = buffer_dir / f"fenetre_{timestamp}.txt"
        archive_path.write_text(contenu_avec_offsets, encoding='utf-8')
    
    # Extraire l'overlap (SANS les token offsets, juste le texte brut)
    overlap = extract_overlap(contenu_sans_instructions)
    tokens_overlap = count_tokens(overlap)
    
    # Réinitialiser la fenêtre avec INSTRUCTIONS + OVERLAP
    instructions = load_system_instructions()
    fenetre_path.write_text(instructions + overlap, encoding='utf-8')
    
    return {
        "status": "success",
        "timestamp": get_timestamp_zulu(),
        "tokens_avant": tokens_avant,
        "tokens_overlap": tokens_overlap,
        "archive": str(archive_path)
    }


def process_large_input(text: str, fenetre_path: Path, buffer_dir: Path) -> dict:
    """
    Traite un input volumineux en le découpant si nécessaire.
    
    Returns:
        dict avec infos sur le traitement
    """
    # Valider la taille
    is_valid, error = validate_input_size(text)
    if not is_valid:
        return {"status": "error", "error": error}
    
    tokens_input = count_tokens(text)
    
    # Si ça tient dans une fenêtre normale, pas de traitement spécial
    if tokens_input <= THRESHOLD:
        return {"status": "normal", "tokens": tokens_input}
    
    # Découper en chunks
    chunks = chunk_large_input(text)
    
    # Archiver tous les chunks sauf le dernier dans le buffer
    buffer_dir.mkdir(exist_ok=True)
    archived = []
    
    for i, chunk in enumerate(chunks[:-1]):
        ts = get_timestamp_zulu().replace(':', '-')
        archive_name = f"chunk_{ts}_part{i+1}.txt"
        archive_path = buffer_dir / archive_name
        archive_path.write_text(chunk, encoding='utf-8')
        archived.append({
            "file": str(archive_path),
            "tokens": count_tokens(chunk)
        })
    
    # Le dernier chunk va dans la fenêtre active
    last_chunk = chunks[-1]
    last_chunk_tokens = count_tokens(last_chunk)
    
    return {
        "status": "chunked",
        "total_tokens": tokens_input,
        "chunks_count": len(chunks),
        "archived": archived,
        "active_chunk_tokens": last_chunk_tokens,
        "active_chunk": last_chunk
    }


def get_window_status(fenetre_path: Path) -> dict:
    """Retourne le statut actuel de la fenêtre."""
    if not fenetre_path.exists():
        return {
            "tokens": 0,
            "threshold": THRESHOLD,
            "usage_percent": 0,
            "should_rotate": False
        }
    
    contenu = fenetre_path.read_text(encoding='utf-8')
    tokens = count_tokens(contenu)
    
    return {
        "tokens": tokens,
        "threshold": THRESHOLD,
        "usage_percent": round((tokens / THRESHOLD) * 100, 1),
        "should_rotate": tokens > THRESHOLD
    }


def initialize_window(fenetre_path: Path) -> dict:
    """
    Initialise une fenêtre vide avec les instructions système.
    À appeler au démarrage si la fenêtre est vide.
    
    Returns:
        dict avec infos sur l'initialisation
    """
    instructions = load_system_instructions()
    
    if not instructions:
        return {"status": "skip", "reason": "Pas d'instructions à injecter"}
    
    # Vérifier si la fenêtre existe et contient déjà les instructions
    if fenetre_path.exists():
        contenu = fenetre_path.read_text(encoding='utf-8')
        if f"[SYSTEM_CONTEXT: {SYSTEM_CONTEXT_VERSION}]" in contenu:
            return {"status": "skip", "reason": "Instructions déjà présentes"}
        # Fenêtre existe mais sans instructions → les ajouter en tête
        fenetre_path.write_text(instructions + contenu, encoding='utf-8')
    else:
        # Fenêtre n'existe pas → la créer avec les instructions
        fenetre_path.parent.mkdir(parents=True, exist_ok=True)
        fenetre_path.write_text(instructions, encoding='utf-8')
    
    return {
        "status": "success",
        "version": SYSTEM_CONTEXT_VERSION,
        "tokens_instructions": count_tokens(instructions)
    }


# === TEST ===
if __name__ == "__main__":
    print("=== Test context_window.py v1.1.0 ===\n")
    
    # Test count_tokens
    test = "Bonjour, comment ça va aujourd'hui?"
    print(f"1. count_tokens('{test}')")
    print(f"   → {count_tokens(test)} tokens\n")
    
    # Test should_rotate
    print(f"2. should_rotate(85000, 10000) avec seuil {THRESHOLD}")
    print(f"   → {should_rotate(85000, 10000)}\n")
    
    print(f"3. should_rotate(25000, 3000) avec seuil {THRESHOLD}")
    print(f"   → {should_rotate(25000, 3000)}\n")
    
    # Test validate_input_size
    print(f"4. validate_input_size() avec MAX_INPUT={MAX_INPUT}")
    print(f"   → Message de 1000 tokens: {validate_input_size('x' * 4000)}\n")
    
    # Test _strip_system_context
    test_content = "[SYSTEM_CONTEXT: v3]\nInstructions...\n[/SYSTEM_CONTEXT]\n---\n[2025-01-01T00:00:00Z] User: Bonjour"
    print(f"5. _strip_system_context()")
    print(f"   → '{_strip_system_context(test_content)[:50]}...'\n")
    
    print("✅ Toutes les fonctions sont prêtes!")
