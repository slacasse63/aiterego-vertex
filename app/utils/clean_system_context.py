#!/usr/bin/env python3
"""
clean_system_context.py - Nettoyage rétroactif des archives

Retire le bloc [SYSTEM_CONTEXT]...[/SYSTEM_CONTEXT]--- des fichiers
d'échanges archivés qui le contiennent par erreur.

Usage:
    python3 clean_system_context.py --dry-run    # Voir ce qui serait modifié
    python3 clean_system_context.py              # Appliquer les modifications
"""

import argparse
from pathlib import Path
import re

# Chemin vers le dossier des échanges archivés
ECHANGES_DIR = Path.home() / "Dropbox" / "aiterego_memory" / "echanges"


def strip_system_context(contenu: str) -> tuple[str, bool]:
    """
    Retire le bloc [SYSTEM_CONTEXT]...[/SYSTEM_CONTEXT] d'un texte.
    
    Returns:
        (contenu_nettoyé, a_été_modifié)
    """
    if "[SYSTEM_CONTEXT:" not in contenu:
        return contenu, False
    
    # Pattern pour capturer tout le bloc SYSTEM_CONTEXT
    # Du début [SYSTEM_CONTEXT: jusqu'à [/SYSTEM_CONTEXT] suivi de --- et newline
    pattern = r'\[SYSTEM_CONTEXT:[^\]]*\].*?\[/SYSTEM_CONTEXT\]\s*---\s*'
    
    nouveau_contenu = re.sub(pattern, '', contenu, flags=re.DOTALL)
    
    # Nettoyer les lignes vides en début de fichier
    nouveau_contenu = nouveau_contenu.lstrip('\n')
    
    return nouveau_contenu, nouveau_contenu != contenu


def process_file(filepath: Path, dry_run: bool = True) -> dict:
    """
    Traite un fichier individuel.
    
    Returns:
        dict avec infos sur le traitement
    """
    try:
        contenu = filepath.read_text(encoding='utf-8')
        contenu_nettoye, modifie = strip_system_context(contenu)
        
        if not modifie:
            return {"status": "skip", "reason": "Pas de SYSTEM_CONTEXT"}
        
        taille_avant = len(contenu)
        taille_apres = len(contenu_nettoye)
        reduction = taille_avant - taille_apres
        
        if not dry_run:
            filepath.write_text(contenu_nettoye, encoding='utf-8')
        
        return {
            "status": "cleaned" if not dry_run else "would_clean",
            "taille_avant": taille_avant,
            "taille_apres": taille_apres,
            "reduction": reduction,
            "reduction_pct": round(reduction / taille_avant * 100, 1)
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Nettoie les fichiers d'archives contenant le SYSTEM_CONTEXT"
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true',
        help="Affiche ce qui serait modifié sans rien changer"
    )
    parser.add_argument(
        '--path',
        type=str,
        default=str(ECHANGES_DIR),
        help=f"Chemin vers le dossier des échanges (défaut: {ECHANGES_DIR})"
    )
    args = parser.parse_args()
    
    echanges_dir = Path(args.path)
    
    if not echanges_dir.exists():
        print(f"❌ Dossier non trouvé: {echanges_dir}")
        return
    
    print(f"{'🔍 MODE DRY-RUN' if args.dry_run else '🧹 MODE NETTOYAGE'}")
    print(f"📁 Dossier: {echanges_dir}")
    print("=" * 60)
    
    # Trouver tous les fichiers .txt
    fichiers = list(echanges_dir.rglob("*.txt"))
    print(f"📄 {len(fichiers)} fichiers trouvés\n")
    
    stats = {
        "total": len(fichiers),
        "nettoyes": 0,
        "ignores": 0,
        "erreurs": 0,
        "octets_economises": 0
    }
    
    for filepath in sorted(fichiers):
        result = process_file(filepath, dry_run=args.dry_run)
        
        # Chemin relatif pour affichage
        rel_path = filepath.relative_to(echanges_dir)
        
        if result["status"] in ("cleaned", "would_clean"):
            action = "→ serait nettoyé" if args.dry_run else "✓ nettoyé"
            print(f"{action}: {rel_path}")
            print(f"   {result['taille_avant']:,} → {result['taille_apres']:,} octets (-{result['reduction']:,}, -{result['reduction_pct']}%)")
            stats["nettoyes"] += 1
            stats["octets_economises"] += result["reduction"]
            
        elif result["status"] == "error":
            print(f"❌ Erreur: {rel_path} - {result['error']}")
            stats["erreurs"] += 1
            
        else:
            stats["ignores"] += 1
    
    # Résumé
    print("\n" + "=" * 60)
    print("📊 RÉSUMÉ")
    print(f"   Total fichiers: {stats['total']}")
    print(f"   {'Seraient nettoyés' if args.dry_run else 'Nettoyés'}: {stats['nettoyes']}")
    print(f"   Déjà propres: {stats['ignores']}")
    print(f"   Erreurs: {stats['erreurs']}")
    print(f"   Espace {'qui serait libéré' if args.dry_run else 'libéré'}: {stats['octets_economises']:,} octets ({stats['octets_economises']/1024:.1f} Ko)")
    
    if args.dry_run and stats["nettoyes"] > 0:
        print(f"\n💡 Pour appliquer les modifications, relancez sans --dry-run")


if __name__ == "__main__":
    main()
