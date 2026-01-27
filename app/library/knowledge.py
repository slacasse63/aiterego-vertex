"""
knowledge.py - Mémoire persistante d'Iris (fichiers Markdown)
MOSS v0.11.5 - Session 80 - Support symlinks et sous-dossiers

Permet à Iris de lire, enrichir et mettre à jour ses fichiers de connaissance.
Format: YAML frontmatter + sections Markdown (##)

NOUVEAU v0.11.5 (diff avec v0.10.4):
- Support complet des liens symboliques (followlinks=True)
- Accès aux sous-dossiers (ex: drive_link/blackboard)
- Résolution de chemin intelligente avec Path.resolve()
- Fonction _resolve_path() pour centraliser la logique
- list_knowledge() avec option include_subfolders

Emplacement principal: ~/Dropbox/aiterego_memory/iris/knowledge/
Lien symbolique attendu: ~/Dropbox/aiterego_memory/iris/knowledge/drive_link → Google Drive/AIter Ego/Iris/

Auteurs: Serge Lacasse, Claude, Iris
Date: 2026-01-16
"""

from pathlib import Path
from datetime import datetime
import logging
import re
import os
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Chemin vers le dossier knowledge d'Iris (compatible avec la version actuelle)
KNOWLEDGE_DIR = Path("~/Dropbox/aiterego_memory/iris/knowledge").expanduser().resolve()

# Extensions supportées pour la lecture
SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}


def _resolve_path(fichier: str) -> tuple[Path, str]:
    """
    Résout un chemin de fichier, supportant:
    - Noms simples (dans KNOWLEDGE_DIR)
    - Chemins avec sous-dossiers (ex: drive_link/blackboard)
    - Liens symboliques (suivis automatiquement)
    
    Args:
        fichier: Nom ou chemin relatif du fichier
        
    Returns:
        tuple (filepath_resolved, fichier_clean)
    """
    # Nettoyer le nom
    fichier_clean = fichier.strip()
    
    # Enlever .md si présent à la fin (on l'ajoute si nécessaire)
    if fichier_clean.endswith(".md"):
        fichier_clean = fichier_clean[:-3]
    
    # Construire le chemin
    if "/" in fichier_clean or "\\" in fichier_clean:
        # Chemin avec sous-dossiers (ex: drive_link/blackboard)
        filepath = KNOWLEDGE_DIR / fichier_clean
        
        # Essayer avec différentes extensions
        if not filepath.exists():
            for ext in SUPPORTED_EXTENSIONS:
                test_path = KNOWLEDGE_DIR / f"{fichier_clean}{ext}"
                if test_path.exists():
                    filepath = test_path
                    break
            else:
                # Essayer sans extension (peut être un fichier sans extension)
                filepath = KNOWLEDGE_DIR / fichier_clean
    else:
        # Nom simple → ajouter .md
        filepath = KNOWLEDGE_DIR / f"{fichier_clean}.md"
    
    # Résoudre le lien symbolique si présent (CRITIQUE pour drive_link)
    try:
        filepath_resolved = filepath.resolve()
    except Exception:
        filepath_resolved = filepath
    
    return filepath_resolved, fichier_clean


def _list_available_files() -> list[str]:
    """
    Liste tous les fichiers disponibles, y compris dans les sous-dossiers
    et à travers les liens symboliques.
    
    Returns:
        Liste des chemins relatifs des fichiers disponibles
    """
    fichiers = []
    
    if not KNOWLEDGE_DIR.exists():
        return fichiers
    
    # Parcourir récursivement avec suivi des liens symboliques
    for root, dirs, files in os.walk(KNOWLEDGE_DIR, followlinks=True):
        # Éviter les boucles infinies en excluant certains dossiers
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'__pycache__', 'venv'}]
        
        root_path = Path(root)
        
        for filename in files:
            # Ignorer fichiers cachés
            if filename.startswith('.'):
                continue
            
            # Vérifier l'extension
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            
            try:
                # Chemin relatif depuis KNOWLEDGE_DIR
                rel_path = (root_path / filename).relative_to(KNOWLEDGE_DIR)
                fichiers.append(str(rel_path))
            except ValueError:
                # Si relative_to échoue, utiliser le nom simple
                fichiers.append(filename)
    
    return sorted(fichiers)


