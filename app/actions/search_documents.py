"""
search_documents.py - Recherche dans l'index des fichiers Dropbox
MOSS v0.11 - Session 82

Permet à Iris de chercher dans les ~22K fichiers indexés avec résumés Mistral.
Utilise FTS5 pour la recherche textuelle performante.

Base: ~/Dropbox/aiterego_memory/index/file_index.db
Table: files (avec FTS5 via files_fts)
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Chemin de la base file_index.db
FILE_INDEX_DB = Path.home() / "Dropbox" / "aiterego_memory" / "index" / "file_index.db"


def search_documents(
    query: str,
    domain: Optional[str] = None,
    extension: Optional[str] = None,
    limit: int = 10,
    min_importance: int = 1
) -> Dict[str, Any]:
    """
    Recherche dans l'index des fichiers Dropbox.
    
    Args:
        query: Mots-clés à chercher (dans path, name, summary, keywords)
        domain: Filtrer par domaine (personnel, recherche, technique, administratif, créatif)
        extension: Filtrer par extension (.pdf, .docx, .md, etc.)
        limit: Nombre maximum de résultats (défaut: 10, max: 50)
        min_importance: Importance minimale (1-5, défaut: 1)
    
    Returns:
        Dict avec status, results, count, query_info
    """
    if not query:
        return {"status": "error", "error": "Paramètre 'query' manquant"}
    
    if not FILE_INDEX_DB.exists():
        return {"status": "error", "error": f"Base file_index.db introuvable: {FILE_INDEX_DB}"}
    
    # Limiter pour éviter les abus
    limit = min(limit, 50)
    
    logger.info(f"🔍 search_documents: query='{query}', domain={domain}, ext={extension}, limit={limit}")
    
    try:
        conn = sqlite3.connect(str(FILE_INDEX_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Construire la requête FTS5
        # On cherche dans files_fts (path_display, name, summary, keywords)
        fts_query = _prepare_fts_query(query)
        
        # Requête SQL avec jointure FTS5
        sql = """
            SELECT 
                f.id,
                f.file_id,
                f.path_display,
                f.name,
                f.extension,
                f.size,
                f.domain,
                f.summary,
                f.keywords,
                f.importance,
                f.status,
                f.server_modified,
                f.enriched_at
            FROM files f
            JOIN files_fts fts ON f.id = fts.rowid
            WHERE files_fts MATCH ?
        """
        params = [fts_query]
        
        # Filtres optionnels
        if domain:
            sql += " AND f.domain = ?"
            params.append(domain.lower())
        
        if extension:
            # Normaliser l'extension (avec ou sans point)
            ext = extension if extension.startswith('.') else f".{extension}"
            sql += " AND f.extension = ?"
            params.append(ext.lower())
        
        if min_importance > 1:
            sql += " AND f.importance >= ?"
            params.append(min_importance)
        
        # Trier par pertinence FTS5 (rank) puis importance
        sql += " ORDER BY rank, f.importance DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # Formater les résultats
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "path": row["path_display"],
                "name": row["name"],
                "extension": row["extension"],
                "size": row["size"],
                "size_human": _human_size(row["size"]),
                "domain": row["domain"],
                "summary": row["summary"][:500] if row["summary"] else None,  # Tronquer
                "keywords": row["keywords"],
                "importance": row["importance"],
                "status": row["status"],
                "modified": row["server_modified"],
                "enriched": row["enriched_at"]
            })
        
        conn.close()
        
        # Construire le résumé textuel pour Iris
        summary = _format_results_for_iris(results, query, domain, extension)
        
        return {
            "status": "success",
            "count": len(results),
            "results": results,
            "summary": summary,
            "query_info": {
                "query": query,
                "fts_query": fts_query,
                "domain": domain,
                "extension": extension,
                "limit": limit
            }
        }
        
    except sqlite3.OperationalError as e:
        error_msg = str(e)
        logger.error(f"Erreur SQL search_documents: {error_msg}")
        
        # Si FTS5 échoue, fallback sur LIKE
        if "no such table: files_fts" in error_msg or "fts5" in error_msg.lower():
            logger.warning("FTS5 indisponible, fallback sur LIKE")
            return _search_with_like(query, domain, extension, limit, min_importance)
        
        return {"status": "error", "error": f"Erreur SQL: {error_msg}"}
        
    except Exception as e:
        logger.error(f"Erreur search_documents: {e}")
        return {"status": "error", "error": str(e)}


def _prepare_fts_query(query: str) -> str:
    """
    Prépare la requête pour FTS5.
    Gère les espaces, caractères spéciaux, et ajoute des wildcards.
    """
    # Nettoyer et séparer les mots
    words = query.strip().split()
    
    # Pour chaque mot, ajouter un wildcard si pas déjà présent
    fts_terms = []
    for word in words:
        # Échapper les caractères spéciaux FTS5
        clean = word.replace('"', '').replace("'", "").replace('*', '')
        if clean:
            # Ajouter wildcard pour recherche préfixe
            fts_terms.append(f'"{clean}"*')
    
    # Combiner avec OR pour être plus permissif
    return " OR ".join(fts_terms) if fts_terms else query


def _search_with_like(
    query: str,
    domain: Optional[str],
    extension: Optional[str],
    limit: int,
    min_importance: int
) -> Dict[str, Any]:
    """
    Fallback si FTS5 n'est pas disponible.
    Utilise LIKE classique (plus lent mais fonctionne toujours).
    """
    try:
        conn = sqlite3.connect(str(FILE_INDEX_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Requête avec LIKE
        sql = """
            SELECT 
                id, file_id, path_display, name, extension, size,
                domain, summary, keywords, importance, status,
                server_modified, enriched_at
            FROM files
            WHERE (
                path_display LIKE ? 
                OR name LIKE ? 
                OR summary LIKE ? 
                OR keywords LIKE ?
            )
        """
        like_pattern = f"%{query}%"
        params = [like_pattern, like_pattern, like_pattern, like_pattern]
        
        if domain:
            sql += " AND domain = ?"
            params.append(domain.lower())
        
        if extension:
            ext = extension if extension.startswith('.') else f".{extension}"
            sql += " AND extension = ?"
            params.append(ext.lower())
        
        if min_importance > 1:
            sql += " AND importance >= ?"
            params.append(min_importance)
        
        sql += " ORDER BY importance DESC, server_modified DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "path": row["path_display"],
                "name": row["name"],
                "extension": row["extension"],
                "size": row["size"],
                "size_human": _human_size(row["size"]),
                "domain": row["domain"],
                "summary": row["summary"][:500] if row["summary"] else None,
                "keywords": row["keywords"],
                "importance": row["importance"],
                "status": row["status"],
                "modified": row["server_modified"],
                "enriched": row["enriched_at"]
            })
        
        conn.close()
        
        summary = _format_results_for_iris(results, query, domain, extension)
        
        return {
            "status": "success",
            "count": len(results),
            "results": results,
            "summary": summary,
            "query_info": {
                "query": query,
                "method": "LIKE (fallback)",
                "domain": domain,
                "extension": extension
            }
        }
        
    except Exception as e:
        return {"status": "error", "error": f"Erreur LIKE fallback: {e}"}


def _human_size(size: Optional[int]) -> str:
    """Convertit une taille en octets en format lisible."""
    if not size:
        return "?"
    for unit in ['o', 'Ko', 'Mo', 'Go']:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'o' else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} To"


def _format_results_for_iris(
    results: List[Dict],
    query: str,
    domain: Optional[str],
    extension: Optional[str]
) -> str:
    """
    Formate les résultats en texte lisible pour Iris.
    """
    if not results:
        filters = []
        if domain:
            filters.append(f"domaine={domain}")
        if extension:
            filters.append(f"extension={extension}")
        filter_str = f" (filtres: {', '.join(filters)})" if filters else ""
        return f"Aucun document trouvé pour '{query}'{filter_str}."
    
    lines = [f"📚 {len(results)} document(s) trouvé(s) pour '{query}':\n"]
    
    for i, doc in enumerate(results, 1):
        # Ligne principale
        importance_stars = "⭐" * (doc.get("importance") or 3)
        status_icon = "✅" if doc.get("status") == "enriched" else "⏳"
        
        lines.append(f"{i}. **{doc['name']}** {importance_stars} {status_icon}")
        lines.append(f"   📁 {doc['path']}")
        lines.append(f"   📊 {doc['size_human']} | {doc.get('domain', '?')} | {doc.get('extension', '?')}")
        
        # Résumé (tronqué)
        if doc.get("summary"):
            summary_short = doc["summary"][:200] + "..." if len(doc["summary"]) > 200 else doc["summary"]
            lines.append(f"   📝 {summary_short}")
        
        # Mots-clés
        if doc.get("keywords"):
            lines.append(f"   🏷️ {doc['keywords']}")
        
        lines.append("")  # Ligne vide entre résultats
    
    return "\n".join(lines)


def get_document_stats() -> Dict[str, Any]:
    """
    Retourne des statistiques sur l'index des documents.
    Utile pour le debugging et le monitoring.
    """
    if not FILE_INDEX_DB.exists():
        return {"status": "error", "error": "Base introuvable"}
    
    try:
        conn = sqlite3.connect(str(FILE_INDEX_DB))
        cursor = conn.cursor()
        
        stats = {}
        
        # Total
        cursor.execute("SELECT COUNT(*) FROM files")
        stats["total"] = cursor.fetchone()[0]
        
        # Par statut
        cursor.execute("SELECT status, COUNT(*) FROM files GROUP BY status")
        stats["by_status"] = dict(cursor.fetchall())
        
        # Par domaine
        cursor.execute("SELECT domain, COUNT(*) FROM files WHERE domain IS NOT NULL GROUP BY domain")
        stats["by_domain"] = dict(cursor.fetchall())
        
        # Par extension (top 10)
        cursor.execute("""
            SELECT extension, COUNT(*) as cnt 
            FROM files 
            WHERE extension IS NOT NULL 
            GROUP BY extension 
            ORDER BY cnt DESC 
            LIMIT 10
        """)
        stats["top_extensions"] = dict(cursor.fetchall())
        
        conn.close()
        
        return {"status": "success", "stats": stats}
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Test standalone
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test stats
    print("=== Stats ===")
    stats = get_document_stats()
    print(stats)
    
    # Test recherche
    print("\n=== Recherche 'brevet' ===")
    result = search_documents("brevet", limit=5)
    print(result.get("summary", result))
