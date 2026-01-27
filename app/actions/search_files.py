"""
search_files.py - Recherche textuelle unifiée dans les fichiers d'échanges
MOSS v0.10.4 - Session 62 - Fusion search_files + search_recent_files

Principe : Scan des fichiers .txt dans echanges/202X/ uniquement.
PAS d'accès à metadata.db — on cherche dans le texte brut.

Fonctionnalités :
- Support du wildcard * ("jerem*" → Jérémie, Jérémy, Jeremy)
- Filtrage par scope (today/week/month/year/all) OU par dates
- Contexte configurable autour des matches
- Résultats écrits dans scratch/search_results.json

Structure ciblée :
    ~/Dropbox/aiterego_memory/echanges/
    ├── 2023/
    ├── 2024/
    ├── 2025/
    └── 2026/
        └── MM/
            └── YYYY-MM-DDTHH-MM-SS.txt

Usage:
    from actions.search_files import search_files
    
    # Par scope (recommandé pour Iris)
    result = search_files(query="pipeline", scope="week")
    
    # Par dates exactes
    result = search_files(query="Stiegler", date_start="2025-01-01", date_end="2025-06-30")
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_DIR = MEMORY_DIR / "echanges"
SCRATCH_DIR = MEMORY_DIR / "scratch"
RESULTS_FILE = SCRATCH_DIR / "search_results.json"

# Années à scanner (dossiers autorisés)
ALLOWED_YEARS = ["2023", "2024", "2025", "2026"]

# S'assurer que le dossier scratch existe
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def _scope_to_dates(scope: str) -> tuple[Optional[str], Optional[str]]:
    """
    Convertit un scope en dates de début/fin.
    
    Args:
        scope: 'today' | 'week' | 'month' | 'year' | 'all'
    
    Returns:
        (date_start, date_end) au format YYYY-MM-DD, ou (None, None) pour 'all'
    """
    now = datetime.now()
    date_end = now.strftime("%Y-%m-%d")
    
    if scope == "today":
        date_start = date_end
    elif scope == "week":
        date_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    elif scope == "month":
        date_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    elif scope == "year":
        date_start = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    elif scope == "all":
        return None, None
    else:
        # Défaut: all
        return None, None
    
    return date_start, date_end


def search_files(
    query: str,
    scope: str = "all",
    days: Optional[int] = None,
    limit: int = 20,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    context_chars: int = 300
) -> Dict[str, Any]:
    """
    Recherche plein texte dans les fichiers .txt du dossier echanges/.
    
    Supporte le wildcard * pour des recherches flexibles :
    - "jerem*" → matche Jérémie, Jérémy, Jeremy, etc.
    - "post*human*" → matche posthumanisme, post-humanisme, etc.
    
    Filtrage temporel (mutuellement exclusif, par ordre de priorité) :
    1. date_start/date_end : dates exactes YYYY-MM-DD
    2. days : nombre de jours en arrière
    3. scope : 'today' | 'week' | 'month' | 'year' | 'all'
    
    Args:
        query: Mots-clés de recherche, supporte * comme wildcard (OBLIGATOIRE)
        scope: Portée temporelle ('today', 'week', 'month', 'year', 'all')
        days: Nombre de jours en arrière (alternative à scope)
        limit: Nombre max de résultats (défaut 20, max 100)
        date_start: Date début optionnelle (YYYY-MM-DD)
        date_end: Date fin optionnelle (YYYY-MM-DD)
        context_chars: Caractères de contexte autour du match (défaut 300)
    
    Returns:
        dict avec status, count, summary, et chemin du fichier résultats
    """
    
    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Le paramètre 'query' est obligatoire",
            "results_file": None
        }
    
    query = query.strip()
    limit = min(max(1, limit), 100)
    context_chars = min(max(100, context_chars), 1000)
    
    # Résoudre le filtrage temporel (priorité: dates > days > scope)
    if date_start or date_end:
        # Dates explicites fournies, on les utilise
        pass
    elif days is not None:
        # Nombre de jours fourni
        now = datetime.now()
        date_end = now.strftime("%Y-%m-%d")
        date_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    else:
        # Utiliser le scope
        date_start, date_end = _scope_to_dates(scope)
    
    try:
        # Collecter tous les fichiers .txt des années autorisées
        all_files = []
        for year in ALLOWED_YEARS:
            year_dir = ECHANGES_DIR / year
            if year_dir.exists():
                # Récursif dans les sous-dossiers (mois)
                for txt_file in year_dir.rglob("*.txt"):
                    all_files.append(txt_file)
        
        logger.info(f"[SEARCH_FILES] Scanning {len(all_files)} fichiers pour '{query}'")
        
        # Filtrer par date si spécifié
        if date_start or date_end:
            all_files = _filter_files_by_date(all_files, date_start, date_end)
            logger.info(f"[SEARCH_FILES] Après filtrage dates ({date_start} → {date_end}): {len(all_files)} fichiers")
        
        # Trier par date (plus récent d'abord pour le scan, on re-triera après)
        all_files.sort(key=lambda f: f.name, reverse=True)
        
        # Convertir la query en pattern regex (avec support wildcard)
        regex_pattern = _query_to_regex(query)
        logger.info(f"[SEARCH_FILES] Pattern regex: {regex_pattern}")
        
        # Chercher dans les fichiers
        results = []
        files_scanned = 0
        files_matched = 0
        
        for filepath in all_files:
            files_scanned += 1
            matches = _search_in_file(filepath, regex_pattern, context_chars)
            
            if matches:
                files_matched += 1
                for match in matches:
                    results.append(match)
                    if len(results) >= limit:
                        break
            
            if len(results) >= limit:
                break
        
        # Trier les résultats par date (plus ancien d'abord pour "première fois")
        results.sort(key=lambda r: r.get("timestamp", ""), reverse=False)
        
        # Construire le document de résultats
        search_doc = {
            "meta": {
                "query": query,
                "regex_pattern": regex_pattern,
                "scope": scope,
                "days": days,
                "limit": limit,
                "date_start": date_start,
                "date_end": date_end,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "files_scanned": files_scanned,
                "files_matched": files_matched,
                "total_found": len(results)
            },
            "results": results
        }
        
        # Écrire dans le fichier tampon
        RESULTS_FILE.write_text(
            json.dumps(search_doc, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        logger.info(f"[SEARCH_FILES] query='{query}' → {len(results)} résultats dans {files_matched} fichiers → {RESULTS_FILE}")
        
        # Construire le résumé pour Iris
        summary = _build_summary(query, results, files_scanned, files_matched, date_start, date_end, scope)
        
        return {
            "status": "success",
            "count": len(results),
            "files_scanned": files_scanned,
            "files_matched": files_matched,
            "scope": scope,
            "date_range": f"{date_start or 'début'} → {date_end or 'maintenant'}",
            "summary": summary,
            "results_file": str(RESULTS_FILE)
        }
        
    except Exception as e:
        logger.error(f"[SEARCH_FILES] Erreur: {e}")
        return {
            "status": "error",
            "error": f"Erreur: {str(e)}",
            "results_file": None
        }


def _build_summary(
    query: str,
    results: List[Dict],
    files_scanned: int,
    files_matched: int,
    date_start: Optional[str],
    date_end: Optional[str],
    scope: str
) -> str:
    """
    Construit le résumé textuel pour Iris.
    """
    if len(results) == 0:
        summary = f"Aucun résultat trouvé pour '{query}' dans {files_scanned} fichiers scannés"
        if date_start or date_end:
            summary += f" (période: {date_start or 'début'} → {date_end or 'maintenant'})"
        elif scope != "all":
            summary += f" (portée: {scope})"
        return summary
    
    summary = f"{len(results)} occurrence(s) trouvée(s) pour '{query}' dans {files_matched} fichier(s)\n"
    
    # Première occurrence (la plus ancienne)
    first = results[0]
    summary += f"\nPREMIÈRE MENTION : {first['date']} dans {first['filename']}\n"
    summary += f"Contexte : ...{first['context']}...\n"
    
    # Si plusieurs résultats, montrer aussi le plus récent
    if len(results) > 1:
        last = results[-1]
        summary += f"\nDERNIÈRE MENTION : {last['date']} dans {last['filename']}\n"
        summary += f"Contexte : ...{last['context']}...\n"
    
    if len(results) > 2:
        summary += f"\n({len(results) - 2} autres occurrences dans {RESULTS_FILE.name})"
    
    return summary


def _query_to_regex(query: str) -> str:
    """
    Convertit une query utilisateur en pattern regex.
    
    Supporte :
    - Wildcard * → .*
    - Échappement des caractères spéciaux regex
    - Case-insensitive (géré au niveau du compile)
    
    Exemples :
    - "jerem*" → "jerem.*"
    - "post*human*" → "post.*human.*"
    - "Alex Baker" → "Alex Baker" (recherche exacte)
    """
    # Séparer les wildcards du reste
    parts = query.split('*')
    
    # Échapper chaque partie (pour éviter les injections regex)
    escaped_parts = [re.escape(part) for part in parts]
    
    # Rejoindre avec .* (équivalent du wildcard)
    pattern = '.*'.join(escaped_parts)
    
    return pattern


def _search_in_file(filepath: Path, regex_pattern: str, context_chars: int) -> List[Dict]:
    """
    Cherche un pattern regex dans un fichier et retourne les matches avec contexte.
    """
    results = []
    
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        
        # Compiler le pattern (case-insensitive)
        pattern = re.compile(regex_pattern, re.IGNORECASE)
        
        for match in pattern.finditer(content):
            start = max(0, match.start() - context_chars)
            end = min(len(content), match.end() + context_chars)
            context = content[start:end].strip()
            
            # Nettoyer le contexte (enlever les retours à la ligne multiples)
            context = re.sub(r'\n{3,}', '\n\n', context)
            context = re.sub(r'[ \t]+', ' ', context)
            
            # Extraire la date du nom de fichier (format: YYYY-MM-DDTHH-MM-SS.txt)
            filename = filepath.name
            date_match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
            date_str = date_match.group(1) if date_match else "date inconnue"
            
            # Extraire le timestamp complet si possible
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})', filename)
            timestamp = ts_match.group(1).replace('T', ' ').replace('-', ':', 2) if ts_match else date_str
            
            # Capturer le texte exact qui a matché
            matched_text = match.group(0)
            
            results.append({
                "filename": filename,
                "filepath": str(filepath),
                "date": date_str,
                "timestamp": timestamp,
                "position": match.start(),
                "matched": matched_text,
                "context": context[:500]  # Limiter la taille du contexte
            })
    
    except Exception as e:
        logger.warning(f"[SEARCH_FILES] Erreur lecture {filepath}: {e}")
    
    return results


def _filter_files_by_date(files: List[Path], date_start: Optional[str], date_end: Optional[str]) -> List[Path]:
    """
    Filtre les fichiers par date basée sur leur nom.
    """
    filtered = []
    
    for f in files:
        # Extraire la date du nom de fichier
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', f.name)
        if not date_match:
            continue
        
        file_date = date_match.group(1)
        
        if date_start and file_date < date_start:
            continue
        if date_end and file_date > date_end:
            continue
        
        filtered.append(f)
    
    return filtered


def get_last_results() -> Dict[str, Any]:
    """
    Récupère les derniers résultats de recherche depuis le fichier tampon.
    """
    if not RESULTS_FILE.exists():
        return {
            "status": "error",
            "error": "Aucune recherche précédente. Utilise d'abord search_files."
        }
    
    try:
        content = RESULTS_FILE.read_text(encoding='utf-8')
        return {
            "status": "success",
            "data": json.loads(content)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lecture fichier: {str(e)}"
        }


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("SEARCH_FILES v0.10.4 - Test unifié")
    print("=" * 60)
    
    # Test 1: Scope week
    print("\n1. Recherche 'pipeline' (scope=week)...")
    result = search_files(query="pipeline", scope="week", limit=5)
    print(f"   Status: {result['status']}")
    print(f"   Count: {result.get('count', 0)}")
    print(f"   Scope: {result.get('scope')}")
    
    # Test 2: Scope all avec wildcard
    print("\n2. Recherche 'jerem*' (scope=all, wildcard)...")
    result = search_files(query="jerem*", scope="all", limit=5)
    print(f"   Status: {result['status']}")
    print(f"   Count: {result.get('count', 0)}")
    
    # Test 3: Par days
    print("\n3. Recherche 'Clio' (days=3)...")
    result = search_files(query="Clio", days=3, limit=5)
    print(f"   Status: {result['status']}")
    print(f"   Count: {result.get('count', 0)}")
    print(f"   Date range: {result.get('date_range')}")
    
    # Test 4: Par dates exactes
    print("\n4. Recherche 'Stiegler' (dates exactes)...")
    result = search_files(query="Stiegler", date_start="2025-01-01", date_end="2025-12-31", limit=5)
    print(f"   Status: {result['status']}")
    print(f"   Count: {result.get('count', 0)}")
    print(f"   Date range: {result.get('date_range')}")
    
    print("\n" + "=" * 60)
    print("Tests terminés!")
