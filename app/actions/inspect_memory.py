"""
inspect_memory.py - Outil d'audit pour les bases de données mémorielles d'Iris

Permet à Iris d'inspecter les données brutes de sa mémoire pour:
- Vérifier la fidélité des résumés de Clio
- Auditer la pertinence des tags Roget
- Repérer les doublons et erreurs de marquage
- Préparer le travail de Mnémosyne

v1.0.1 - 2026-01-16 - Fix schéma (source_nature au lieu de type_contenu)

Emplacement: app/actions/inspect_memory.py

Usage:
    from actions.inspect_memory import inspect_memory
    result = inspect_memory(database="episodic", limit=50, order="recent")
"""

import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional

# === CONFIGURATION ===
# Base épisodique (metadata.db) - segments de Clio
EPISODIC_DB = Path("~/Dropbox/aiterego_memory/metadata.db").expanduser()

# Base sémantique (iris_knowledge.db) - connaissances structurées
SEMANTIC_DB = Path("~/Dropbox/aiterego_memory/iris/iris_knowledge.db").expanduser()


def inspect_memory(
    database: str = "episodic",
    limit: int = 50,
    offset: int = 0,
    order: str = "recent",
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Inspecte les données brutes des bases mémorielles pour audit.
    
    Args:
        database: "episodic" (metadata.db) ou "semantic" (iris_knowledge.db)
        limit: Nombre de lignes à retourner (défaut: 50, max: 100)
        offset: Pour pagination (défaut: 0)
        order: "recent" (DESC par date) ou "oldest" (ASC par date)
        filters: Filtres optionnels {
            "auteur": str,           # Filtrer par auteur (ex: "iris_internal")
            "source_nature": str,    # Filtrer par nature (trace, document, reflexion)
            "date_from": str,        # Date minimale (YYYY-MM-DD)
            "date_to": str,          # Date maximale (YYYY-MM-DD)
            "has_tags": bool,        # Seulement ceux avec tags Roget
            "search_resume": str     # Recherche dans resume_texte
        }
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - database: nom de la base inspectée
            - total_records: nombre total d'enregistrements
            - returned: nombre retourné
            - offset: offset utilisé
            - results: liste des enregistrements bruts
            - schema: colonnes disponibles
            - quality_metrics: métriques de qualité (si episodic)
    """
    # Validation des paramètres
    if database not in ("episodic", "semantic"):
        return {
            "status": "error",
            "error": f"Base inconnue: {database}. Utiliser 'episodic' ou 'semantic'."
        }
    
    limit = min(max(1, limit), 100)  # Clamp entre 1 et 100
    offset = max(0, offset)
    order_sql = "DESC" if order == "recent" else "ASC"
    
    db_path = EPISODIC_DB if database == "episodic" else SEMANTIC_DB
    
    if not db_path.exists():
        return {
            "status": "error",
            "error": f"Base non trouvée: {db_path}"
        }
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if database == "episodic":
            return _inspect_episodic(cursor, conn, limit, offset, order_sql, filters)
        else:
            return _inspect_semantic(cursor, conn, limit, offset, order_sql, filters)
            
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}"
        }
    finally:
        if 'conn' in locals():
            conn.close()


def _inspect_episodic(
    cursor, conn, limit: int, offset: int, order_sql: str, 
    filters: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Inspection de la base épisodique (metadata.db).
    Schéma réel: id, timestamp, source_file, source_nature, auteur, 
                 emotion_valence, emotion_activation, tags_roget,
                 personnes, projets, sujets, resume_texte, gr_id,
                 pilier, vecteur_trildasa, poids_mnemique, etc.
    """
    # Obtenir le schéma
    cursor.execute("PRAGMA table_info(metadata)")
    schema = [col[1] for col in cursor.fetchall()]
    
    # Compter le total
    cursor.execute("SELECT COUNT(*) FROM metadata")
    total = cursor.fetchone()[0]
    
    # Construire la requête avec filtres
    where_clauses = []
    params = []
    
    if filters:
        if filters.get("auteur"):
            where_clauses.append("auteur = ?")
            params.append(filters["auteur"])
        
        if filters.get("source_nature"):
            where_clauses.append("source_nature = ?")
            params.append(filters["source_nature"])
        
        if filters.get("date_from"):
            where_clauses.append("DATE(timestamp) >= ?")
            params.append(filters["date_from"])
        
        if filters.get("date_to"):
            where_clauses.append("DATE(timestamp) <= ?")
            params.append(filters["date_to"])
        
        if filters.get("has_tags"):
            where_clauses.append("tags_roget IS NOT NULL AND tags_roget != '' AND tags_roget != '[]'")
        
        if filters.get("search_resume"):
            where_clauses.append("resume_texte LIKE ?")
            params.append(f"%{filters['search_resume']}%")
    
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    
    # Requête principale - colonnes du schéma réel
    sql = f"""
        SELECT 
            id,
            timestamp,
            source_file,
            source_nature,
            source_origine,
            auteur,
            emotion_valence,
            emotion_activation,
            tags_roget,
            personnes,
            projets,
            sujets,
            resume_texte,
            gr_id,
            pilier,
            poids_mnemique,
            confidence_score
        FROM metadata
        {where_sql}
        ORDER BY timestamp {order_sql}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    
    # Calculer des métriques de qualité
    quality_metrics = _compute_quality_metrics(cursor, where_sql, params[:-2] if len(params) > 2 else [])
    
    return {
        "status": "success",
        "database": "episodic (metadata.db)",
        "total_records": total,
        "returned": len(results),
        "offset": offset,
        "order": "recent → oldest" if order_sql == "DESC" else "oldest → recent",
        "filters_applied": filters or {},
        "schema": schema,
        "quality_metrics": quality_metrics,
        "results": results
    }


def _inspect_semantic(
    cursor, conn, limit: int, offset: int, order_sql: str,
    filters: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Inspection de la base sémantique (iris_knowledge.db).
    Structure variable selon l'implémentation.
    """
    # Lister les tables disponibles
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    
    if not tables:
        return {
            "status": "success",
            "database": "semantic (iris_knowledge.db)",
            "warning": "Base vide ou non initialisée",
            "tables": []
        }
    
    # Inspecter chaque table
    table_info = {}
    all_results = []
    
    for table in tables:
        # Schéma
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Compter
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        
        table_info[table] = {
            "columns": columns,
            "count": count
        }
        
        # Échantillon de la table principale (si existe)
        if count > 0:
            # Chercher une colonne de date pour l'ordre
            date_col = None
            for col in columns:
                if 'date' in col.lower() or 'time' in col.lower() or 'created' in col.lower():
                    date_col = col
                    break
            
            order_clause = f"ORDER BY {date_col} {order_sql}" if date_col else ""
            cursor.execute(f"SELECT * FROM {table} {order_clause} LIMIT ? OFFSET ?", [limit, offset])
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                record['_table'] = table
                all_results.append(record)
    
    return {
        "status": "success",
        "database": "semantic (iris_knowledge.db)",
        "tables": table_info,
        "returned": len(all_results),
        "offset": offset,
        "results": all_results
    }


def _compute_quality_metrics(cursor, where_sql: str, params: List) -> Dict[str, Any]:
    """
    Calcule des métriques de qualité pour l'audit.
    """
    metrics = {}
    
    try:
        # Segments sans résumé
        base_where = where_sql.replace("WHERE", "WHERE (resume_texte IS NULL OR resume_texte = '' OR LENGTH(resume_texte) < 10) AND") if where_sql else "WHERE (resume_texte IS NULL OR resume_texte = '' OR LENGTH(resume_texte) < 10)"
        cursor.execute(f"SELECT COUNT(*) FROM metadata {base_where}", params)
        metrics["segments_sans_resume"] = cursor.fetchone()[0]
        
        # Segments sans tags Roget
        base_where = where_sql.replace("WHERE", "WHERE (tags_roget IS NULL OR tags_roget = '' OR tags_roget = '[]') AND") if where_sql else "WHERE (tags_roget IS NULL OR tags_roget = '' OR tags_roget = '[]')"
        cursor.execute(f"SELECT COUNT(*) FROM metadata {base_where}", params)
        metrics["segments_sans_tags"] = cursor.fetchone()[0]
        
        # Segments sans personnes détectées
        base_where = where_sql.replace("WHERE", "WHERE (personnes IS NULL OR personnes = '' OR personnes = '[]') AND") if where_sql else "WHERE (personnes IS NULL OR personnes = '' OR personnes = '[]')"
        cursor.execute(f"SELECT COUNT(*) FROM metadata {base_where}", params)
        metrics["segments_sans_personnes"] = cursor.fetchone()[0]
        
        # Distribution par source_nature
        cursor.execute(f"""
            SELECT source_nature, COUNT(*) as cnt 
            FROM metadata 
            {where_sql}
            GROUP BY source_nature 
            ORDER BY cnt DESC 
            LIMIT 10
        """, params)
        metrics["distribution_nature"] = {row[0] or "null": row[1] for row in cursor.fetchall()}
        
        # Distribution par auteur
        cursor.execute(f"""
            SELECT auteur, COUNT(*) as cnt 
            FROM metadata 
            {where_sql}
            GROUP BY auteur 
            ORDER BY cnt DESC 
            LIMIT 10
        """, params)
        metrics["distribution_auteurs"] = {row[0] or "null": row[1] for row in cursor.fetchall()}
        
        # Émotion valence moyenne
        cursor.execute(f"""
            SELECT AVG(emotion_valence) 
            FROM metadata 
            {where_sql + ' AND' if where_sql else 'WHERE'} 
            emotion_valence IS NOT NULL
        """, params)
        avg = cursor.fetchone()[0]
        metrics["emotion_valence_moyenne"] = round(avg, 3) if avg else None
        
        # Doublons potentiels (même résumé)
        cursor.execute(f"""
            SELECT resume_texte, COUNT(*) as cnt 
            FROM metadata 
            {where_sql + ' AND' if where_sql else 'WHERE'} 
            resume_texte IS NOT NULL AND resume_texte != ''
            GROUP BY resume_texte 
            HAVING cnt > 1 
            LIMIT 5
        """, params)
        doublons = cursor.fetchall()
        metrics["doublons_potentiels"] = len(doublons)
        if doublons:
            metrics["exemples_doublons"] = [
                {"resume": row[0][:100] + "..." if len(row[0]) > 100 else row[0], "count": row[1]} 
                for row in doublons[:3]
            ]
        
    except Exception as e:
        metrics["_error"] = f"Erreur calcul métriques: {str(e)}"
    
    return metrics


# === POINT D'ENTRÉE POUR TESTS ===
if __name__ == "__main__":
    import json
    
    print("=" * 70)
    print("INSPECT_MEMORY - Test de l'outil d'audit")
    print("=" * 70)
    
    # Test 1: Inspection épisodique - 10 plus récents
    print("\n1. Test episodic - 10 plus récents...")
    result = inspect_memory(database="episodic", limit=10, order="recent")
    print(f"   Status: {result['status']}")
    print(f"   Total: {result.get('total_records', '?')}")
    print(f"   Retournés: {result.get('returned', '?')}")
    if result.get('quality_metrics'):
        print(f"   Sans résumé: {result['quality_metrics'].get('segments_sans_resume', '?')}")
        print(f"   Sans tags: {result['quality_metrics'].get('segments_sans_tags', '?')}")
        print(f"   Doublons: {result['quality_metrics'].get('doublons_potentiels', '?')}")
    
    print("\n" + "=" * 70)
    print("✅ Tests terminés!")
