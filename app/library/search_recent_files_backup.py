"""
search_recent_files.py - Scan textuel des fichiers de conversation récents
MOSS v0.9.2 - Session 51

Principe: Scanner ≠ Charger
- On parcourt les fichiers texte en lecture seule
- On extrait SEULEMENT les passages pertinents (±500 chars autour du match)
- On n'embourbe jamais la fenêtre de contexte

Usage dans la cascade de recherche:
1. Fenêtre de contexte active (déjà en mémoire)
2. search_recent_files (ce module) ← RAPIDE, lexical, récent
3. Hermès (sémantique, historique complet)
"""

import os
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
ECHANGES_PATH = Path.home() / "Dropbox" / "aiterego_memory" / "echanges"
DEFAULT_CONTEXT_CHARS = 500  # Caractères à extraire autour du match
MAX_RESULTS = 10  # Maximum de passages à retourner


def get_recent_files(scope: str = "all") -> List[Path]:
    """
    Récupère les fichiers .txt selon la portée temporelle.
    
    Args:
        scope: 'today' | 'week' | 'month' | 'year' | 'all' (défaut: 'all')
    
    Returns:
        Liste de chemins de fichiers, triés du plus récent au plus ancien
    """
    now = datetime.now()
    
    # Calculer la date limite selon la portée
    if scope == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif scope == "week":
        cutoff = now - timedelta(days=7)
    elif scope == "month":
        cutoff = now - timedelta(days=30)
    elif scope == "year":
        cutoff = now - timedelta(days=365)
    elif scope == "all":
        cutoff = datetime(2020, 1, 1)  # Assez loin pour tout inclure
    else:
        # Par défaut: semaine
        cutoff = now - timedelta(days=7)
    
    files = []
    
    # Parcourir la structure echanges/YYYY/MM/*.txt
    if not ECHANGES_PATH.exists():
        logger.warning(f"Dossier echanges introuvable: {ECHANGES_PATH}")
        return files
    
    for year_dir in ECHANGES_PATH.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            
            for txt_file in month_dir.glob("*.txt"):
                # Extraire la date du nom de fichier (format: YYYY-MM-DDTHH-MM-SS.txt)
                try:
                    date_str = txt_file.stem[:10]  # YYYY-MM-DD
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    if file_date >= cutoff:
                        files.append(txt_file)
                except (ValueError, IndexError):
                    # Nom de fichier non standard, ignorer
                    continue
    
    # Trier du plus récent au plus ancien
    files.sort(key=lambda f: f.name, reverse=True)
    
    return files


def extract_context(text: str, match_start: int, match_end: int, context_chars: int = DEFAULT_CONTEXT_CHARS) -> str:
    """
    Extrait le contexte autour d'un match, en essayant de couper aux limites de phrases.
    
    Args:
        text: Texte complet
        match_start: Position de début du match
        match_end: Position de fin du match
        context_chars: Nombre de caractères de contexte de chaque côté
    
    Returns:
        Passage extrait avec le match en contexte
    """
    # Calculer les bornes brutes
    start = max(0, match_start - context_chars)
    end = min(len(text), match_end + context_chars)
    
    # Essayer de trouver le début d'une ligne/phrase
    if start > 0:
        # Chercher un saut de ligne ou un timestamp
        newline_pos = text.rfind('\n', start - 100, match_start)
        if newline_pos > start - 100:
            start = newline_pos + 1
    
    # Essayer de trouver la fin d'une ligne/phrase
    if end < len(text):
        newline_pos = text.find('\n', match_end, end + 100)
        if newline_pos != -1 and newline_pos < end + 100:
            end = newline_pos
    
    passage = text[start:end].strip()
    
    # Ajouter des indicateurs de troncature
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    
    return f"{prefix}{passage}{suffix}"


def search_recent_files(query: str, scope: str = "all", context_chars: int = DEFAULT_CONTEXT_CHARS) -> str:
    """
    Scan textuel des fichiers de conversation.
    
    PRINCIPE: Scanner n'est pas charger.
    - On lit les fichiers un par un
    - On cherche le pattern avec regex
    - On extrait SEULEMENT les passages pertinents
    - La fenêtre de contexte reste légère
    
    Args:
        query: Mots-clés à chercher (OBLIGATOIRE)
        scope: 'today' | 'week' | 'month' | 'year' | 'all' (défaut: 'all')
        context_chars: Caractères autour du match (défaut: 500)
    
    Returns:
        Passages pertinents formatés, ou message pour passer à Hermès
    """
    if not query or not query.strip():
        return "Erreur: query requis pour search_recent_files"
    
    query = query.strip()
    
    # Récupérer les fichiers selon la portée
    files = get_recent_files(scope)
    
    if not files:
        return f"Aucun fichier trouvé pour la portée '{scope}'. Passage à Hermès recommandé."
    
    # Préparer la recherche (insensible à la casse)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    
    results = []
    files_scanned = 0
    total_matches = 0
    
    for file_path in files:
        try:
            # Lecture du fichier (LECTURE SEULE)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            files_scanned += 1
            
            # Trouver tous les matches
            for match in pattern.finditer(content):
                total_matches += 1
                
                if len(results) >= MAX_RESULTS:
                    break
                
                # Extraire le contexte autour du match
                passage = extract_context(
                    content, 
                    match.start(), 
                    match.end(), 
                    context_chars
                )
                
                # Extraire la date du fichier
                date_str = file_path.stem[:10]
                
                results.append({
                    "date": date_str,
                    "file": file_path.name,
                    "passage": passage
                })
            
            if len(results) >= MAX_RESULTS:
                break
                
        except Exception as e:
            logger.error(f"Erreur lecture {file_path}: {e}")
            continue
    
    # Formater la sortie
    if not results:
        return f"Aucun résultat pour '{query}' dans les fichiers récents (scope: {scope}, {files_scanned} fichiers scannés). Passage à Hermès recommandé."
    
    output = [f"=== SCAN FICHIERS RÉCENTS : '{query}' ==="]
    output.append(f"Portée: {scope} | Fichiers: {files_scanned} | Matches: {total_matches}")
    output.append("")
    
    for i, result in enumerate(results, 1):
        output.append(f"--- [{result['date']}] {result['file']} ---")
        output.append(result['passage'])
        output.append("")
    
    if total_matches > MAX_RESULTS:
        output.append(f"[{total_matches - MAX_RESULTS} résultats supplémentaires non affichés]")
    
    return "\n".join(output)


# === POINT D'ENTRÉE POUR TESTS ===
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python search_recent_files.py <query> [scope]")
        print("Scopes: today, week, month, year, all")
        sys.exit(1)
    
    query = sys.argv[1]
    scope = sys.argv[2] if len(sys.argv) > 2 else "week"
    
    print(f"\n🔍 Recherche: '{query}' (scope: {scope})\n")
    result = search_recent_files(query, scope)
    print(result)
