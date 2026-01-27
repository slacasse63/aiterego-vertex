"""
hermes_modules/parsing.py - Parsing des requêtes en langage naturel

Extrait les paramètres d'une requête : mots-clés, personnes, dates, etc.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

# === STOPWORDS ===
STOPWORDS = {
    # Français
    'dans', 'avec', 'pour', 'cette', 'quand', 'comment',
    'pourquoi', 'quel', 'quelle', 'quels', 'quelles', 'nous',
    'vous', 'leur', 'notre', 'votre', 'été', 'être', 'avoir',
    'fait', 'faire', 'plus', 'moins', 'très', 'aussi', 'donc',
    'souviens', 'rappelle', 'parlé', 'discuté', 'discussion', 'conversation'
    'conversations', 'est', 'sont', 'qui', 'que', 'quoi', 'sur', 'les', 'des', 'une',
    # Anglais
    'the', 'and', 'that', 'this', 'with', 'from', 'what', 'when',
    'where', 'which', 'about', 'have', 'been', 'were', 'will'
}

# Mots exclus pour la détection de personnes (plus strict)
STOPWORDS_STRICT = {
    'qui', 'que', 'quoi', 'comment', 'pourquoi', 'quand', 
    'est', 'sont', 'etait', 'était', 'les', 'des'
}

# Mots avec majuscule qui ne sont PAS des personnes
NON_PERSONNES = {
    # Projets MOSS
    'roget', 'moss', 'aiter', 'ego', 'orbito', 'neandertal', 'trildasa',
    'hermes', 'hermès', 'scribe',
    # Outils et plateformes
    'python', 'azure', 'dropbox', 'github', 'google', 'drive', 'onedrive',
    'openai', 'anthropic', 'gemini', 'claude', 'chatgpt', 'gpt',
    'flask', 'fastapi', 'sqlite', 'pycharm', 'pythonanywhere', 'valeria',
    # Institutions et organisations
    'crsh', 'obvia', 'oicrm', 'iid', 'ulaval', 'frqsc', 'mila',
    # Autres noms propres non-personnes
    'québec', 'canada', 'montréal', 'paris', 'france'
}


def _parse_query(query: str) -> Dict[str, Any]:
    """
    Extrait les paramètres d'une requête en langage naturel.
    Nettoie les mots-clés pour éviter les doublons avec les personnes.
    
    Returns:
        dict avec:
            - mots_cles: liste de mots significatifs
            - tags_explicites: tags Roget au format XX-XXXX-XXXX
            - date_debut, date_fin: plage de dates (ou None)
            - type_contenu: type détecté (ou None)
            - domaine: domaine détecté (ou None)
            - emotion_cible: tuple (valence, activation) ou None
            - personnes: noms de personnes détectés
    """
    query_lower = query.lower()
    
    # 1. Extraction des Personnes d'abord (Priorité)
    # Heuristique: Mots avec majuscule, SAUF les noms connus (projets, outils, lieux)
    raw_personnes = re.findall(r'\b[A-Z][a-zÀ-ÿ]+\b', query)
    personnes_detectees = [
        p for p in raw_personnes 
        if p.lower() not in STOPWORDS_STRICT 
        and p.lower() not in NON_PERSONNES
    ]
    
    # 2. Extraction des mots-clés avec FILTRAGE INTELLIGENT
    mots = re.findall(r'\b[a-zA-ZÀ-ÿ]{3,}\b', query_lower)
    
    # On garde le mot SEULEMENT SI :
    # - Ce n'est pas un stopword
    # - Ce n'est pas une partie du nom d'une personne détectée
    personnes_lower = [p.lower() for p in personnes_detectees]
    mots_cles = []
    
    for m in mots:
        if m in STOPWORDS:
            continue
        # Si le mot est déjà dans les personnes détectées, on ne le met pas en mot-clé
        if m in personnes_lower:
            continue
        mots_cles.append(m)
    
    # 3. Ajouter les noms connus (projets, outils) aux mots-clés s'ils sont dans la requête
    for p in raw_personnes:
        if p.lower() in NON_PERSONNES and p.lower() not in mots_cles:
            mots_cles.append(p.lower())
    
    # Tags Roget explicites (format XX-XXXX-XXXX)
    tags_explicites = re.findall(r'\b\d{2}-\d{4}-\d{4}\b', query)
    
    # Dates relatives (utiliser UTC)
    date_debut, date_fin = _parse_dates(query_lower)
    
    # Type de contenu
    type_contenu = _detect_type_contenu(query_lower)
    
    # Domaine
    domaine = _detect_domaine(query_lower)
    
    # Émotion cible
    emotion_cible = _detect_emotion(query_lower)
    
    return {
        "mots_cles": mots_cles,
        "tags_explicites": tags_explicites,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "type_contenu": type_contenu,
        "domaine": domaine,
        "emotion_cible": emotion_cible,
        "personnes": personnes_detectees
    }


def _parse_dates(query_lower: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Extrait les dates relatives de la requête."""
    now = datetime.now(timezone.utc)
    
    if 'hier' in query_lower or 'yesterday' in query_lower:
        return now - timedelta(days=1), now
    elif 'semaine' in query_lower or 'week' in query_lower:
        return now - timedelta(weeks=1), now
    elif 'mois' in query_lower or 'month' in query_lower:
        return now - timedelta(days=30), now
    
    return None, None


def _detect_type_contenu(query_lower: str) -> Optional[str]:
    """Détecte le type de contenu recherché."""
    if any(w in query_lower for w in ['question', 'demande', 'ask']):
        return 'question'
    elif any(w in query_lower for w in ['décision', 'decision', 'choisi', 'chose']):
        return 'decision'
    elif any(w in query_lower for w in ['réflexion', 'pensée', 'thought']):
        return 'reflexion'
    return None


def _detect_domaine(query_lower: str) -> Optional[str]:
    """Détecte le domaine recherché."""
    if any(w in query_lower for w in ['travail', 'work', 'professionnel', 'projet']):
        return 'professionnel'
    elif any(w in query_lower for w in ['personnel', 'personal', 'famille', 'ami']):
        return 'personnel'
    elif any(w in query_lower for w in ['technique', 'technical', 'code', 'python']):
        return 'technique'
    return None


def _detect_emotion(query_lower: str) -> Optional[Tuple[float, float]]:
    """Détecte l'émotion cible (valence, activation)."""
    if any(w in query_lower for w in ['content', 'happy', 'joie', 'positif']):
        return (0.7, 0.5)
    elif any(w in query_lower for w in ['triste', 'sad', 'négatif', 'frustré']):
        return (-0.7, 0.5)
    elif any(w in query_lower for w in ['calme', 'calm', 'serein', 'peaceful']):
        return (0.3, 0.2)
    elif any(w in query_lower for w in ['excité', 'excited', 'énergique', 'motivated']):
        return (0.5, 0.9)
    return None