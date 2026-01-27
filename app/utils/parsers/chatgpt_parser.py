"""
ChatGPT Parser - Extracteur d'exports OpenAI pour le Scribe Rétroactif

Lit les fichiers JSON d'export ChatGPT et génère des fichiers .txt par jour MOSS.
Le format de sortie est compatible avec le Scribe existant.

Usage:
    python chatgpt_parser.py chemin/vers/conversations.json
    python chatgpt_parser.py chemin/vers/conversations.json --output /chemin/sortie
    python chatgpt_parser.py chemin/vers/conversations.json --after 2025-12-11T13:50:31

Jour MOSS: 08:00:01 UTC → 08:00:00 UTC le lendemain (03:00 heure Québec)

Particularités ChatGPT:
- Timestamps en format Unix (secondes depuis epoch)
- Structure en arbre (mapping avec parent/children)
- Messages système à filtrer (is_visually_hidden_from_conversation)
"""

import json
import re
import sys
sys.setrecursionlimit(10000)
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Optional, Any


# === CONFIGURATION ===
MOSS_DAY_START_HOUR_UTC = 8  # 08:00 UTC = 03:00 Québec


# === NETTOYAGE DES ARTEFACTS ===
def nettoyer_artefacts_chatgpt(texte: str) -> str:
    """
    Supprime les artefacts d'export ChatGPT.
    
    Artefacts supprimés:
    - turn0image0, turn0search1, etc. (références images/recherches)
    - Blocs [Code] avec contenu échappé Unicode (appels de fonction)
    """
    if not texte:
        return texte
    
    # 1. Références images/recherches (turn0image0, turn0search1, iturn0image0, etc.)
    texte = re.sub(r'i?turn\d+(image|search)\d+', '', texte)
    
    # 2. Blocs [Code] avec contenu échappé Unicode (appels de fonction ChatGPT)
    # Pattern: [Code]\n suivi d'une ligne contenant \uXXXX
    texte = re.sub(r'\[Code\]\s*\n[^\n]*\\u[0-9a-fA-F]{4}[^\n]*\n?', '', texte)
    
    # 3. Nettoyer les lignes vides multiples résultantes
    texte = re.sub(r'\n{3,}', '\n\n', texte)
    
    return texte.strip()


def unix_to_iso(unix_ts: float) -> str:
    """Convertit un timestamp Unix en ISO 8601."""
    if unix_ts is None:
        return ""
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def unix_to_datetime(unix_ts: float) -> Optional[datetime]:
    """Convertit un timestamp Unix en datetime UTC."""
    if unix_ts is None:
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc)


def get_moss_day(unix_ts: float) -> str:
    """
    Détermine le 'jour MOSS' pour un timestamp Unix donné.
    
    Règle: Le jour MOSS commence à 08:00:01 UTC et se termine à 08:00:00 UTC le lendemain.
    """
    if unix_ts is None:
        return "unknown"
    
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    
    # Si avant 08:00 UTC, c'est encore le jour précédent
    if dt.hour < MOSS_DAY_START_HOUR_UTC:
        dt = dt - timedelta(days=1)
    
    return dt.strftime("%Y-%m-%d")


def reconstruct_conversation_order(mapping: Dict[str, Any]) -> List[Dict]:
    """
    Reconstruit l'ordre linéaire des messages à partir de la structure en arbre.
    
    ChatGPT stocke les messages dans un "mapping" avec parent/children.
    On doit parcourir l'arbre pour obtenir l'ordre chronologique.
    """
    if not mapping:
        return []
    
    # Trouver la racine (message sans parent ou parent null)
    root_id = None
    for msg_id, node in mapping.items():
        if node.get("parent") is None:
            root_id = msg_id
            break
    
    if not root_id:
        # Fallback: prendre le premier
        root_id = list(mapping.keys())[0]
    
    # Parcours en profondeur pour reconstruire l'ordre
    messages = []
    visited = set()
    
    def traverse(node_id: str):
        if node_id in visited or node_id not in mapping:
            return
        visited.add(node_id)
        
        node = mapping[node_id]
        message = node.get("message")
        
        if message:
            # Vérifier si le message doit être affiché
            metadata = message.get("metadata", {})
            if not metadata.get("is_visually_hidden_from_conversation", False):
                messages.append(message)
        
        # Parcourir les enfants
        children = node.get("children", [])
        for child_id in children:
            traverse(child_id)
    
    traverse(root_id)
    
    # Trier par create_time si disponible
    messages.sort(key=lambda m: m.get("create_time") or 0)
    
    return messages


def extract_text_from_content(content: Dict) -> str:
    """Extrait le texte du contenu d'un message ChatGPT."""
    if not content:
        return ""
    
    content_type = content.get("content_type", "")
    
    if content_type == "text":
        parts = content.get("parts", [])
        text = "\n".join(str(p) for p in parts if p)
        # Nettoyer les artefacts
        return nettoyer_artefacts_chatgpt(text)
    
    elif content_type == "user_editable_context":
        # C'est le profil utilisateur, on l'ignore
        return ""
    
    elif content_type == "code":
        # Code exécuté - on le garde mais nettoyé
        code = content.get("text", "")
        # Ne pas inclure les blocs [Code] avec Unicode échappé
        if code and '\\u' in code:
            return ""  # Supprimer complètement les appels de fonction
        return f"[Code]\n{code}" if code else ""
    
    elif content_type == "execution_output":
        # Résultat d'exécution
        output = content.get("text", "")
        return f"[Output]\n{output}" if output else ""
    
    else:
        # Autres types: tenter d'extraire parts
        parts = content.get("parts", [])
        if parts:
            text = "\n".join(str(p) for p in parts if p)
            return nettoyer_artefacts_chatgpt(text)
        return ""


