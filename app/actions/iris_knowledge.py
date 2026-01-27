"""
iris_knowledge.py - Mémoire sémantique d'Iris
MOSS v0.11.1 - Session 73

Ce module gère iris_knowledge.db, la base de connaissances personnelle d'Iris.
C'est son "savoir acquis" (mémoire sémantique), distinct de metadata.db
qui est sa "mémoire vécue" (mémoire épisodique).

Outils disponibles:
    - store_fact: Ajouter ou mettre à jour un fait
    - query_facts: Rechercher des faits
    - delete_fact: Supprimer un fait

Territoire exclusif d'Iris - elle seule peut gérer cette base.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# === CONFIGURATION ===
IRIS_KNOWLEDGE_DB = Path.home() / "Dropbox" / "aiterego_memory" / "iris" / "iris_knowledge.db"
SCHEMA_PATH = Path(__file__).parent / "create_iris_knowledge.sql"


def _get_connection() -> sqlite3.Connection:
    """Obtient une connexion à la base iris_knowledge.db."""
    # Créer le dossier si nécessaire
    IRIS_KNOWLEDGE_DB.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(IRIS_KNOWLEDGE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db():
    """Initialise la base de données si elle n'existe pas."""
    if IRIS_KNOWLEDGE_DB.exists():
        return
    
    conn = _get_connection()
    try:
        # Créer la structure
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS connaissances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domaine TEXT NOT NULL,
                sujet TEXT NOT NULL,
                information TEXT NOT NULL,
                importance INTEGER DEFAULT 3 CHECK (importance >= 1 AND importance <= 5),
                metadata JSON,
                source_id INTEGER,
                date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                derniere_maj TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domaine, sujet)
            );
            
            CREATE INDEX IF NOT EXISTS idx_domaine ON connaissances(domaine);
            CREATE INDEX IF NOT EXISTS idx_sujet ON connaissances(sujet);
            CREATE INDEX IF NOT EXISTS idx_importance ON connaissances(importance DESC);
            
            CREATE VIRTUAL TABLE IF NOT EXISTS connaissances_fts USING fts5(
                sujet,
                information,
                content='connaissances',
                content_rowid='id'
            );
            
            CREATE TRIGGER IF NOT EXISTS connaissances_ai AFTER INSERT ON connaissances BEGIN
                INSERT INTO connaissances_fts(rowid, sujet, information) 
                VALUES (new.id, new.sujet, new.information);
            END;
            
            CREATE TRIGGER IF NOT EXISTS connaissances_ad AFTER DELETE ON connaissances BEGIN
                INSERT INTO connaissances_fts(connaissances_fts, rowid, sujet, information) 
                VALUES ('delete', old.id, old.sujet, old.information);
            END;
            
            CREATE TRIGGER IF NOT EXISTS connaissances_au AFTER UPDATE ON connaissances BEGIN
                INSERT INTO connaissances_fts(connaissances_fts, rowid, sujet, information) 
                VALUES ('delete', old.id, old.sujet, old.information);
                INSERT INTO connaissances_fts(rowid, sujet, information) 
                VALUES (new.id, new.sujet, new.information);
            END;
        """)
        conn.commit()
    finally:
        conn.close()


# === OUTILS IRIS ===

def store_fact(
    domaine: str,
    sujet: str,
    information: str,
    importance: int = 3,
    metadata: Optional[Dict[str, Any]] = None,
    source_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Ajoute ou met à jour un fait dans la mémoire sémantique d'Iris.
    
    Si le couple (domaine, sujet) existe déjà, met à jour l'information.
    
    Args:
        domaine: Catégorie large (personnel, projet_MOSS, technique, preferences)
        sujet: Mot-clé ou titre du fait (anniversaire_serge, cafe_prefere)
        information: Le contenu du savoir à retenir
        importance: Score de 1 à 5 (défaut: 3)
        metadata: Dictionnaire flexible pour détails additionnels
        source_id: Référence optionnelle vers metadata.db
    
    Returns:
        Dict avec statut, id, et action (created/updated)
    
    Exemple:
        {"tool": "store_fact", "args": {
            "domaine": "personnel",
            "sujet": "anniversaire_serge",
            "information": "Serge est né le 9 janvier 1963, il a 62 ans en 2025",
            "importance": 5
        }}
    """
    _init_db()
    
    # Valider importance
    importance = max(1, min(5, importance))
    
    # Sérialiser metadata
    metadata_json = json.dumps(metadata) if metadata else None
    
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        
        # Vérifier si le fait existe déjà
        cursor.execute(
            "SELECT id FROM connaissances WHERE domaine = ? AND sujet = ?",
            (domaine, sujet)
        )
        existing = cursor.fetchone()
        
        now = datetime.now().isoformat()
        
        if existing:
            # Mise à jour
            cursor.execute("""
                UPDATE connaissances 
                SET information = ?, importance = ?, metadata = ?, 
                    source_id = ?, derniere_maj = ?
                WHERE id = ?
            """, (information, importance, metadata_json, source_id, now, existing['id']))
            conn.commit()
            
            return {
                "status": "success",
                "action": "updated",
                "id": existing['id'],
                "domaine": domaine,
                "sujet": sujet,
                "message": f"Fait mis à jour: {domaine}/{sujet}"
            }
        else:
            # Insertion
            cursor.execute("""
                INSERT INTO connaissances 
                (domaine, sujet, information, importance, metadata, source_id, derniere_maj)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (domaine, sujet, information, importance, metadata_json, source_id, now))
            conn.commit()
            
            return {
                "status": "success",
                "action": "created",
                "id": cursor.lastrowid,
                "domaine": domaine,
                "sujet": sujet,
                "message": f"Nouveau fait créé: {domaine}/{sujet}"
            }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        conn.close()


def query_facts(
    domaine: Optional[str] = None,
    sujet: Optional[str] = None,
    search: Optional[str] = None,
    min_importance: int = 1,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Recherche des faits dans la mémoire sémantique d'Iris.
    
    Args:
        domaine: Filtrer par domaine (optionnel)
        sujet: Filtrer par sujet exact (optionnel)
        search: Recherche full-text dans sujet et information (optionnel)
        min_importance: Importance minimale (défaut: 1)
        limit: Nombre max de résultats (défaut: 10)
    
    Returns:
        Dict avec liste des faits trouvés
    
    Exemples:
        {"tool": "query_facts", "args": {"domaine": "personnel"}}
        {"tool": "query_facts", "args": {"search": "anniversaire"}}
        {"tool": "query_facts", "args": {"min_importance": 4}}
    """
    _init_db()
    
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        
        if search:
            # Recherche full-text
            cursor.execute("""
                SELECT c.* FROM connaissances c
                JOIN connaissances_fts fts ON c.id = fts.rowid
                WHERE connaissances_fts MATCH ?
                AND c.importance >= ?
                ORDER BY c.importance DESC, c.derniere_maj DESC
                LIMIT ?
            """, (search, min_importance, limit))
        else:
            # Recherche par filtres
            query = "SELECT * FROM connaissances WHERE importance >= ?"
            params = [min_importance]
            
            if domaine:
                query += " AND domaine = ?"
                params.append(domaine)
            
            if sujet:
                query += " AND sujet = ?"
                params.append(sujet)
            
            query += " ORDER BY importance DESC, derniere_maj DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
        
        rows = cursor.fetchall()
        
        facts = []
        for row in rows:
            fact = {
                "id": row['id'],
                "domaine": row['domaine'],
                "sujet": row['sujet'],
                "information": row['information'],
                "importance": row['importance'],
                "derniere_maj": row['derniere_maj']
            }
            if row['metadata']:
                fact['metadata'] = json.loads(row['metadata'])
            if row['source_id']:
                fact['source_id'] = row['source_id']
            facts.append(fact)
        
        return {
            "status": "success",
            "count": len(facts),
            "facts": facts
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        conn.close()


def delete_fact(
    id: Optional[int] = None,
    domaine: Optional[str] = None,
    sujet: Optional[str] = None
) -> Dict[str, Any]:
    """
    Supprime un fait de la mémoire sémantique d'Iris.
    
    Peut supprimer par id OU par couple (domaine, sujet).
    
    Args:
        id: ID du fait à supprimer (optionnel)
        domaine: Domaine du fait (requis si pas d'id)
        sujet: Sujet du fait (requis si pas d'id)
    
    Returns:
        Dict avec statut de la suppression
    
    Exemples:
        {"tool": "delete_fact", "args": {"id": 42}}
        {"tool": "delete_fact", "args": {"domaine": "personnel", "sujet": "ancien_telephone"}}
    """
    _init_db()
    
    if not id and not (domaine and sujet):
        return {
            "status": "error",
            "error": "Spécifier id OU (domaine + sujet)"
        }
    
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        
        if id:
            # Récupérer info avant suppression
            cursor.execute("SELECT domaine, sujet FROM connaissances WHERE id = ?", (id,))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "error": f"Fait id={id} non trouvé"}
            
            cursor.execute("DELETE FROM connaissances WHERE id = ?", (id,))
            deleted_info = f"{row['domaine']}/{row['sujet']}"
        else:
            # Vérifier existence
            cursor.execute(
                "SELECT id FROM connaissances WHERE domaine = ? AND sujet = ?",
                (domaine, sujet)
            )
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "error": f"Fait {domaine}/{sujet} non trouvé"}
            
            cursor.execute(
                "DELETE FROM connaissances WHERE domaine = ? AND sujet = ?",
                (domaine, sujet)
            )
            deleted_info = f"{domaine}/{sujet}"
        
        conn.commit()
        
        return {
            "status": "success",
            "deleted": deleted_info,
            "message": f"Fait supprimé: {deleted_info}"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
    finally:
        conn.close()


def get_stats() -> Dict[str, Any]:
    """
    Retourne des statistiques sur la mémoire sémantique d'Iris.
    
    Utile pour qu'Iris puisse voir l'état de sa base de connaissances.
    """
    _init_db()
    
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        
        # Total
        cursor.execute("SELECT COUNT(*) as total FROM connaissances")
        total = cursor.fetchone()['total']
        
        # Par domaine
        cursor.execute("""
            SELECT domaine, COUNT(*) as count 
            FROM connaissances 
            GROUP BY domaine 
            ORDER BY count DESC
        """)
        par_domaine = {row['domaine']: row['count'] for row in cursor.fetchall()}
        
        # Par importance
        cursor.execute("""
            SELECT importance, COUNT(*) as count 
            FROM connaissances 
            GROUP BY importance 
            ORDER BY importance DESC
        """)
        par_importance = {row['importance']: row['count'] for row in cursor.fetchall()}
        
        # Dernière mise à jour
        cursor.execute("SELECT MAX(derniere_maj) as last FROM connaissances")
        last_update = cursor.fetchone()['last']
        
        return {
            "status": "success",
            "total_faits": total,
            "par_domaine": par_domaine,
            "par_importance": par_importance,
            "derniere_maj": last_update,
            "db_path": str(IRIS_KNOWLEDGE_DB)
        }
    
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e)
        }
    finally:
        conn.close()


# === TEST ===
if __name__ == "__main__":
    print("=== Test iris_knowledge.py ===\n")
    
    # Test store_fact
    print("1. store_fact (création)")
    result = store_fact(
        domaine="personnel",
        sujet="test_anniversaire",
        information="Ceci est un test - anniversaire le 9 janvier",
        importance=5,
        metadata={"contexte": "test session 73"}
    )
    print(f"   → {result}\n")
    
    # Test query_facts
    print("2. query_facts (recherche)")
    result = query_facts(domaine="personnel")
    print(f"   → {result}\n")
    
    # Test query_facts full-text
    print("3. query_facts (full-text)")
    result = query_facts(search="anniversaire")
    print(f"   → {result}\n")
    
    # Test get_stats
    print("4. get_stats")
    result = get_stats()
    print(f"   → {result}\n")
    
    # Test delete_fact
    print("5. delete_fact")
    result = delete_fact(domaine="personnel", sujet="test_anniversaire")
    print(f"   → {result}\n")
    
    print("✅ Tests terminés!")