def read_knowledge(fichier: str) -> dict:
    """
    Lit un fichier de connaissance d'Iris.
    
    Supporte:
    - Noms simples: "personnes" → knowledge/personnes.md
    - Sous-dossiers: "drive_link/blackboard" → knowledge/drive_link/blackboard.md
    - Liens symboliques: Suivis automatiquement
    
    Args:
        fichier: Nom du fichier ou chemin relatif (avec ou sans extension)
    
    Returns:
        dict avec status, fichier, contenu (ou error + fichiers_disponibles)
    """
    logger.info(f"📖 [KNOWLEDGE] Lecture: {fichier}")
    
    filepath, fichier_clean = _resolve_path(fichier)
    
    try:
        if not filepath.exists():
            # Lister les fichiers disponibles (y compris via symlinks)
            fichiers_dispo = _list_available_files()
            
            return {
                "status": "error",
                "error": f"Fichier '{fichier}' non trouvé",
                "fichiers_disponibles": fichiers_dispo,
                "chemin_verifie": str(filepath),
                "hint": "Utilisez le chemin relatif (ex: drive_link/blackboard)"
            }
        
        contenu = filepath.read_text(encoding='utf-8')
        
        # Déterminer si c'est via un lien symbolique
        original_path = KNOWLEDGE_DIR / fichier_clean
        is_symlink = original_path.is_symlink() if original_path.exists() else False
        
        return {
            "status": "success",
            "fichier": fichier_clean,
            "contenu": contenu,
            "taille": len(contenu),
            "chemin": str(filepath),
            "via_symlink": is_symlink
        }
        
    except PermissionError as e:
        logger.error(f"Permission refusée: {filepath}")
        return {
            "status": "error",
            "error": f"Permission refusée pour '{fichier}'",
            "chemin_verifie": str(filepath)
        }
    except Exception as e:
        logger.error(f"Erreur lecture knowledge: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fichier": fichier_clean
        }


def append_knowledge(fichier: str, contenu: str) -> dict:
    """
    Ajoute du contenu à la fin d'un fichier de connaissance.
    
    Args:
        fichier: Nom du fichier ou chemin relatif
        contenu: Texte à ajouter (sera précédé d'une ligne vide)
    
    Returns:
        dict avec status et détails
    """
    logger.info(f"📝 [KNOWLEDGE] Append: {fichier}")
    
    filepath, fichier_clean = _resolve_path(fichier)
    
    try:
        if not filepath.exists():
            fichiers_dispo = _list_available_files()
            return {
                "status": "error",
                "error": f"Fichier '{fichier}' non trouvé. Impossible d'ajouter à un fichier inexistant.",
                "fichiers_disponibles": fichiers_dispo
            }
        
        # Lire le contenu actuel
        contenu_actuel = filepath.read_text(encoding='utf-8')
        
        # Ajouter le nouveau contenu avec séparateur
        nouveau_contenu = f"{contenu_actuel.rstrip()}\n\n{contenu.strip()}\n"
        
        # Écrire
        filepath.write_text(nouveau_contenu, encoding='utf-8')
        
        logger.info(f"✅ [KNOWLEDGE] Ajouté {len(contenu)} chars à {fichier_clean}")
        
        return {
            "status": "success",
            "fichier": fichier_clean,
            "action": "append",
            "chars_ajoutes": len(contenu),
            "taille_finale": len(nouveau_contenu),
            "message": f"Contenu ajouté à {fichier}"
        }
        
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission refusée pour écrire dans '{fichier}'"
        }
    except Exception as e:
        logger.error(f"Erreur append knowledge: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fichier": fichier_clean
        }


