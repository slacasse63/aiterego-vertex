"""
Fusion et dédoublonnage d'exports Claude

Lit plusieurs fichiers JSON d'export Claude et produit un fichier unique
sans doublons (basé sur l'UUID des messages).

Usage:
    python merge_claude_exports.py fichier1.json fichier2.json fichier3.json -o merged.json
    python merge_claude_exports.py *.json -o merged.json --dry-run
"""

import json
import argparse
from pathlib import Path
from collections import OrderedDict


def merge_exports(input_files: list, output_file: Path, dry_run: bool = False) -> dict:
    """
    Fusionne plusieurs exports Claude en un seul fichier sans doublons.
    
    La déduplication se fait sur:
    1. UUID de conversation (niveau conversation)
    2. UUID de message (niveau message)
    
    Args:
        input_files: Liste des fichiers JSON à fusionner
        output_file: Fichier de sortie
        dry_run: Si True, analyse seulement sans écrire
    
    Returns:
        Dict avec statistiques
    """
    print(f"\n{'='*60}")
    print(f"🔀 FUSION EXPORTS CLAUDE")
    print(f"{'='*60}")
    
    stats = {
        "files_read": 0,
        "conversations_total": 0,
        "conversations_unique": 0,
        "conversations_duplicates": 0,
        "messages_total": 0,
        "messages_unique": 0,
        "messages_duplicates": 0,
    }
    
    # Dictionnaire ordonné pour garder l'ordre chronologique
    # Clé = UUID conversation, Valeur = conversation complète
    all_conversations = OrderedDict()
    
    # Set pour tracker les UUIDs de messages vus
    seen_message_uuids = set()
    
    for input_path in input_files:
        input_path = Path(input_path)
        if not input_path.exists():
            print(f"   ⚠️ Fichier non trouvé: {input_path}")
            continue
        
        print(f"\n📂 Lecture: {input_path.name}")
        
        with open(input_path, 'r', encoding='utf-8') as f:
            conversations = json.load(f)
        
        stats["files_read"] += 1
        print(f"   📊 {len(conversations)} conversations")
        
        for conv in conversations:
            conv_uuid = conv.get("uuid", "")
            stats["conversations_total"] += 1
            
            if conv_uuid in all_conversations:
                # Conversation existe déjà - fusionner les messages
                stats["conversations_duplicates"] += 1
                existing_conv = all_conversations[conv_uuid]
                existing_messages = existing_conv.get("chat_messages", [])
                new_messages = conv.get("chat_messages", [])
                
                # Ajouter les messages non-vus
                for msg in new_messages:
                    msg_uuid = msg.get("uuid", "")
                    stats["messages_total"] += 1
                    
                    if msg_uuid and msg_uuid not in seen_message_uuids:
                        existing_messages.append(msg)
                        seen_message_uuids.add(msg_uuid)
                        stats["messages_unique"] += 1
                    else:
                        stats["messages_duplicates"] += 1
                
                # Mettre à jour si la conversation fusionnée a un updated_at plus récent
                if conv.get("updated_at", "") > existing_conv.get("updated_at", ""):
                    existing_conv["updated_at"] = conv["updated_at"]
                    existing_conv["summary"] = conv.get("summary", existing_conv.get("summary"))
            else:
                # Nouvelle conversation
                stats["conversations_unique"] += 1
                all_conversations[conv_uuid] = conv
                
                # Tracker tous les messages
                for msg in conv.get("chat_messages", []):
                    msg_uuid = msg.get("uuid", "")
                    stats["messages_total"] += 1
                    
                    if msg_uuid:
                        if msg_uuid not in seen_message_uuids:
                            seen_message_uuids.add(msg_uuid)
                            stats["messages_unique"] += 1
                        else:
                            stats["messages_duplicates"] += 1
                    else:
                        stats["messages_unique"] += 1
    
    # Trier par date de création
    sorted_conversations = sorted(
        all_conversations.values(),
        key=lambda c: c.get("created_at", "")
    )
    
    print(f"\n{'='*60}")
    print(f"📊 STATISTIQUES:")
    print(f"   Fichiers lus:              {stats['files_read']}")
    print(f"   Conversations totales:     {stats['conversations_total']}")
    print(f"   Conversations uniques:     {stats['conversations_unique']}")
    print(f"   Conversations doublons:    {stats['conversations_duplicates']}")
    print(f"   Messages totaux:           {stats['messages_total']}")
    print(f"   Messages uniques:          {stats['messages_unique']}")
    print(f"   Messages doublons:         {stats['messages_duplicates']}")
    print(f"{'='*60}")
    
    if dry_run:
        print(f"\n🔍 MODE DRY-RUN - pas d'écriture")
    else:
        print(f"\n📝 Écriture: {output_file}")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(sorted_conversations, f, ensure_ascii=False, indent=2)
        print(f"   ✅ {len(sorted_conversations)} conversations sauvegardées")
    
    print(f"\n{'='*60}")
    print(f"✅ TERMINÉ!")
    print(f"{'='*60}")
    
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fusionne plusieurs exports Claude en un seul fichier dédoublonné"
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Fichiers JSON d'export Claude à fusionner"
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Fichier de sortie"
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Analyser sans écrire"
    )
    
    args = parser.parse_args()
    
    merge_exports(
        input_files=args.inputs,
        output_file=Path(args.output),
        dry_run=args.dry_run
    )