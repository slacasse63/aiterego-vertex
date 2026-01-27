import sqlite3
from config import METADATA_DB

def get_emotional_resonance(valence: float = None, activation: float = None, limit: int = 5):
    """
    Rayon Émotions : Trouve les souvenirs par résonance émotionnelle.
    Utilise le modèle Russell Circumplex (valence + activation).
    
    Args:
        valence (float): -1.0 (négatif) à +1.0 (positif)
        activation (float): 0.0 (calme) à 1.0 (intense)
        limit (int): Nombre de résultats (défaut: 5)
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    try:
        # Construction dynamique de la requête selon les paramètres
        conditions = []
        params = []
        
        if valence is not None:
            if valence < 0:
                # Émotions négatives : on cherche valence <= seuil
                conditions.append("emotion_valence <= ?")
                params.append(valence + 0.2)  # Marge de tolérance
            else:
                # Émotions positives : on cherche valence >= seuil
                conditions.append("emotion_valence >= ?")
                params.append(valence - 0.2)
        
        if activation is not None:
            if activation > 0.5:
                # Haute activation : on cherche activation >= seuil
                conditions.append("emotion_activation >= ?")
                params.append(activation - 0.2)
            else:
                # Basse activation : on cherche activation <= seuil
                conditions.append("emotion_activation <= ?")
                params.append(activation + 0.2)
        
        # S'assurer qu'on a des conditions
        if not conditions:
            return "Aucun paramètre émotionnel fourni. Utilise valence et/ou activation."
        
        # Exclure les valeurs nulles
        conditions.append("emotion_valence IS NOT NULL")
        conditions.append("emotion_activation IS NOT NULL")
        
        where_clause = " AND ".join(conditions)
        
        # Tri : priorité aux émotions les plus intenses dans la direction demandée
        if valence is not None and valence < 0:
            order_by = "emotion_valence ASC, emotion_activation DESC"
        elif valence is not None and valence > 0:
            order_by = "emotion_valence DESC, emotion_activation DESC"
        else:
            order_by = "emotion_activation DESC"
        
        query = f"""
        SELECT timestamp, resume_texte, emotion_valence, emotion_activation
        FROM metadata
        WHERE {where_clause}
        ORDER BY {order_by}
        LIMIT ?
        """
        
        params.append(limit)
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            quadrant = _describe_quadrant(valence, activation)
            return f"Aucun souvenir trouvé dans le quadrant '{quadrant}'."
        
        quadrant = _describe_quadrant(valence, activation)
        formatted = f"=== RÉSONANCES ÉMOTIONNELLES : {quadrant} ===\n"
        for ts, texte, val, act in results:
            formatted += f"- [{ts}] (V:{val:.2f}, A:{act:.2f}) {texte}\n"
        return formatted
        
    except Exception as e:
        return f"Erreur bibliothèque émotions: {e}"
    finally:
        conn.close()


def _describe_quadrant(valence: float, activation: float) -> str:
    """Décrit le quadrant Russell en langage naturel."""
    if valence is None and activation is None:
        return "indéfini"
    
    if valence is not None and valence < 0:
        if activation is not None and activation > 0.5:
            return "Tension (stress, anxiété, colère)"
        else:
            return "Dépression (tristesse, épuisement)"
    elif valence is not None and valence > 0:
        if activation is not None and activation > 0.5:
            return "Excitation (joie, enthousiasme)"
        else:
            return "Sérénité (calme, détente)"
    else:
        if activation is not None and activation > 0.5:
            return "Haute activation"
        else:
            return "Basse activation"