def update_knowledge(fichier: str, section: str, contenu: str) -> dict:
    """
    Met à jour une section spécifique (##) dans un fichier de connaissance.
    Remplace le contenu de la section jusqu'à la prochaine section ## ou la fin.
    
    Args:
        fichier: Nom du fichier ou chemin relatif
        section: Titre de la section SANS les ## (ex: "Tâches en cours")
        contenu: Nouveau contenu de la section (SANS le titre ##)
    
    Returns:
        dict avec status et détails
    """
    logger.info(f"🔄 [KNOWLEDGE] Update: {fichier} → section '{section}'")
    
    filepath, fichier_clean = _resolve_path(fichier)
    
    try:
        if not filepath.exists():
            fichiers_dispo = _list_available_files()
            return {
                "status": "error",
                "error": f"Fichier '{fichier}' non trouvé",
                "fichiers_disponibles": fichiers_dispo
            }
        
        texte = filepath.read_text(encoding='utf-8')
        
        # Chercher la section (## Titre ou # Titre)
        section_clean = section.strip()
        
        # Pattern corrigé v0.10.4 :
        # - {{1,2}} pour échapper les accolades dans la f-string
        # - \s*$ pour accepter fin de ligne OU fin de fichier
        # group(1) = ^ ou \n (préfixe)
        # group(2) = ## Titre (le header qu'on veut garder)
        pattern = rf'(^|\n)(#{{1,2}}\s*{re.escape(section_clean)}\s*$)'
        match = re.search(pattern, texte, re.MULTILINE | re.IGNORECASE)
        
        if not match:
            # Extraire les sections existantes pour aider
            sections_pattern = r'^#{1,2}\s*(.+?)\s*$'
            sections_existantes = re.findall(sections_pattern, texte, re.MULTILINE)
            
            return {
                "status": "error",
                "error": f"Section '{section_clean}' non trouvée",
                "sections_disponibles": sections_existantes
            }
        
        # Trouver où commence le contenu (après le header)
        section_start = match.end()
        
        # Trouver où finit la section (prochain ## ou fin de fichier)
        next_section = re.search(r'\n#{1,2}\s+\S', texte[section_start:])
        
        if next_section:
            section_end = section_start + next_section.start()
        else:
            section_end = len(texte)
        
        # Construire le nouveau texte
        avant = texte[:section_start]
        apres = texte[section_end:]
        
        # Ajouter le nouveau contenu avec formatage propre
        nouveau_contenu = f"\n{contenu.strip()}\n"
        
        nouveau_texte = avant + nouveau_contenu + apres
        
        # Écrire
        filepath.write_text(nouveau_texte, encoding='utf-8')
        
        logger.info(f"✅ [KNOWLEDGE] Section '{section_clean}' mise à jour dans {fichier_clean}")
        
        return {
            "status": "success",
            "fichier": fichier_clean,
            "section": section_clean,
            "action": "update",
            "taille_nouvelle_section": len(contenu),
            "message": f"Section '{section_clean}' mise à jour dans {fichier}"
        }
        
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission refusée pour écrire dans '{fichier}'"
        }
    except Exception as e:
        logger.error(f"Erreur update knowledge: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fichier": fichier_clean
        }


def create_knowledge(fichier: str, contenu: str = "") -> dict:
    """
    Crée un nouveau fichier de connaissance.
    
    Args:
        fichier: Nom du fichier (sans extension .md)
        contenu: Contenu initial (optionnel)
    
    Returns:
        dict avec status et détails
    """
    logger.info(f"🆕 [KNOWLEDGE] Création: {fichier}")
    
    filepath, fichier_clean = _resolve_path(fichier)
    
    try:
        # Vérifier si le fichier existe déjà
        if filepath.exists():
            return {
                "status": "error",
                "error": f"Le fichier '{fichier}' existe déjà",
                "chemin": str(filepath)
            }
        
        # Créer le dossier parent si nécessaire
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Créer le fichier
        filepath.write_text(contenu, encoding='utf-8')
        
        logger.info(f"✅ [KNOWLEDGE] Fichier créé: {filepath}")
        
        return {
            "status": "success",
            "fichier": fichier_clean,
            "action": "created",
            "taille": len(contenu),
            "chemin": str(filepath),
            "message": f"Fichier '{fichier}' créé"
        }
        
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission refusée pour créer '{fichier}'"
        }
    except Exception as e:
        logger.error(f"Erreur création knowledge: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fichier": fichier_clean
        }


def delete_knowledge(fichier: str) -> dict:
    """
    Supprime un fichier de connaissance.
    
    Args:
        fichier: Nom du fichier (sans extension .md)
    
    Returns:
        dict avec status et détails
    """
    logger.info(f"🗑️ [KNOWLEDGE] Suppression: {fichier}")
    
    filepath, fichier_clean = _resolve_path(fichier)
    
    try:
        if not filepath.exists():
            fichiers_dispo = _list_available_files()
            return {
                "status": "error",
                "error": f"Fichier '{fichier}' non trouvé",
                "fichiers_disponibles": fichiers_dispo
            }
        
        # Supprimer le fichier
        filepath.unlink()
        
        logger.info(f"✅ [KNOWLEDGE] Fichier supprimé: {fichier_clean}")
        
        return {
            "status": "success",
            "fichier": fichier_clean,
            "action": "deleted",
            "message": f"Fichier '{fichier}' supprimé"
        }
        
    except PermissionError:
        return {
            "status": "error",
            "error": f"Permission refusée pour supprimer '{fichier}'"
        }
    except Exception as e:
        logger.error(f"Erreur suppression knowledge: {e}")
        return {
            "status": "error",
            "error": str(e),
            "fichier": fichier_clean
        }


