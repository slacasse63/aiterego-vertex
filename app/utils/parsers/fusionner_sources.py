"""
MOSS - Fusion des sources d'exports
app/utils/parsers/fusionner_sources.py

Fusionne les fichiers .txt parsés de plusieurs sources (ChatGPT, Claude)
en un fichier unique par date avec tag [SOURCE:xxx] pour traçabilité.

Usage:
    python3 -m app.utils.parsers.fusionner_sources
    python3 -m app.utils.parsers.fusionner_sources --dry-run

Historique:
    - Session 63: Script inline original
    - Session 68: Conversion en utilitaire propre
"""

import re
import argparse
from pathlib import Path
from collections import defaultdict


# === CONFIGURATION PAR DÉFAUT ===
DEFAULT_SOURCES = {
    "chatgpt_serge": "~/Dropbox/aiterego_memory/echanges/exports/chatgpt_serge/",
    "chatgpt_prof": "~/Dropbox/aiterego_memory/echanges/exports/chatgpt_prof/",
    "claude": "~/Dropbox/aiterego_memory/echanges/exports/claude/",
}

DEFAULT_OUTPUT = "~/Dropbox/aiterego_memory/echanges/exports/fusionne/"

# Pattern pour parser les échanges
EXCHANGE_PATTERN = re.compile(
    r'(\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]\s*'
    r'(human|assistant|user|utilisateur|AIter Ego|Human|Assistant|User|Utilisateur|MOSS)\s*:)',
    re.IGNORECASE
)


def extract_exchanges(text: str, source_id: str) -> list:
    """
    Extrait les échanges avec leur timestamp et source pour tri.
    
    Args:
        text: Contenu du fichier .txt
        source_id: Identifiant de la source (chatgpt_serge, claude, etc.)
    
    Returns:
        Liste de tuples (timestamp, formatted_exchange)
    """
    matches = list(EXCHANGE_PATTERN.finditer(text))
    exchanges = []
    
    for i, match in enumerate(matches):
        timestamp = match.group(2)
        role = match.group(3)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        
        # Format: [SOURCE:xxx][timestamp] role:\ncontenu
        formatted = f"[SOURCE:{source_id}][{timestamp}] {role}:\n{content}"
        exchanges.append((timestamp, formatted))
    
    return exchanges


def fusionner_sources(
    sources: dict = None,
    output_dir: str = None,
    dry_run: bool = False
) -> dict:
    """
    Fusionne les fichiers .txt de plusieurs sources par date.
    
    Args:
        sources: Dict {source_id: chemin_dossier}
        output_dir: Dossier de sortie pour les fichiers fusionnés
        dry_run: Si True, analyse sans écrire
    
    Returns:
        Dict avec statistiques
    """
    # Utiliser les valeurs par défaut si non spécifiées
    if sources is None:
        sources = {k: Path(v).expanduser() for k, v in DEFAULT_SOURCES.items()}
    else:
        sources = {k: Path(v).expanduser() for k, v in sources.items()}
    
    if output_dir is None:
        output_dir = Path(DEFAULT_OUTPUT).expanduser()
    else:
        output_dir = Path(output_dir).expanduser()
    
    print(f"\n{'='*60}")
    print(f"🔀 FUSION DES SOURCES {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}")
    
    # Afficher les sources
    print(f"\n📂 Sources:")
    for source_id, source_path in sources.items():
        exists = "✅" if source_path.exists() else "❌"
        print(f"   {exists} {source_id}: {source_path}")
    
    print(f"\n📂 Output: {output_dir}")
    
    # Créer le dossier de sortie si nécessaire
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    
    # Grouper les fichiers par date
    files_by_date = defaultdict(list)
    
    for source_id, source_path in sources.items():
        if source_path.exists():
            for f in source_path.glob("*.txt"):
                # Extraire la date du nom de fichier (YYYY-MM-DD)
                date = f.stem[:10]
                files_by_date[date].append((source_id, f))
    
    print(f"\n📊 {len(files_by_date)} dates à traiter\n")
    print(f"{'-'*60}")
    
    # Statistiques
    stats = {
        "dates_processed": 0,
        "dates_skipped": 0,
        "total_exchanges": 0,
        "sources_used": defaultdict(int),
    }
    
    # Fusionner et trier chaque date
    for date, files in sorted(files_by_date.items()):
        all_exchanges = []
        sources_used = []
        
        for source_id, f in files:
            content = f.read_text(encoding="utf-8").strip()
            if content:
                exchanges = extract_exchanges(content, source_id)
                if exchanges:
                    all_exchanges.extend(exchanges)
                    if source_id not in sources_used:
                        sources_used.append(source_id)
                        stats["sources_used"][source_id] += 1
        
        if all_exchanges:
            # Trier par timestamp
            all_exchanges.sort(key=lambda x: x[0])
            
            # Recombiner
            combined = "\n\n".join(ex[1] for ex in all_exchanges)
            
            output_file = output_dir / f"{date}.txt"
            
            if not dry_run:
                output_file.write_text(combined, encoding="utf-8")
            
            status = "🔍" if dry_run else "✅"
            print(f"{status} {date} — {', '.join(sources_used)} — {len(all_exchanges)} échanges")
            
            stats["dates_processed"] += 1
            stats["total_exchanges"] += len(all_exchanges)
        else:
            print(f"⚠️  {date} — aucun échange")
            stats["dates_skipped"] += 1
    
    # Résumé
    print(f"{'-'*60}")
    print(f"\n📊 RÉSUMÉ:")
    print(f"   Dates traitées:  {stats['dates_processed']}")
    print(f"   Dates skippées:  {stats['dates_skipped']}")
    print(f"   Total échanges:  {stats['total_exchanges']}")
    print(f"   Sources:")
    for source_id, count in stats["sources_used"].items():
        print(f"      - {source_id}: {count} fichiers")
    
    print(f"\n{'='*60}")
    print(f"{'🔍 DRY RUN TERMINÉ' if dry_run else '🎉 FUSION TERMINÉE'}")
    print(f"{'='*60}\n")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Fusionne les fichiers parsés de plusieurs sources par date"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Analyser sans écrire les fichiers"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help=f"Dossier de sortie (défaut: {DEFAULT_OUTPUT})"
    )
    
    args = parser.parse_args()
    
    fusionner_sources(
        dry_run=args.dry_run,
        output_dir=args.output
    )


if __name__ == "__main__":
    main()
