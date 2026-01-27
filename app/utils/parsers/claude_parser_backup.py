"""
Claude Parser - Extracteur d'exports Anthropic pour le Scribe Rétroactif

Lit les fichiers JSON d'export Claude et génère des fichiers .txt par jour MOSS.
Le format de sortie est compatible avec le Scribe existant.

Usage:
    python claude_parser.py chemin/vers/export.json
    python claude_parser.py chemin/vers/export.json --output /chemin/sortie
    python claude_parser.py chemin/vers/export.json --after 2025-12-11T13:50:31

Jour MOSS: 08:00:01 UTC → 08:00:00 UTC le lendemain (03:00 heure Québec)
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Optional


# === CONFIGURATION ===
MOSS_DAY_START_HOUR_UTC = 8  # 08:00 UTC = 03:00 Québec


# === NETTOYAGE DES ARTEFACTS ===
def nettoyer_artefacts_claude(texte: str) -> str:
    """
    Supprime les artefacts d'export Claude.
    
    Artefacts supprimés:
    - Blocs "This block is not supported on your current device yet."
      (artifacts non exportés: code, JSON, fichiers générés)
    """
    if not texte:
        return texte
    
    # Blocs artifacts non exportés (entre triple backticks)
    texte = re.sub(
        r'```\s*\n?\s*This block is not supported on your current device yet\.\s*\n?\s*```',
        '',
        texte,
        flags=re.IGNORECASE
    )
    
    # Nettoyer les lignes vides multiples résultantes
    texte = re.sub(r'\n{3,}', '\n\n', texte)
    
    return texte.strip()


def get_moss_day(timestamp_str: str) -> str:
    """
    Détermine le 'jour MOSS' pour un timestamp donné.
    
    Règle: Le jour MOSS commence à 08:00:01 UTC et se termine à 08:00:00 UTC le lendemain.
    Donc tout ce qui est entre 00:00 et 08:00 UTC appartient au jour PRÉCÉDENT.
    
    Args:
        timestamp_str: Timestamp ISO (ex: "2025-12-13T19:19:41.631003Z")
    
    Returns:
        Date au format YYYY-MM-DD
    """
    # Parser le timestamp
    ts = timestamp_str.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        # Fallback si format différent
        dt = datetime.strptime(timestamp_str[:19], "%Y-%m-%dT%H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Si avant 08:00 UTC, c'est encore le jour précédent
    if dt.hour < MOSS_DAY_START_HOUR_UTC:
        dt = dt - timedelta(days=1)
    
    return dt.strftime("%Y-%m-%d")


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse un timestamp ISO en datetime UTC."""
    ts = timestamp_str.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        dt = datetime.strptime(timestamp_str[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)


def format_message(msg: dict) -> str:
    """
    Formate un message Claude au format attendu par le Scribe.
    
    Format: [TIMESTAMP] sender:\ntext\n
    """
    sender = msg.get("sender", "human")
    text = msg.get("text", "").strip()
    created_at = msg.get("created_at", "")
    
    if not text or not created_at:
        return ""
    
    # Nettoyer les artefacts Claude
    text = nettoyer_artefacts_claude(text)
    
    # Si le texte est vide après nettoyage, ignorer
    if not text.strip():
        return ""
    
    # Normaliser le sender
    if sender.lower() in ["human", "user"]:
        sender = "human"
    else:
        sender = "assistant"
    
    return f"[{created_at}] {sender}:\n{text}\n"


def parse_claude_export(
    input_path: Path,
    output_dir: Path,
    after_timestamp: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Parse un export Claude et génère des fichiers .txt par jour MOSS.
    
    Args:
        input_path: Chemin vers le fichier JSON d'export
        output_dir: Dossier de sortie pour les fichiers .txt
        after_timestamp: Ne traiter que les messages après ce timestamp (optionnel)
        dry_run: Si True, n'écrit pas les fichiers (juste analyse)
    
    Returns:
        Dict avec statistiques {jour: nb_messages}
    """
    print(f"\n{'='*60}")
    print(f"📖 CLAUDE PARSER (avec nettoyage artefacts)")
    print(f"{'='*60}")
    print(f"📂 Input:  {input_path}")
    print(f"📂 Output: {output_dir}")
    
    if after_timestamp:
        print(f"⏭️  Skip:   messages ≤ {after_timestamp}")
    
    # Charger le JSON
    print(f"\n📄 Chargement du JSON...")
    with open(input_path, 'r', encoding='utf-8') as f:
        conversations = json.load(f)
    
    print(f"   {len(conversations)} conversations trouvées")
    
    # Parser le timestamp de référence si fourni
    after_dt = None
    if after_timestamp:
        after_dt = parse_timestamp(after_timestamp)
    
    # Grouper les messages par jour MOSS
    days: Dict[str, List[tuple]] = defaultdict(list)  # {jour: [(timestamp, formatted_msg, conv_name)]}
    
    stats = {
        "conversations": 0,
        "messages_total": 0,
        "messages_skipped": 0,
        "messages_processed": 0,
        "artefacts_removed": 0,
    }
    
    for conv in conversations:
        conv_name = conv.get("name", "Sans titre")
        conv_uuid = conv.get("uuid", "")[:8]
        messages = conv.get("chat_messages", [])
        
        if not messages:
            continue
        
        stats["conversations"] += 1
        conv_messages = []
        
        for msg in messages:
            stats["messages_total"] += 1
            created_at = msg.get("created_at", "")
            
            if not created_at:
                continue
            
            # Vérifier si on doit skip ce message
            if after_dt:
                msg_dt = parse_timestamp(created_at)
                if msg_dt <= after_dt:
                    stats["messages_skipped"] += 1
                    continue
            
            # Compter les artefacts avant nettoyage
            original_text = msg.get("text", "")
            if "This block is not supported" in original_text:
                stats["artefacts_removed"] += original_text.count("This block is not supported")
            
            formatted = format_message(msg)
            if formatted:
                moss_day = get_moss_day(created_at)
                conv_messages.append((created_at, formatted))
                stats["messages_processed"] += 1
        
        # Ajouter les messages de cette conversation aux jours appropriés
        # avec un header de conversation
        if conv_messages:
            # Grouper les messages de cette conv par jour
            conv_by_day = defaultdict(list)
            for ts, msg in conv_messages:
                day = get_moss_day(ts)
                conv_by_day[day].append((ts, msg))
            
            # Ajouter à chaque jour avec header
            for day, day_msgs in conv_by_day.items():
                header = f"\n{'='*50}\n=== Conversation: {conv_name} ({conv_uuid}) ===\n{'='*50}\n\n"
                days[day].append((day_msgs[0][0], header, True))  # True = is_header
                for ts, msg in day_msgs:
                    days[day].append((ts, msg, False))
    
    print(f"\n📊 Statistiques:")
    print(f"   Conversations:      {stats['conversations']}")
    print(f"   Messages total:     {stats['messages_total']}")
    print(f"   Messages skipped:   {stats['messages_skipped']}")
    print(f"   Messages traités:   {stats['messages_processed']}")
    print(f"   Artefacts supprimés: {stats['artefacts_removed']}")
    print(f"   Jours MOSS:         {len(days)}")
    
    # Écrire les fichiers
    if dry_run:
        print(f"\n📝 Mode DRY RUN - pas d'écriture")
    else:
        print(f"\n📝 Écriture des fichiers...")
        output_dir.mkdir(parents=True, exist_ok=True)
    
    day_stats = {}
    for day in sorted(days.keys()):
        entries = days[day]
        # Trier par timestamp
        entries.sort(key=lambda x: x[0])
        
        # Compter les vrais messages (pas les headers)
        msg_count = sum(1 for e in entries if not e[2])
        day_stats[day] = msg_count
        
        if not dry_run:
            output_file = output_dir / f"{day}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                for _, content, _ in entries:
                    f.write(content)
            print(f"   ✅ {day}.txt ({msg_count} messages)")
        else:
            print(f"   📄 {day}.txt ({msg_count} messages)")
    
    print(f"\n{'='*60}")
    print(f"✅ Terminé!")
    print(f"{'='*60}")
    
    return day_stats


# === POINT D'ENTRÉE ===
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Parse Claude exports to daily MOSS files")
    parser.add_argument("input", help="Chemin vers le fichier JSON d'export Claude")
    parser.add_argument("--output", "-o", help="Dossier de sortie (défaut: même dossier que input, sans /sources)")
    parser.add_argument("--after", "-a", help="Ne traiter que les messages après ce timestamp")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Analyser sans écrire")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    
    if not input_path.exists():
        print(f"❌ Fichier non trouvé: {input_path}")
        sys.exit(1)
    
    # Déterminer le dossier de sortie
    if args.output:
        output_dir = Path(args.output)
    else:
        # Par défaut: dossier parent de sources/ (ex: exports/claude/)
        if input_path.parent.name == "sources":
            output_dir = input_path.parent.parent
        else:
            output_dir = input_path.parent
    
    # Lancer le parsing
    parse_claude_export(
        input_path=input_path,
        output_dir=output_dir,
        after_timestamp=args.after,
        dry_run=args.dry_run
    )