def list_knowledge(include_subfolders: bool = True) -> dict:
    """
    Liste tous les fichiers de connaissance disponibles.
    
    Args:
        include_subfolders: Si True, inclut les sous-dossiers et symlinks
    
    Returns:
        dict avec liste des fichiers
    """
    logger.info(f"📋 [KNOWLEDGE] Liste des fichiers")
    
    try:
        if not KNOWLEDGE_DIR.exists():
            return {
                "status": "success",
                "fichiers": [],
                "count": 0,
                "chemin": str(KNOWLEDGE_DIR)
            }
        
        fichiers = []
        
        if include_subfolders:
            # Parcours complet avec symlinks
            for root, dirs, files in os.walk(KNOWLEDGE_DIR, followlinks=True):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'__pycache__', 'venv'}]
                
                root_path = Path(root)
                
                for filename in files:
                    if filename.startswith('.'):
                        continue
                    
                    ext = Path(filename).suffix.lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue
                    
                    filepath = root_path / filename
                    stat = filepath.stat()
                    
                    try:
                        rel_path = filepath.relative_to(KNOWLEDGE_DIR)
                    except ValueError:
                        rel_path = Path(filename)
                    
                    # Détecter si via symlink
                    is_symlink = any(part for part in rel_path.parts 
                                    if (KNOWLEDGE_DIR / part).is_symlink())
                    
                    fichiers.append({
                        "nom": str(rel_path),
                        "taille": stat.st_size,
                        "modifie": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        "via_symlink": is_symlink
                    })
        else:
            # Seulement le niveau racine
            for f in sorted(KNOWLEDGE_DIR.glob("*.md")):
                stat = f.stat()
                fichiers.append({
                    "nom": f.stem,
                    "taille": stat.st_size,
                    "modifie": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    "via_symlink": False
                })
        
        return {
            "status": "success",
            "fichiers": fichiers,
            "count": len(fichiers),
            "chemin": str(KNOWLEDGE_DIR)
        }
        
    except Exception as e:
        logger.error(f"Erreur liste knowledge: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("TEST - Module knowledge.py v0.11.5 (Support symlinks)")
    print("=" * 60)
    
    print(f"\n📁 Dossier knowledge: {KNOWLEDGE_DIR}")
    print(f"   Existe: {KNOWLEDGE_DIR.exists()}")
    
    # Test list_knowledge avec symlinks
    print("\n1. Test list_knowledge (avec sous-dossiers et symlinks):")
    result = list_knowledge(include_subfolders=True)
    if result["status"] == "success":
        print(f"   ✅ {result['count']} fichiers trouvés:")
        for f in result["fichiers"][:10]:  # Max 10 pour l'affichage
            symlink_mark = " 🔗" if f.get("via_symlink") else ""
            print(f"      - {f['nom']}{symlink_mark}")
        if result["count"] > 10:
            print(f"      ... et {result['count'] - 10} autres")
    else:
        print(f"   ❌ {result['error']}")
    
    # Test read_knowledge simple
    print("\n2. Test read_knowledge('current_context'):")
    result = read_knowledge("current_context")
    if result["status"] == "success":
        print(f"   ✅ Lu {result['taille']} caractères")
    else:
        print(f"   ❌ {result['error']}")
    
    # Test read_knowledge avec sous-dossier (si drive_link existe)
    drive_link = KNOWLEDGE_DIR / "drive_link"
    if drive_link.exists():
        print("\n3. Test read_knowledge('drive_link/blackboard'):")
        result = read_knowledge("drive_link/blackboard")
        if result["status"] == "success":
            print(f"   ✅ Lu {result['taille']} caractères via symlink: {result.get('via_symlink')}")
        else:
            print(f"   ❌ {result['error']}")
            if result.get("fichiers_disponibles"):
                print(f"   📋 Fichiers disponibles dans drive_link: {[f for f in result['fichiers_disponibles'] if 'drive_link' in f][:5]}")
    else:
        print("\n3. Test symlink ignoré (drive_link non présent)")
    
    print("\n" + "=" * 60)
