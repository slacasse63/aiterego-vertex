"""
MOSS - Nettoyage de texte temps réel
app/utils/nettoyer_text.py

Nettoie un segment de texte AVANT envoi à Gemini Extractor.
Utilisé par scribe.py pour les conversations en temps réel.

Usage:
    from app.utils.nettoyer_text import nettoyer_segment
    
    texte_propre = nettoyer_segment(texte_brut)

Historique:
    - Session 68: Création (séparé de nettoyer_fusionne.py)
"""

import re


def detecter_langage(code: str) -> str:
    """Détecte le langage d'un bloc de code."""
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
    - Une ligne vide suivie d'un texte normal
    - Double saut de ligne
    - Fin de texte
    """
    # Pattern pour [Code] suivi du contenu
    pattern = r'\[Code\]\s*\n([\s\S]*?)(?=\n\n[^\s\[]|\n\[|\Z)'
    
    def remplacer(match):
        code_content = match.group(1).strip()
        if not code_content:
            return ''  # Bloc vide, on supprime
        
        langage = detecter_langage(code_content)
        return f'[CODE:{langage}:START]\n{code_content}\n[CODE:{langage}:END]'
    
    return re.sub(pattern, remplacer, contenu)


def encapsuler_code_markdown(contenu: str) -> str:
    """
    Transforme les blocs ```langage ... ``` en [CODE:lang:START]...[CODE:lang:END]
    
    Gère les blocs de code Markdown courants dans les conversations.
    """
    # Pattern pour ```langage\n...\n```
    pattern = r'```(\w*)\n([\s\S]*?)```'
    
    def remplacer(match):
        lang_hint = match.group(1).lower() or 'code'
        code_content = match.group(2).strip()
        
        if not code_content:
            return ''
        
        # Utiliser le hint du markdown si présent, sinon détecter
        if lang_hint and lang_hint != 'code':
            langage = lang_hint
        else:
            langage = detecter_langage(code_content)
        
        return f'[CODE:{langage}:START]\n{code_content}\n[CODE:{langage}:END]'
    
    return re.sub(pattern, remplacer, contenu)


def nettoyer_segment(texte: str) -> str:
    """
    Nettoie un segment de texte pour l'extraction Gemini.
    
    Transformations:
    1. Encapsule les blocs [Code]... 
    2. Encapsule les blocs ```markdown```
    3. Nettoie les lignes vides multiples
    
    Args:
        texte: Texte brut du segment
        
    Returns:
        Texte nettoyé prêt pour Gemini Extractor
    """
    if not texte:
        return texte
    
    # 1. Encapsuler les blocs [Code]
    resultat = encapsuler_blocs_code(texte)
    
    # 2. Encapsuler les blocs markdown ```
    resultat = encapsuler_code_markdown(resultat)
    
    # 3. Nettoyer lignes vides multiples
    resultat = re.sub(r'\n{3,}', '\n\n', resultat)
    
    return resultat


# === TEST ===
if __name__ == '__main__':
    print("=" * 60)
    print("Test nettoyer_text.py")
    print("=" * 60)
    
    # Test 1: Bloc [Code]
    test1 = """Voici un script Python:
[Code]
def hello():
    print("Hello world")

Et voilà!"""
    
    print("\n1. Test [Code] Python:")
    print(f"   Avant: {repr(test1[:50])}")
    result1 = nettoyer_segment(test1)
    print(f"   Après: {repr(result1[:80])}")
    assert '[CODE:python:START]' in result1
    print("   ✅ OK")
    
    # Test 2: Bloc markdown
    test2 = """Voici du SQL:
```sql
SELECT * FROM users WHERE id = 1;
```
C'est tout."""
    
    print("\n2. Test ```sql```:")
    result2 = nettoyer_segment(test2)
    print(f"   Résultat: {repr(result2[:80])}")
    assert '[CODE:sql:START]' in result2
    print("   ✅ OK")
    
    # Test 3: LaTeX
    test3 = """La formule est:
[Code]
$$\\frac{a}{b} = c$$

Merci."""
    
    print("\n3. Test LaTeX:")
    result3 = nettoyer_segment(test3)
    assert '[CODE:latex:START]' in result3
    print("   ✅ OK")
    
    print("\n" + "=" * 60)
    print("✅ Tous les tests passés!")
