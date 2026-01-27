"""
profile.py - Lecture du profil utilisateur
MOSS v0.8.3

Permet à l'Agent (Iris) de consulter le profil détaillé de Serge
(psychométrie, biographie, expertise, etc.)
"""

from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

# Chemin vers le profil
PROFILE_PATH = Path.home() / "Dropbox" / "aiterego_memory" / "config" / "profil_serge.json"


def read_profile(section: str = None) -> str:
    """
    Lit le profil de Serge.
    
    Args:
        section (str, optionnel): Section spécifique à retourner.
            Options: identity, cognitive, biological, knowledge, interaction, biography
            Si None, retourne tout le profil.
    
    Returns:
        str: Contenu formaté du profil
    """
    logger.info(f"📋 Lecture profil (section: {section or 'complète'})")
    
    try:
        if not PROFILE_PATH.exists():
            return f"Erreur: Fichier profil non trouvé: {PROFILE_PATH}"
        
        with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
            profile = json.load(f)
        
        user_profile = profile.get("user_profile", {})
        
        # Si section spécifique demandée
        if section:
            section_map = {
                "identity": "identity_core",
                "cognitive": "cognitive_operating_system",
                "biological": "biological_hardware",
                "knowledge": "knowledge_graph",
                "interaction": "interaction_protocol",
                "biography": "biography"
            }
            
            key = section_map.get(section.lower())
            if key and key in user_profile:
                return f"=== PROFIL SERGE : {section.upper()} ===\n{json.dumps(user_profile[key], indent=2, ensure_ascii=False)}"
            else:
                sections_dispo = ", ".join(section_map.keys())
                return f"Section '{section}' non trouvée. Sections disponibles: {sections_dispo}"
        
        # Sinon retourner tout le profil formaté
        return f"=== PROFIL COMPLET DE SERGE ===\n{json.dumps(user_profile, indent=2, ensure_ascii=False)}"
        
    except json.JSONDecodeError as e:
        return f"Erreur parsing JSON du profil: {e}"
    except Exception as e:
        logger.error(f"Erreur lecture profil: {e}")
        return f"Erreur lecture profil: {str(e)}"


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("TEST - Module profile.py")
    print("=" * 60)
    
    print("\n1. Lecture complète:")
    result = read_profile()
    print(result[:500] + "..." if len(result) > 500 else result)
    
    print("\n2. Lecture section 'identity':")
    result = read_profile("identity")
    print(result)
    
    print("\n3. Lecture section 'biography':")
    result = read_profile("biography")
    print(result[:500] + "..." if len(result) > 500 else result)
