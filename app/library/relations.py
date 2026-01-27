import sqlite3
from config import METADATA_DB

def get_relation_history(person_name: str, limit: int = 10):
    """
    Rayon Relations : Retrace l'historique avec une personne.
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    query = """
    SELECT m.timestamp, m.resume_texte, m.projets
    FROM metadata m
    WHERE m.personnes LIKE ?
    ORDER BY m.timestamp ASC
    LIMIT ?
    """
    
    try:
        cursor.execute(query, (f"%{person_name}%", limit))
        results = cursor.fetchall()
        
        if not results:
            return f"Aucun historique trouvé avec '{person_name}'."
            
        formatted = f"=== HISTORIQUE RELATIONNEL : {person_name} ===\n"
        for ts, texte, proj in results:
            formatted += f"- [{ts}] {texte} [Projet: {proj}]\n"
        return formatted
        
    except Exception as e:
        return f"Erreur bibliothèque relations: {e}"
    finally:
        conn.close()