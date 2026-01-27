import sqlite3
from config import METADATA_DB

def get_project_timeline(project_keyword: str, limit: int = 10):
    """
    Rayon Chronologie : Reconstruit la timeline d'un projet.
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    query = """
    SELECT timestamp, resume_texte 
    FROM metadata 
    WHERE projets LIKE ? OR resume_texte LIKE ?
    ORDER BY timestamp ASC
    LIMIT ?
    """
    
    try:
        cursor.execute(query, (f"%{project_keyword}%", f"%{project_keyword}%", limit))
        results = cursor.fetchall()
        
        if not results:
            return f"Aucune chronologie trouvée pour '{project_keyword}'."

        formatted = f"=== CHRONOLOGIE PROJET : {project_keyword} ===\n"
        for ts, texte in results:
            formatted += f"- [{ts}] {texte}\n"
        return formatted
    except Exception as e:
        return f"Erreur bibliothèque chronologie: {e}"
    finally:
        conn.close()