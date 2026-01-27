"""
inspect_failed_segments.py - Inspecter les segments avec confidence_score = 0.5
MOSS v0.10.3 - Session 69

Extrait et affiche le texte réel des segments échoués pour inspection manuelle.

Usage:
    python inspect_failed_segments.py --limit 10
    python inspect_failed_segments.py --all
    python inspect_failed_segments.py --output rapport.txt
"""

import sqlite3
import tiktoken
from pathlib import Path
import argparse

# Configuration
MEMORY_PATH = Path.home() / "Dropbox" / "aiterego_memory"
DB_PATH = MEMORY_PATH / "metadata.db"
ECHANGES_PATH = MEMORY_PATH / "echanges"

# Tokenizer
ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Compte les tokens d'un texte"""
    return len(ENCODER.encode(text))


def extract_segment_by_tokens(file_path: Path, token_start: int, token_end: int) -> dict:
    """
    Extrait un segment d'un fichier en comptant les tokens.
    
    Retourne:
        {
            "found": bool,
            "text": str,
            "actual_token_start": int,
            "actual_token_end": int,
            "context_before": str,  # 50 chars avant
            "context_after": str,   # 50 chars après
        }
    """
    if not file_path.exists():
        return {"found": False, "error": f"Fichier non trouvé: {file_path}"}
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return {"found": False, "error": f"Erreur lecture: {e}"}
    
    # Tokeniser tout le fichier
    tokens = ENCODER.encode(content)
    total_tokens = len(tokens)
    
    if token_start >= total_tokens:
        return {
            "found": False, 
            "error": f"token_start ({token_start}) >= total_tokens ({total_tokens})"
        }
    
    # Extraire les tokens du segment
    segment_tokens = tokens[token_start:token_end]
    segment_text = ENCODER.decode(segment_tokens)
    
    # Contexte avant (décode les 100 tokens avant)
    context_before_tokens = tokens[max(0, token_start - 100):token_start]
    context_before = ENCODER.decode(context_before_tokens)[-200:] if context_before_tokens else ""
    
    # Contexte après (décode les 100 tokens après)
    context_after_tokens = tokens[token_end:min(total_tokens, token_end + 100)]
    context_after = ENCODER.decode(context_after_tokens)[:200] if context_after_tokens else ""
    
    return {
        "found": True,
        "text": segment_text,
        "token_count": len(segment_tokens),
        "total_file_tokens": total_tokens,
        "context_before": context_before,
        "context_after": context_after
    }


def classify_content(text: str) -> str:
    """
    Classifie le contenu du segment.
    Retourne: "code", "json", "mixte", "texte", "court"
    """
    text_stripped = text.strip()
    
    if len(text_stripped) < 20:
        return "court"
    
    # Indicateurs de code/JSON
    code_indicators = [
        text_stripped.startswith('{') and text_stripped.endswith('}'),
        text_stripped.startswith('[') and text_stripped.endswith(']'),
        '```' in text,
        'def ' in text and ':' in text,
        'function ' in text,
        'import ' in text,
        'class ' in text and ':' in text,
        'curl ' in text.lower(),
        '"action":' in text,
        '"status":' in text,
    ]
    
    # Indicateurs de texte conversationnel
    text_indicators = [
        'je ' in text.lower(),
        'tu ' in text.lower(),
        'nous ' in text.lower(),
        'merci' in text.lower(),
        'bonjour' in text.lower(),
        '?' in text,
        '!' in text,
    ]
    
    code_score = sum(code_indicators)
    text_score = sum(text_indicators)
    
    if code_score > 2 and text_score > 2:
        return "mixte"
    elif code_score > 2:
        if text_stripped.startswith('{') or text_stripped.startswith('['):
            return "json"
        return "code"
    else:
        return "texte"


def main():
    parser = argparse.ArgumentParser(description="Inspecter les segments échoués")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Nombre de segments à inspecter")
    parser.add_argument("--all", "-a", action="store_true", help="Inspecter tous les segments")
    parser.add_argument("--output", "-o", type=str, help="Fichier de sortie (optionnel)")
    
    args = parser.parse_args()
    
    # Connexion DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Récupérer les segments échoués
    query = """
        SELECT id, timestamp, token_start, token_end, source_file, auteur
        FROM metadata 
        WHERE confidence_score = 0.5
        ORDER BY source_file, token_start
    """
    if not args.all:
        query += f" LIMIT {args.limit}"
    
    cursor.execute(query)
    segments = cursor.fetchall()
    
    print(f"\n{'='*80}")
    print(f"🔍 INSPECTION DES SEGMENTS ÉCHOUÉS")
    print(f"{'='*80}")
    print(f"📊 {len(segments)} segments à inspecter\n")
    
    # Stats
    stats = {"code": 0, "json": 0, "mixte": 0, "texte": 0, "court": 0, "erreur": 0}
    
    output_lines = []
    
    for i, seg in enumerate(segments, 1):
        seg_id = seg['id']
        token_start = seg['token_start']
        token_end = seg['token_end']
        source_file = seg['source_file']
        auteur = seg['auteur']
        
        # Construire le chemin
        file_path = ECHANGES_PATH / source_file.replace("echanges/", "")
        
        # Extraire le segment
        result = extract_segment_by_tokens(file_path, token_start, token_end)
        
        # Affichage
        header = f"\n[{i}/{len(segments)}] ID {seg_id} | {source_file}"
        print(header)
        output_lines.append(header)
        
        print(f"    Token: {token_start} → {token_end} | Auteur: {auteur}")
        output_lines.append(f"    Token: {token_start} → {token_end} | Auteur: {auteur}")
        
        if not result.get("found"):
            error_msg = f"    ❌ ERREUR: {result.get('error')}"
            print(error_msg)
            output_lines.append(error_msg)
            stats["erreur"] += 1
            continue
        
        # Classifier
        classification = classify_content(result["text"])
        stats[classification] += 1
        
        class_line = f"    📋 Classification: {classification.upper()} ({result['token_count']} tokens)"
        print(class_line)
        output_lines.append(class_line)
        
        # Afficher le texte (tronqué)
        text_preview = result["text"][:500].replace('\n', ' ↵ ')
        if len(result["text"]) > 500:
            text_preview += "..."
        
        text_line = f"    📝 Texte: {text_preview}"
        print(text_line)
        output_lines.append(text_line)
        
        # Contexte si mixte ou texte
        if classification in ["mixte", "texte"]:
            ctx_before = result["context_before"][-100:].replace('\n', ' ↵ ')
            ctx_after = result["context_after"][:100].replace('\n', ' ↵ ')
            print(f"    ⬆️  Avant: ...{ctx_before}")
            print(f"    ⬇️  Après: {ctx_after}...")
            output_lines.append(f"    ⬆️  Avant: ...{ctx_before}")
            output_lines.append(f"    ⬇️  Après: {ctx_after}...")
    
    # Résumé
    print(f"\n{'='*80}")
    print(f"📊 RÉSUMÉ")
    print(f"{'='*80}")
    for cat, count in stats.items():
        pct = count / len(segments) * 100 if segments else 0
        print(f"   {cat.upper():8} : {count:3} ({pct:.1f}%)")
    
    # Sauvegarder si demandé
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        print(f"\n💾 Rapport sauvegardé: {args.output}")
    
    conn.close()


if __name__ == "__main__":
    main()
