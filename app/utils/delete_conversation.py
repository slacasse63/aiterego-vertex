#!/usr/bin/env python3
"""
Outil simple pour supprimer des conversations de conversations_serge.json
Usage: python delete_conversation.py
"""

import json
import sys
from pathlib import Path

# === CHEMIN FIXE ===
FILEPATH = Path.home() / "Dropbox" / "aiterego_memory" / "echanges" / "exports" / "chatgpt" / "sources" / "conversations_serge.json"

def main():
    if not FILEPATH.exists():
        print(f"❌ Fichier introuvable: {FILEPATH}")
        sys.exit(1)
    
    print(f"📂 Chargement de {FILEPATH.name}...")
    print("   (peut prendre quelques secondes pour un gros fichier)")
    
    with open(FILEPATH, 'r', encoding='utf-8') as f:
        conversations = json.load(f)
    
    print(f"✅ {len(conversations)} conversations chargées\n")
    print("=" * 50)
    print("SUPPRESSION DE CONVERSATIONS")
    print("=" * 50)
    print("Colle un titre et appuie sur Entrée pour supprimer.")
    print("Tape 'liste' pour voir les 20 premiers titres.")
    print("Tape 'cherche mot' pour chercher dans les titres.")
    print("Tape 'quit' pour sauvegarder et quitter.")
    print("=" * 50)
    
    deleted_count = 0
    modified = False
    
    while True:
        try:
            user_input = input("\n🎯 Titre à supprimer: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break
        
        if not user_input:
            continue
        
        # Commande: quitter
        if user_input.lower() in ['quit', 'q', 'exit']:
            break
        
        # Commande: lister
        if user_input.lower() == 'liste':
            print("\n📋 20 premiers titres:")
            for i, conv in enumerate(conversations[:20]):
                title = conv.get('title', '(sans titre)')
                print(f"   {i+1}. {title}")
            continue
        
        # Commande: chercher
        if user_input.lower().startswith('cherche '):
            search_term = user_input[8:].lower()
            print(f"\n🔍 Recherche '{search_term}':")
            found = 0
            for conv in conversations:
                title = conv.get('title', '')
                if title and search_term in title.lower():
                    print(f"   • {title}")
                    found += 1
                    if found >= 20:
                        print("   ... (limité à 20 résultats)")
                        break
            if found == 0:
                print("   Aucun résultat")
            continue
        
        # Décoder les séquences Unicode (ex: \u00e9 → é)
        try:
            user_input_decoded = user_input.encode('utf-8').decode('unicode_escape')
        except:
            user_input_decoded = user_input
        
        # Supprimer par titre (essayer les deux versions)
        initial_count = len(conversations)
        conversations = [c for c in conversations if c.get('title') not in [user_input, user_input_decoded]]
        
        if len(conversations) < initial_count:
            deleted_count += 1
            modified = True
            print(f"✅ Supprimé: \"{user_input_decoded}\"")
            print(f"   ({len(conversations)} conversations restantes)")
        else:
            # Essayer recherche partielle
            search_term = user_input_decoded.lower()
            matches = [c for c in conversations if search_term in (c.get('title') or '').lower()]
            if matches:
                print(f"❌ Titre exact non trouvé. Suggestions:")
                for m in matches[:5]:
                    print(f"   • {m.get('title')}")
            else:
                print(f"❌ Aucune conversation avec ce titre")
    
    # Sauvegarder si modifié
    if modified:
        # Backup
        backup_path = FILEPATH.with_suffix('.backup.json')
        print(f"\n💾 Sauvegarde backup: {backup_path.name}")
        with open(FILEPATH, 'r', encoding='utf-8') as f:
            backup_content = f.read()
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(backup_content)
        
        # Écrire le fichier nettoyé
        print(f"💾 Sauvegarde: {FILEPATH.name}")
        with open(FILEPATH, 'w', encoding='utf-8') as f:
            json.dump(conversations, f, ensure_ascii=False, indent=2)
        
        print(f"\n🎉 Terminé! {deleted_count} conversation(s) supprimée(s)")
    else:
        print("\n👋 Aucune modification.")

if __name__ == "__main__":
    main()