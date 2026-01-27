"""
MOSS - Nettoyage des fichiers fusionnés
utils/nettoyer_fusionne.py

Nettoie les artefacts d'export et encapsule les blocs de code
pour éviter les erreurs JSON lors de l'extraction Gemini.

Usage:
    python -m app.utils.nettoyer_fusionne [--dry-run]

Historique:
    - Session 66: Première version (suppression artifacts)
    - Session 68: Ajout encapsulation code [CODE:lang:START/END]
"""

import re
from pathlib import Path
import argparse


def detecter_langage(code: str) -> str:
    """Détecte le langage d'un bloc de code"""
    code_lower = code.lower()
    
    # Python
    if any(x in code for x in ['import ', 'from ', 'def ', 'class ', 'print(', 'if __name__']):
        return 'python'
    
    # LaTeX
    if any(x in code for x in ['\\frac', '\\begin{', '\\end{', '$$', '\\alpha', '\\beta', '\\sum']):
        return 'latex'
    
    # HTML/XML
    if any(x in code_lower for x in ['<html', '<div', '<span', '</div>', '<!doctype']):
        return 'html'
    
    # SQL
    if any(x in code.upper() for x in ['SELECT ', 'FROM ', 'WHERE ', 'INSERT ', 'UPDATE ', 'CREATE TABLE']):
        return 'sql'
    
    # JavaScript/TypeScript
    if any(x in code for x in ['const ', 'let ', 'function ', '=>', 'console.log']):
        return 'javascript'
    
    # Bash/Shell
    if code.strip().startswith('#!') or any(x in code for x in ['echo ', '#!/bin/bash', 'sudo ', 'apt ']):
        return 'bash'
    
    # JSON
    if code.strip().startswith('{') and code.strip().endswith('}'):
        try:
            import json
            json.loads(code)
            return 'json'
        except:
            pass
    
    # Défaut
    return 'code'


def encapsuler_blocs_code(contenu: str) -> str:
    """
    Transforme les blocs [Code]... en [CODE:lang:START]...[CODE:lang:END]
    
    Détecte la fin d'un bloc de code par:
    - Une ligne vide suivie de [SOURCE:
    - Une ligne commençant par [SOURCE:
    - Fin de fichier
    """
    
    # Pattern pour trouver [Code] suivi du contenu jusqu'au prochain [SOURCE: ou fin
    pattern = r'\[Code\]\s*\n([\s\S]*?)(?=\n\[SOURCE:|$)'
    
    def remplacer(match):
        code_content = match.group(1).strip()
        if not code_content:
            return ''  # Bloc vide, on supprime
        
        langage = detecter_langage(code_content)
        return f'[CODE:{langage}:START]\n{code_content}\n[CODE:{langage}:END]'
    
    return re.sub(pattern, remplacer, contenu)


def nettoyer_fusionne(filepath: Path, dry_run: bool = False) -> dict:
    """
    Nettoie un fichier fusionné:
    1. Supprime les artefacts ChatGPT (turn0image0, citeturn0search*, search(...))
    2. Supprime les artefacts Claude (This block is not supported)
    3. Encapsule les blocs [Code] en [CODE:lang:START]...[CODE:lang:END]
    """
    
    contenu = filepath.read_text(encoding='utf-8')
    original_len = len(contenu)
    original_contenu = contenu
    
    # === ARTEFACTS CHATGPT ===
    
    # Références images/recherches: turn0image0, turn0search1, citeturn0search0, etc.
    contenu = re.sub(r'i?turn\d+(image|search)\d+', '', contenu)
    contenu = re.sub(r'cite(turn\d+search\d+)?', 'cite', contenu)  # citeturn0search0 -> cite
    
    # Blocs search("...") avec Unicode échappé - supprimer complètement
    contenu = re.sub(r'search\s*\(["\'][^"\']*\\u[0-9a-fA-F]{4}[^"\']*["\']\)\s*\n?', '', contenu)
    
    # === ARTEFACTS CLAUDE ===
    
    # Blocs artifacts non exportés
    contenu = re.sub(
        r'```\s*\n?\s*This block is not supported on your current device yet\.\s*\n?\s*```',
        '',
        contenu,
        flags=re.IGNORECASE
    )
    
    # === ENCAPSULATION CODE ===
    
    # Transformer [Code]... en [CODE:lang:START]...[CODE:lang:END]
    contenu = encapsuler_blocs_code(contenu)
    
    # === NETTOYAGE FINAL ===
    
    # Nettoyer lignes vides multiples
    contenu = re.sub(r'\n{3,}', '\n\n', contenu)
    
    # Statistiques
    result = {
        "modified": contenu != original_contenu,
        "original_len": original_len,
        "new_len": len(contenu),
        "saved": original_len - len(contenu)
    }
    
    # Écrire si modifié (et pas dry-run)
    if result["modified"] and not dry_run:
        filepath.write_text(contenu, encoding='utf-8')
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Nettoie les fichiers fusionnés MOSS')
    parser.add_argument('--dry-run', action='store_true', help='Simule sans modifier les fichiers')
    parser.add_argument('--path', type=str, default='~/Dropbox/aiterego_memory/echanges/exports/fusionne/',
                        help='Chemin vers le dossier fusionne/')
    args = parser.parse_args()
    
    fusionne_dir = Path(args.path).expanduser()
    
    if not fusionne_dir.exists():
        print(f"❌ Dossier non trouvé: {fusionne_dir}")
        return
    
    print(f"🧹 Nettoyage {'(DRY RUN) ' if args.dry_run else ''}de {fusionne_dir}")
    print("=" * 60)
    
    total_saved = 0
    files_modified = 0
    
    for f in sorted(fusionne_dir.glob("*.txt")):
        result = nettoyer_fusionne(f, dry_run=args.dry_run)
        if result["modified"]:
            status = "🔍" if args.dry_run else "✅"
            print(f"{status} {f.name} — {result['saved']:+d} chars")
            total_saved += result["saved"]
            files_modified += 1
    
    print("=" * 60)
    print(f"📊 {files_modified} fichiers {'à modifier' if args.dry_run else 'modifiés'}")
    print(f"💾 {total_saved:,} caractères {'économisables' if args.dry_run else 'supprimés'}")


if __name__ == '__main__':
    main()
