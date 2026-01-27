"""
Bibliothèque Piliers - Gestion des faits consolidés par l'Agent
MOSS v0.8.1

Les piliers sont des faits importants que l'Agent consolide activement,
contrairement aux segments que le Scribe indexe passivement.

Échelle d'importance:
    0 = Éphémère (défaut Scribe)
    1 = Détail utile
    2 = Jalon/Structure
    3 = Fondamental/Identitaire

Catégories: IDENTITE, RECHERCHE, TECHNIQUE, RELATION, VALEUR
"""

import sqlite3
from config import METADATA_DB


def get_piliers(categorie: str = None, importance_min: int = None, limit: int = 10):
    """
    Rayon Piliers : Récupère les faits consolidés.
    
    Args:
        categorie (str): Filtrer par catégorie (IDENTITE, RECHERCHE, TECHNIQUE, RELATION, VALEUR)
        importance_min (int): Importance minimale (0-3)
        limit (int): Nombre de résultats (défaut: 10)
    
    Returns:
        str: Liste formatée des piliers pour l'Agent
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    try:
        conditions = []
        params = []
        
        if categorie:
            conditions.append("categorie = ?")
            params.append(categorie.upper())
        
        if importance_min is not None:
            conditions.append("importance >= ?")
            params.append(importance_min)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = f"""
        SELECT id, fait, categorie, importance, created_at
        FROM piliers
        {where_clause}
        ORDER BY importance DESC, created_at DESC
        LIMIT ?
        """
        
        params.append(limit)
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            if categorie:
                return f"Aucun pilier trouvé dans la catégorie '{categorie}'."
            return "Aucun pilier consolidé pour le moment."
        
        # Formatage pour l'Agent
        formatted = "=== PILIERS (FAITS CONSOLIDÉS) ===\n"
        for id_, fait, cat, imp, created in results:
            etoiles = "★" * imp + "☆" * (3 - imp)
            formatted += f"[{cat}] {etoiles} {fait}\n"
        
        return formatted
        
    except Exception as e:
        return f"Erreur bibliothèque piliers: {e}"
    finally:
        conn.close()


def add_pilier(fait: str, categorie: str = "IDENTITE", importance: int = 1, source_id: int = None):
    """
    Ajoute un nouveau pilier (fait consolidé par l'Agent).
    
    Args:
        fait (str): Le fait à consolider (obligatoire)
        categorie (str): IDENTITE, RECHERCHE, TECHNIQUE, RELATION, VALEUR (défaut: IDENTITE)
        importance (int): 0-3 (défaut: 1)
        source_id (int): ID du segment source (optionnel)
    
    Returns:
        str: Confirmation ou erreur
    """
    # Validation
    categories_valides = ["IDENTITE", "RECHERCHE", "TECHNIQUE", "RELATION", "VALEUR"]
    categorie = categorie.upper()
    
    if categorie not in categories_valides:
        return f"Catégorie invalide. Choix: {', '.join(categories_valides)}"
    
    if not 0 <= importance <= 3:
        return "Importance doit être entre 0 et 3."
    
    if not fait or len(fait.strip()) < 3:
        return "Le fait doit contenir au moins 3 caractères."
    
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    try:
        # Vérifier si un pilier similaire existe déjà
        cursor.execute(
            "SELECT id, fait FROM piliers WHERE fait LIKE ? LIMIT 1",
            (f"%{fait[:50]}%",)
        )
        existing = cursor.fetchone()
        
        if existing:
            return f"Pilier similaire existe déjà (ID {existing[0]}): {existing[1][:80]}..."
        
        # Insertion
        cursor.execute("""
            INSERT INTO piliers (fait, categorie, importance, source_id)
            VALUES (?, ?, ?, ?)
        """, (fait.strip(), categorie, importance, source_id))
        
        conn.commit()
        pilier_id = cursor.lastrowid
        
        etoiles = "★" * importance + "☆" * (3 - importance)
        return f"✅ Pilier consolidé (ID {pilier_id}): [{categorie}] {etoiles} {fait}"
        
    except Exception as e:
        conn.rollback()
        return f"Erreur ajout pilier: {e}"
    finally:
        conn.close()


def update_pilier(pilier_id: int, importance: int = None, categorie: str = None):
    """
    Met à jour un pilier existant.
    
    Args:
        pilier_id (int): ID du pilier à modifier
        importance (int): Nouvelle importance (0-3)
        categorie (str): Nouvelle catégorie
    
    Returns:
        str: Confirmation ou erreur
    """
    if importance is None and categorie is None:
        return "Rien à modifier. Spécifie importance et/ou categorie."
    
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    try:
        # Vérifier que le pilier existe
        cursor.execute("SELECT fait FROM piliers WHERE id = ?", (pilier_id,))
        existing = cursor.fetchone()
        
        if not existing:
            return f"Pilier ID {pilier_id} introuvable."
        
        updates = []
        params = []
        
        if importance is not None:
            if not 0 <= importance <= 3:
                return "Importance doit être entre 0 et 3."
            updates.append("importance = ?")
            params.append(importance)
        
        if categorie is not None:
            categories_valides = ["IDENTITE", "RECHERCHE", "TECHNIQUE", "RELATION", "VALEUR"]
            categorie = categorie.upper()
            if categorie not in categories_valides:
                return f"Catégorie invalide. Choix: {', '.join(categories_valides)}"
            updates.append("categorie = ?")
            params.append(categorie)
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(pilier_id)
        
        query = f"UPDATE piliers SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()
        
        return f"✅ Pilier ID {pilier_id} mis à jour: {existing[0][:60]}..."
        
    except Exception as e:
        conn.rollback()
        return f"Erreur mise à jour pilier: {e}"
    finally:
        conn.close()


def delete_pilier(pilier_id: int):
    """
    Supprime un pilier.
    
    Args:
        pilier_id (int): ID du pilier à supprimer
    
    Returns:
        str: Confirmation ou erreur
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT fait FROM piliers WHERE id = ?", (pilier_id,))
        existing = cursor.fetchone()
        
        if not existing:
            return f"Pilier ID {pilier_id} introuvable."
        
        cursor.execute("DELETE FROM piliers WHERE id = ?", (pilier_id,))
        conn.commit()
        
        return f"🗑️ Pilier supprimé: {existing[0][:60]}..."
        
    except Exception as e:
        conn.rollback()
        return f"Erreur suppression pilier: {e}"
    finally:
        conn.close()