def format_message(msg: Dict) -> tuple:
    """
    Formate un message ChatGPT au format attendu par le Scribe.
    
    Returns:
        tuple: (timestamp_unix, formatted_string) ou (None, "") si invalide
    """
    author = msg.get("author", {})
    role = author.get("role", "")
    content = msg.get("content", {})
    create_time = msg.get("create_time")
    
    # Ignorer les messages système
    if role == "system":
        return None, ""
    
    # Extraire le texte
    text = extract_text_from_content(content)
    if not text or not text.strip():
        return None, ""
    
    # Normaliser le rôle
    if role == "user":
        sender = "human"
    elif role == "assistant":
        sender = "assistant"
    else:
        return None, ""
    
    # Convertir le timestamp
    if create_time:
        iso_timestamp = unix_to_iso(create_time)
    else:
        return None, ""
    
    formatted = f"[{iso_timestamp}] {sender}:\n{text.strip()}\n"
    return create_time, formatted


def parse_chatgpt_export(
    input_path: Path,
    output_dir: Path,
    after_timestamp: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Parse un export ChatGPT et génère des fichiers .txt par jour MOSS.
    
    Args:
        input_path: Chemin vers le fichier JSON d'export
        output_dir: Dossier de sortie pour les fichiers .txt
        after_timestamp: Ne traiter que les messages après ce timestamp (ISO ou Unix)
        dry_run: Si True, n'écrit pas les fichiers (juste analyse)
    
    Returns:
        Dict avec statistiques {jour: nb_messages}
    """
    print(f"\n{'='*60}")
    print(f"📖 CHATGPT PARSER (avec nettoyage artefacts)")
    print(f"{'='*60}")
    print(f"📂 Input:  {input_path}")
    print(f"📂 Output: {output_dir}")
    
    # Parser le timestamp de référence si fourni
    after_unix = None
    if after_timestamp:
        print(f"⏭️  Skip:   messages ≤ {after_timestamp}")
        # Gérer les deux formats
        if 'T' in after_timestamp:
            # Format ISO
            ts = after_timestamp.replace('Z', '+00:00')
            dt = datetime.fromisoformat(ts)
            after_unix = dt.timestamp()
        else:
            # Format Unix
            after_unix = float(after_timestamp)
    
    # Charger le JSON
    print(f"\n📄 Chargement du JSON...")
    with open(input_path, 'r', encoding='utf-8') as f:
        conversations = json.load(f)
    
    print(f"   {len(conversations)} conversations trouvées")
    
    # Grouper les messages par jour MOSS
    days: Dict[str, List[tuple]] = defaultdict(list)
    
    stats = {
        "conversations": 0,
        "messages_total": 0,
        "messages_skipped": 0,
        "messages_processed": 0,
    }
    
    for conv in conversations:
        title = conv.get("title", "Sans titre")
        conv_create_time = conv.get("create_time", 0)
        mapping = conv.get("mapping", {})
        
        if not mapping:
            continue
        
        stats["conversations"] += 1
        
        # Reconstruire l'ordre des messages
        messages = reconstruct_conversation_order(mapping)
        
        conv_messages = []
        
        for msg in messages:
            stats["messages_total"] += 1
            create_time = msg.get("create_time")
            
            if not create_time:
                continue
            
            # Vérifier si on doit skip ce message
            if after_unix and create_time <= after_unix:
                stats["messages_skipped"] += 1
                continue
            
            ts, formatted = format_message(msg)
            if ts and formatted:
                conv_messages.append((ts, formatted))
                stats["messages_processed"] += 1
        
        # Ajouter les messages de cette conversation aux jours appropriés
        if conv_messages:
            # Grouper les messages de cette conv par jour
            conv_by_day = defaultdict(list)
            for ts, msg in conv_messages:
                day = get_moss_day(ts)
                conv_by_day[day].append((ts, msg))
            
            # Créer un ID court pour la conversation
            conv_id = str(hash(title))[-8:]
            
            # Ajouter à chaque jour avec header
            for day, day_msgs in conv_by_day.items():
                header = f"\n{'='*50}\n=== Conversation: {title} ({conv_id}) ===\n{'='*50}\n\n"
                days[day].append((day_msgs[0][0], header, True))
                for ts, msg in day_msgs:
                    days[day].append((ts, msg, False))
    
    print(f"\n📊 Statistiques:")
    print(f"   Conversations:      {stats['conversations']}")
    print(f"   Messages total:     {stats['messages_total']}")
    print(f"   Messages skipped:   {stats['messages_skipped']}")
    print(f"   Messages traités:   {stats['messages_processed']}")
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
    
    parser = argparse.ArgumentParser(description="Parse ChatGPT exports to daily MOSS files")
    parser.add_argument("input", help="Chemin vers le fichier JSON d'export ChatGPT")
    parser.add_argument("--output", "-o", help="Dossier de sortie (défaut: même dossier que input, sans /sources)")
    parser.add_argument("--after", "-a", help="Ne traiter que les messages après ce timestamp (ISO ou Unix)")
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
        # Par défaut: dossier parent de sources/ (ex: exports/chatgpt/)
        if input_path.parent.name == "sources":
            output_dir = input_path.parent.parent
        else:
            output_dir = input_path.parent
    
    # Lancer le parsing
    parse_chatgpt_export(
        input_path=input_path,
        output_dir=output_dir,
        after_timestamp=args.after,
        dry_run=args.dry_run
    )
