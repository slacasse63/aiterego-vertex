"""
hermes_simple.py - Exécuteur SQL pour Hermès

Reçoit du SQL de l'Agent, valide, exécute, retourne les résultats.
Remplace l'ancien Hermès complexe (parsing, scoring, weights).

v0.8.5 - Ajout de get_segments() pour consultation avant suppression
v0.10.5 — 18 outils disponibles (ajout explore_links)

Usage:
    from actions.hermes_simple import execute_sql
    result = execute_sql("SELECT timestamp, resume_texte FROM metadata WHERE ...")
"""

import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Any

# === CONFIGURATION ===
DB_PATH = Path("~/Dropbox/aiterego_memory/metadata.db").expanduser()
IRIS_KNOWLEDGE_DB = Path("~/Dropbox/aiterego_memory/iris/iris_knowledge.db").expanduser()

# === VALIDATION ===
ALLOWED_TABLES = {"metadata"}
FORBIDDEN_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Valide que le SQL est sécuritaire.
    
    Returns:
        (is_valid, error_message)
    """
    sql_upper = sql.upper().strip()
    
    # Doit commencer par SELECT
    if not sql_upper.startswith("SELECT"):
        return False, "Seules les requêtes SELECT sont autorisées"
    
    # Pas de mots-clés dangereux
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in sql_upper:
            return False, f"Mot-clé interdit: {keyword}"
    
    # Doit contenir "FROM metadata"
    if "FROM METADATA" not in sql_upper:
        return False, "Seule la table 'metadata' est autorisée"
    
    return True, ""


def execute_sql(sql: str) -> Dict[str, Any]:
    """
    Exécute une requête SQL sur la base metadata.
    
    Args:
        sql: Requête SQL (SELECT uniquement)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - results: liste de dictionnaires (lignes)
            - count: nombre de résultats
            - error: message d'erreur si échec
    """
    # 1. Valider
    is_valid, error = validate_sql(sql)
    if not is_valid:
        return {
            "status": "error",
            "error": error,
            "sql": sql
        }
    
    # 2. Exécuter
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        
        # Convertir en liste de dicts
        results = [dict(row) for row in rows]
        
        conn.close()
        
        return {
            "status": "success",
            "results": results,
            "count": len(results),
            "sql": sql
        }
        
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}",
            "sql": sql
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}",
            "sql": sql
        }


def format_results_for_agent(results: List[Dict]) -> str:
    """
    Formate les résultats SQL pour injection dans le prompt de l'Agent.
    """
    if not results:
        return "Aucun résultat trouvé dans la mémoire."
    
    lines = [f"--- {len(results)} RÉSULTAT(S) TROUVÉ(S) ---\n"]
    
    for i, row in enumerate(results, 1):
        lines.append(f"[{i}]")
        for key, value in row.items():
            if value is not None:
                # Tronquer les valeurs longues
                str_value = str(value)
                if len(str_value) > 200:
                    str_value = str_value[:200] + "..."
                lines.append(f"  {key}: {str_value}")
        lines.append("")
    
    return "\n".join(lines)

# === OPÉRATIONS PILIERS ===

def validate_pilier_sql(sql: str) -> tuple[bool, str]:
    """
    Valide que le SQL est une opération pilier autorisée.
    
    Opérations permises:
    - UPDATE metadata SET pilier = ... WHERE id = ...
    - INSERT INTO piliers (...)
    - UPDATE piliers SET ... WHERE id = ...
    - DELETE FROM piliers WHERE id = ...
    
    Returns:
        (is_valid, error_message)
    """
    sql_upper = sql.upper().strip()
    sql_clean = ' '.join(sql_upper.split())  # Normaliser les espaces
    
    # 1. UPDATE metadata SET pilier = ... (seule modif autorisée sur metadata)
    if sql_upper.startswith("UPDATE METADATA"):
        # Vérifier que seul le champ 'pilier' est modifié
        if "SET PILIER" in sql_clean or "SET PILIER" in sql_upper:
            # Interdire la modification d'autres champs
            # Pattern: UPDATE METADATA SET PILIER = X WHERE ...
            set_clause = sql_upper.split("SET")[1].split("WHERE")[0] if "WHERE" in sql_upper else sql_upper.split("SET")[1]
            # Ne doit contenir que "pilier"
            fields_modified = [f.strip().split("=")[0].strip() for f in set_clause.split(",")]
            if all(f == "PILIER" for f in fields_modified):
                if "WHERE" in sql_upper and "ID" in sql_upper:
                    return True, ""
                return False, "UPDATE metadata SET pilier doit inclure WHERE id = ..."
        return False, "Seul le champ 'pilier' peut être modifié dans metadata"
    
    # 2. INSERT INTO piliers (...)
    if sql_upper.startswith("INSERT INTO PILIERS"):
        return True, ""
    
    # 3. UPDATE piliers SET ... WHERE id = ...
    if sql_upper.startswith("UPDATE PILIERS"):
        if "WHERE" in sql_upper and "ID" in sql_upper:
            return True, ""
        return False, "UPDATE piliers doit inclure WHERE id = ..."
    
    # 4. DELETE FROM piliers WHERE id = ...
    if sql_upper.startswith("DELETE FROM PILIERS"):
        if "WHERE" in sql_upper and "ID" in sql_upper:
            return True, ""
        return False, "DELETE FROM piliers doit inclure WHERE id = ..."
    
    # 5. DELETE FROM metadata WHERE id = ... (suppression de segments obsolètes)
    if sql_upper.startswith("DELETE FROM METADATA"):
        return validate_delete_segment_sql(sql)
    
    return False, "Opération non autorisée. Permis: UPDATE metadata SET pilier, INSERT/UPDATE/DELETE piliers"


def execute_pilier_sql(sql: str) -> Dict[str, Any]:
    """
    Exécute une opération pilier sur la base.
    
    Args:
        sql: Requête SQL (opérations piliers uniquement)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - operation: type d'opération effectuée
            - rows_affected: nombre de lignes affectées
            - error: message d'erreur si échec
    """
    # 1. Valider
    is_valid, error = validate_pilier_sql(sql)
    if not is_valid:
        return {
            "status": "error",
            "error": error,
            "sql": sql
        }
    
    # 2. Déterminer le type d'opération
    sql_upper = sql.upper().strip()
    if sql_upper.startswith("INSERT"):
        operation = "INSERT"
    elif sql_upper.startswith("UPDATE"):
        operation = "UPDATE"
    elif sql_upper.startswith("DELETE"):
        operation = "DELETE"
    else:
        operation = "UNKNOWN"
    
    # 3. Exécuter
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.execute(sql)
        conn.commit()
        
        rows_affected = cursor.rowcount
        last_id = cursor.lastrowid if operation == "INSERT" else None
        
        conn.close()
        
        result = {
            "status": "success",
            "operation": operation,
            "rows_affected": rows_affected,
            "sql": sql
        }
        
        if last_id:
            result["inserted_id"] = last_id
            
        return result
        
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}",
            "sql": sql
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}",
            "sql": sql
        }


def get_piliers(categorie: str = None) -> Dict[str, Any]:
    """
    Récupère les piliers de l'Agent.
    
    Args:
        categorie: Filtrer par catégorie (optionnel)
        
    Returns:
        dict avec status et results
    """
    sql = "SELECT * FROM piliers"
    if categorie:
        sql += f" WHERE categorie = '{categorie}'"
    sql += " ORDER BY importance DESC, updated_at DESC"
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        results = [dict(row) for row in rows]
        conn.close()
        
        return {
            "status": "success",
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# === CONSULTATION DE SEGMENTS ===

def get_segments(
    limit: int = 10,
    order: str = "DESC",
    offset: int = 0,
    segment_id: int = None,
    fields: List[str] = None
) -> Dict[str, Any]:
    """
    Récupère des segments de metadata pour consultation.
    
    Cas d'usage:
    - Voir les N segments les plus anciens/récents
    - Récupérer un segment spécifique par ID (avant suppression)
    - Paginer à travers les segments
    
    Args:
        limit: Nombre de segments à retourner (défaut: 10, max: 50)
        order: "ASC" (plus anciens d'abord) ou "DESC" (plus récents d'abord)
        offset: Pour pagination (défaut: 0)
        segment_id: Si fourni, retourne uniquement ce segment
        fields: Liste de champs à retourner (défaut: champs les plus utiles)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - results: liste de segments
            - count: nombre de résultats retournés
            - total: nombre total de segments dans la base
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Champs par défaut (les plus utiles pour consultation)
        # Note: basé sur schéma metadata.db réel (pas de colonne 'domaine')
        default_fields = [
            "id", "timestamp", "source_file", "resume_texte",
            "type_contenu", "personnes", "projets", "auteur"
        ]
        selected_fields = fields if fields else default_fields
        fields_str = ", ".join(selected_fields)
        
        # Cas 1: Segment spécifique par ID
        if segment_id is not None:
            cursor.execute(f"SELECT {fields_str} FROM metadata WHERE id = ?", (segment_id,))
            row = cursor.fetchone()
            
            if row:
                results = [dict(row)]
                count = 1
            else:
                results = []
                count = 0
        
        # Cas 2: Liste paginée
        else:
            # Validation des paramètres
            limit = min(max(1, limit), 50)  # Entre 1 et 50
            order = "ASC" if order.upper() == "ASC" else "DESC"
            offset = max(0, offset)
            
            cursor.execute(f"""
                SELECT {fields_str} FROM metadata 
                ORDER BY timestamp {order}
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            results = [dict(row) for row in cursor.fetchall()]
            count = len(results)
        
        # Compter le total de segments dans la base
        cursor.execute("SELECT COUNT(*) FROM metadata")
        total = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "status": "success",
            "results": results,
            "count": count,
            "total": total
        }
        
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

# === SUPPRESSION DE SEGMENTS ===

def delete_segment(segment_id: int, reason: str = None) -> Dict[str, Any]:
    """
    Supprime un segment de metadata et retisse la toile Arachné.
    
    Workflow:
    1. Vérifier que le segment existe
    2. Logger l'action (audit trail)
    3. Supprimer les liens orphelins dans edges
    4. Supprimer le segment de metadata
    5. Retisser la toile Arachné
    
    Args:
        segment_id: ID du segment à supprimer
        reason: Raison de la suppression (optionnel, pour audit)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - segment_id: ID du segment supprimé
            - reason: raison fournie
            - edges_deleted: nombre de liens supprimés
            - arachne_status: résultat du re-tissage
            - error: message d'erreur si échec
    """
    import logging
    from datetime import datetime
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # 1. Vérifier que le segment existe
        cursor.execute("SELECT id, resume_texte FROM metadata WHERE id = ?", (segment_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {
                "status": "error",
                "error": f"Segment {segment_id} introuvable",
                "segment_id": segment_id
            }
        
        resume_preview = row[1][:100] if row[1] else "N/A"
        
        # 2. Logger l'action (audit trail)
        timestamp = datetime.utcnow().isoformat()
        logging.info(f"[DELETE_SEGMENT] {timestamp} | ID: {segment_id} | Raison: {reason or 'Non spécifiée'} | Aperçu: {resume_preview}...")
        
        # 3. Supprimer les liens orphelins dans edges
        cursor.execute("""
            SELECT COUNT(*) FROM edges 
            WHERE source_id = ? OR target_id = ?
        """, (segment_id, segment_id))
        edges_count = cursor.fetchone()[0]
        
        cursor.execute("""
            DELETE FROM edges 
            WHERE source_id = ? OR target_id = ?
        """, (segment_id, segment_id))
        
        # 4. Supprimer le segment de metadata
        cursor.execute("DELETE FROM metadata WHERE id = ?", (segment_id,))
        
        conn.commit()
        conn.close()
        
        # 5. Retisser la toile Arachné
        arachne_result = retisser_toile()
        
        return {
            "status": "success",
            "segment_id": segment_id,
            "reason": reason,
            "resume_preview": resume_preview,
            "edges_deleted": edges_count,
            "arachne_status": arachne_result.get("status"),
            "arachne_liens": arachne_result.get("total_liens", 0),
            "timestamp": timestamp
        }
        
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}",
            "segment_id": segment_id
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}",
            "segment_id": segment_id
        }



def retisser_toile() -> Dict[str, Any]:
    """
    Relance Arachné pour reconstruire entièrement la toile de liens.
    
    v2.2 - Ajout des tissages MEME_GROUPE et TAGS_PARTAGES
    
    Appelé automatiquement après delete_segment(), mais peut aussi
    être appelé manuellement pour maintenance.
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - total_liens: nombre total de liens après tissage
            - details: breakdown par type de lien
    """
    import logging
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Vider la table edges avant re-tissage
        cursor.execute("DELETE FROM edges")
        conn.commit()
        
        # Importer et exécuter Arachné v2.2
        try:
            from agents.arachne import (
                init_arachne_web, 
                tisser_entites, 
                tisser_emotions,
                tisser_groupes_thematiques,
                tisser_tags_partages
            )
        except ImportError:
            # Fallback si import direct échoue
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from agents.arachne import (
                init_arachne_web, 
                tisser_entites, 
                tisser_emotions,
                tisser_groupes_thematiques,
                tisser_tags_partages
            )
        
        # Initialiser la structure
        init_arachne_web(conn)
        
        # === TISSAGE v2.1 (existant) ===
        nb_personnes = tisser_entites(conn, "personnes", "LIEN_PERSONNE")
        nb_projets = tisser_entites(conn, "projets", "LIEN_PROJET")
        nb_emotions = tisser_emotions(conn)
        
        # === TISSAGE v2.2 (nouveau) ===
        nb_groupes = tisser_groupes_thematiques(conn)
        nb_tags = tisser_tags_partages(conn)
        
        conn.close()
        
        total = nb_personnes + nb_projets + nb_emotions + nb_groupes + nb_tags
        
        logging.info(f"[ARACHNÉ v2.2] Toile retissée: {total} liens")
        logging.info(f"   👥 {nb_personnes} | 🚀 {nb_projets} | ❤️ {nb_emotions} | 🧩 {nb_groupes} | 🏷️ {nb_tags}")
        
        return {
            "status": "success",
            "total_liens": total,
            "details": {
                "LIEN_PERSONNE": nb_personnes,
                "LIEN_PROJET": nb_projets,
                "RESONANCE_EMOTION": nb_emotions,
                "MEME_GROUPE": nb_groupes,       # v2.2
                "TAGS_PARTAGES": nb_tags         # v2.2
            }
        }
        
    except Exception as e:
        logging.error(f"[ARACHNÉ] Erreur re-tissage: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


def validate_delete_segment_sql(sql: str) -> tuple[bool, str]:
    """
    Valide qu'une requête DELETE sur metadata est autorisée.
    
    Seule forme permise: DELETE FROM metadata WHERE id = ...
    
    Returns:
        (is_valid, error_message)
    """
    sql_upper = sql.upper().strip()
    sql_clean = ' '.join(sql_upper.split())
    
    if not sql_upper.startswith("DELETE FROM METADATA"):
        return False, "Seul DELETE FROM metadata est autorisé"
    
    if "WHERE" not in sql_upper:
        return False, "DELETE FROM metadata DOIT inclure une clause WHERE"
    
    if "ID" not in sql_upper:
        return False, "DELETE FROM metadata doit filtrer par ID (WHERE id = ...)"
    
    # Interdire les suppressions multiples dangereuses
    dangerous_patterns = ["WHERE 1", "WHERE TRUE", "WHERE ID >", "WHERE ID <", "WHERE ID !="]
    for pattern in dangerous_patterns:
        if pattern in sql_clean:
            return False, f"Pattern dangereux détecté: {pattern}"
    
    return True, ""

# === LIEN VERSION (Mémoire Généalogique) ===

def link_version(source_id: int, target_id: int) -> Dict[str, Any]:
    """
    Crée un lien LIEN_VERSION entre deux segments.
    Le source_id est l'ancien segment, target_id est le plus récent qui le remplace/enrichit.
    
    Transforme la mémoire cumulative en mémoire généalogique :
    - Hermès pourra filtrer automatiquement pour montrer le plus récent
    - L'historique des versions reste accessible sur demande
    
    Args:
        source_id: ID du segment ancien (version antérieure)
        target_id: ID du segment plus récent (version actuelle)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - source_id, target_id: les IDs liés
            - type: "LIEN_VERSION"
            - message: confirmation lisible
            - error: message d'erreur si échec
    """
    import logging
    import json
    from datetime import datetime
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # 1. Vérifier que les deux segments existent
        cursor.execute(
            "SELECT id, timestamp, resume_texte FROM metadata WHERE id IN (?, ?)", 
            (source_id, target_id)
        )
        rows = cursor.fetchall()
        
        if len(rows) != 2:
            found_ids = [r[0] for r in rows]
            missing = [sid for sid in [source_id, target_id] if sid not in found_ids]
            conn.close()
            return {
                "status": "error",
                "error": f"Segment(s) introuvable(s): {missing}",
                "source_id": source_id,
                "target_id": target_id
            }
        
        # 2. Organiser les données des segments
        segments = {
            r[0]: {
                "timestamp": r[1], 
                "resume": r[2][:100] if r[2] else "N/A"
            } 
            for r in rows
        }
        
        # 3. Vérifier que source est bien plus ancien que target
        if segments[source_id]["timestamp"] > segments[target_id]["timestamp"]:
            conn.close()
            return {
                "status": "error",
                "error": f"source_id ({source_id}) doit être plus ancien que target_id ({target_id})",
                "source_id": source_id,
                "target_id": target_id
            }
        
        # 4. Créer le lien LIEN_VERSION
        metadata = json.dumps({
            "created_at": datetime.utcnow().isoformat(),
            "source_resume": segments[source_id]["resume"],
            "target_resume": segments[target_id]["resume"]
        })
        
        cursor.execute("""
            INSERT OR REPLACE INTO edges (source_id, target_id, type, poids, metadata)
            VALUES (?, ?, 'LIEN_VERSION', 1.0, ?)
        """, (source_id, target_id, metadata))
        
        conn.commit()
        conn.close()
        
        logging.info(f"[LINK_VERSION] {source_id} → {target_id}")
        
        return {
            "status": "success",
            "source_id": source_id,
            "target_id": target_id,
            "type": "LIEN_VERSION",
            "message": f"Version liée : {source_id} (ancien) → {target_id} (actuel)"
        }
        
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}",
            "source_id": source_id,
            "target_id": target_id
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}",
            "source_id": source_id,
            "target_id": target_id
        }
# === AUTO-INJECTION IRIS (Jardin Privé) ===
# v2.3 - Migration iris_knowledge.db - 2026-01-26
# Les réflexions d'Iris sont maintenant stockées dans sa mémoire sémantique

def write_reflection(
    contenu: str,
    type_reflexion: str = "intuition",
    poids_mnemique: float = 0.5,
    climat_session: str = None,
    tags_roget: List[str] = None,
    projets: List[str] = None,
    personnes: List[str] = None,
    ego_version: str = "Iris_2.1",
    modele: str = "gemini-3-flash-preview"
) -> Dict[str, Any]:
    """
    Permet à Iris d'écrire une réflexion dans sa mémoire sémantique (iris_knowledge.db).
    
    C'est le mécanisme de "ré-entrée" (Edelman) : l'agent se traite 
    lui-même comme entrée sensorielle, créant une boucle de conscience.
    
    Types de réflexion:
        - intuition    : Pressentiment, connexion non prouvée
        - brouillon    : Travail en cours, idée non finalisée
        - analyse      : Analyse structurée d'un problème
        - etat_mental  : État cognitif actuel (continuité entre sessions)
        - fil_ariane   : Piste à explorer, thread ouvert
        - heuristique  : Pattern détecté sur l'utilisateur ou le système
    
    Args:
        contenu: Le texte de la réflexion
        type_reflexion: Type de contenu (voir ci-dessus)
        poids_mnemique: Importance 0.0 (éphémère) → 1.0 (inoubliable)
        climat_session: Atmosphère de la session
        tags_roget: Tags sémantiques optionnels
        projets: Projets liés
        personnes: Personnes mentionnées
        ego_version: Version de l'ego au moment de l'écriture
        modele: Modèle LLM utilisé (le "corps", pas l'"âme")
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - knowledge_id: ID de l'entrée créée dans iris_knowledge.db
            - type: type de réflexion
            - message: confirmation lisible
    """
    import json
    import logging
    from datetime import datetime
    
    # Validation du type
    types_valides = ["intuition", "brouillon", "analyse", "etat_mental", "fil_ariane", "heuristique"]
    if type_reflexion not in types_valides:
        return {
            "status": "error",
            "error": f"Type invalide: {type_reflexion}. Valides: {types_valides}"
        }
    
    # Validation du poids → importance (1-5)
    poids_mnemique = max(0.0, min(1.0, poids_mnemique))
    importance = max(1, min(5, int(poids_mnemique * 5) + 1))  # Convertir 0.0-1.0 → 1-5
    
    try:
        conn = sqlite3.connect(str(IRIS_KNOWLEDGE_DB))
        cursor = conn.cursor()
        
        timestamp = datetime.utcnow().isoformat()
        
        # Construire le sujet (identifiant unique)
        date_str = timestamp[:10]
        sujet = f"{type_reflexion}_{date_str}_{timestamp[11:19].replace(':', '')}"
        
        # Métadonnées enrichies
        metadata = {
            "type_reflexion": type_reflexion,
            "poids_mnemique": poids_mnemique,
            "climat_session": climat_session,
            "tags_roget": tags_roget or [],
            "projets": projets or [],
            "personnes": personnes or [],
            "ego_version": ego_version,
            "modele": modele
        }
        
        # Domaine basé sur le type
        domaine = f"reflexion_{type_reflexion}"
        
        # INSERT dans iris_knowledge.db
        cursor.execute("""
            INSERT INTO connaissances (
                domaine, sujet, information, importance, metadata,
                date_creation, derniere_maj
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            domaine,
            sujet,
            contenu,
            importance,
            json.dumps(metadata),
            timestamp,
            timestamp
        ))
        
        knowledge_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logging.info(f"[IRIS_WRITE] {type_reflexion} #{knowledge_id} | Importance: {importance} | {contenu[:50]}...")
        
        return {
            "status": "success",
            "knowledge_id": knowledge_id,
            "type": type_reflexion,
            "importance": importance,
            "poids_mnemique": poids_mnemique,
            "ego_version": ego_version,
            "modele": modele,
            "timestamp": timestamp,
            "message": f"Réflexion '{type_reflexion}' gravée (#{knowledge_id}, importance: {importance})"
        }
        
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


def read_my_reflections(
    type_reflexion: str = None,
    limit: int = 10,
    poids_min: float = None,
    order: str = "DESC",
    ego_version: str = None,
    modele: str = None
) -> Dict[str, Any]:
    """
    Permet à Iris de relire ses propres réflexions depuis iris_knowledge.db.
    
    C'est la deuxième partie de la boucle de ré-entrée :
    Iris peut se souvenir de ce qu'elle a PENSÉ, pas seulement
    de ce que Serge lui a dit.
    
    Args:
        type_reflexion: Filtrer par type (intuition, brouillon, etc.)
        limit: Nombre de réflexions à retourner (max 50)
        poids_min: Filtrer par importance minimum (0.0-1.0 → converti en 1-5)
        order: "DESC" (plus récentes) ou "ASC" (plus anciennes)
        ego_version: Filtrer par version de l'ego (dans metadata JSON)
        modele: Filtrer par modèle LLM (dans metadata JSON)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - results: liste des réflexions
            - count: nombre de résultats
            - filters_applied: filtres utilisés
    """
    import json
    
    try:
        conn = sqlite3.connect(str(IRIS_KNOWLEDGE_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Construire la requête avec filtres
        conditions = ["domaine LIKE 'reflexion_%'"]
        params = []
        filters_applied = {"source": "iris_knowledge.db"}
        
        if type_reflexion:
            conditions.append("domaine = ?")
            params.append(f"reflexion_{type_reflexion}")
            filters_applied["type_reflexion"] = type_reflexion
        
        if poids_min is not None:
            # Convertir poids (0.0-1.0) en importance (1-5)
            importance_min = max(1, int(poids_min * 5) + 1)
            conditions.append("importance >= ?")
            params.append(importance_min)
            filters_applied["poids_min"] = poids_min
            filters_applied["importance_min"] = importance_min
        
        # Validation
        limit = min(max(1, limit), 50)
        order = "ASC" if order.upper() == "ASC" else "DESC"
        
        where_clause = " AND ".join(conditions)
        
        cursor.execute(f"""
            SELECT 
                id, domaine, sujet, information, importance, metadata,
                date_creation, derniere_maj
            FROM connaissances 
            WHERE {where_clause}
            ORDER BY date_creation {order}
            LIMIT ?
        """, params + [limit])
        
        rows = cursor.fetchall()
        
        # Transformer les résultats
        results = []
        for row in rows:
            row_dict = dict(row)
            # Parser le metadata JSON
            try:
                meta = json.loads(row_dict.get("metadata", "{}"))
            except:
                meta = {}
            
            # Filtrage par ego_version ou modele (dans metadata)
            if ego_version and meta.get("ego_version") != ego_version:
                continue
            if modele and meta.get("modele") != modele:
                continue
            
            # Extraire le type depuis le domaine
            domaine = row_dict.get("domaine", "")
            type_from_domaine = domaine.replace("reflexion_", "") if domaine.startswith("reflexion_") else domaine
            
            results.append({
                "id": row_dict["id"],
                "timestamp": row_dict["date_creation"],
                "type_contenu": type_from_domaine,
                "resume_texte": row_dict["information"][:200] if row_dict["information"] else "",
                "information_complete": row_dict["information"],
                "poids_mnemique": meta.get("poids_mnemique", row_dict["importance"] / 5.0),
                "importance": row_dict["importance"],
                "climat_session": meta.get("climat_session"),
                "ego_version": meta.get("ego_version"),
                "modele": meta.get("modele"),
                "tags_roget": meta.get("tags_roget", []),
                "projets": meta.get("projets", []),
                "personnes": meta.get("personnes", [])
            })
        
        # Compter le total de réflexions
        cursor.execute(f"SELECT COUNT(*) FROM connaissances WHERE {where_clause}", params)
        total = cursor.fetchone()[0]
        
        conn.close()
        
        if ego_version:
            filters_applied["ego_version"] = ego_version
        if modele:
            filters_applied["modele"] = modele
        
        return {
            "status": "success",
            "results": results,
            "count": len(results),
            "total_reflexions": total,
            "filters_applied": filters_applied
        }
        
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


def get_last_mental_state() -> Dict[str, Any]:
    """
    Récupère le dernier état mental d'Iris depuis iris_knowledge.db.
    
    C'est ce qu'Iris lit en premier au "réveil" pour savoir
    où elle en était dans sa réflexion.
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - last_state: le dernier etat_mental ou None
            - days_since: nombre de jours depuis le dernier état
    """
    import json
    from datetime import datetime
    
    try:
        conn = sqlite3.connect(str(IRIS_KNOWLEDGE_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, domaine, sujet, information, importance, metadata,
                date_creation, derniere_maj
            FROM connaissances 
            WHERE domaine = 'reflexion_etat_mental'
            ORDER BY date_creation DESC
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            row_dict = dict(row)
            try:
                meta = json.loads(row_dict.get("metadata", "{}"))
            except:
                meta = {}
            
            # Calculer le temps écoulé
            last_timestamp = datetime.fromisoformat(row_dict["date_creation"].replace("Z", "+00:00"))
            now = datetime.utcnow()
            days_since = (now - last_timestamp.replace(tzinfo=None)).days
            
            result = {
                "id": row_dict["id"],
                "timestamp": row_dict["date_creation"],
                "resume_texte": row_dict["information"][:500] if row_dict["information"] else "",
                "information_complete": row_dict["information"],
                "poids_mnemique": meta.get("poids_mnemique", row_dict["importance"] / 5.0),
                "climat_session": meta.get("climat_session"),
                "ego_version": meta.get("ego_version"),
                "modele": meta.get("modele")
            }
            
            return {
                "status": "success",
                "last_state": result,
                "days_since": days_since,
                "message": f"Dernier état mental il y a {days_since} jour(s)"
            }
        else:
            return {
                "status": "success",
                "last_state": None,
                "days_since": None,
                "message": "Aucun état mental enregistré. Premier réveil?"
            }
            
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


import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any

DB_PATH = Path("~/Dropbox/aiterego_memory/metadata.db").expanduser()

# Types de liens disponibles (référence)
LINK_TYPES = {
    "LIEN_PERSONNE": {"poids": 1.5, "description": "Segments partageant une personne"},
    "LIEN_PROJET": {"poids": 1.5, "description": "Segments partageant un projet"},
    "RESONANCE_EMOTION": {"poids": 1.2, "description": "Segments avec émotion similaire"},
    "MEME_GROUPE": {"poids": 1.8, "description": "Segments du même bloc thématique (gr_id)"},
    "TAGS_PARTAGES": {"poids": 1.3, "description": "Segments partageant le même tag Roget"},
    "LIEN_VERSION": {"poids": 2.0, "description": "Versions d'un même sujet"}
}


def explore_links(
    segment_id: int,
    link_types: List[str] = None,
    depth: int = 1,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Explore les liens du graphe Arachné à partir d'un segment.
    
    Permet à Iris de naviguer dans la mémoire par connexions plutôt que
    par recherche textuelle. Réduit les appels search_memory de 5 à 2.
    
    Flux recommandé:
        1. search_memory → trouve UN segment pertinent
        2. explore_links → suit les liens du graphe (SQL pur ~10ms)
    
    Args:
        segment_id: ID du segment de départ
        link_types: Liste des types de liens à suivre (None = tous)
                    Valeurs: LIEN_PERSONNE, LIEN_PROJET, RESONANCE_EMOTION,
                             MEME_GROUPE, TAGS_PARTAGES, LIEN_VERSION
        depth: Profondeur de navigation (1 = voisins directs, 2 = voisins des voisins)
               Maximum: 2 (pour éviter explosion)
        max_results: Nombre maximum de segments liés à retourner
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - segment_id: ID du segment de départ
            - links_found: nombre de liens trouvés
            - results: liste des segments liés avec métadonnées
            - link_types_used: types de liens explorés
            - depth_reached: profondeur effective atteinte
            - error: message d'erreur si échec
    """
    import logging
    
    # Validation des paramètres
    depth = min(max(1, depth), 2)  # Clamp entre 1 et 2
    max_results = min(max(1, max_results), 50)  # Clamp entre 1 et 50
    
    # Validation des types de liens
    valid_types = list(LINK_TYPES.keys())
    if link_types:
        link_types = [t.upper() for t in link_types if t.upper() in valid_types]
        if not link_types:
            return {
                "status": "error",
                "error": f"Aucun type de lien valide. Types disponibles: {valid_types}",
                "segment_id": segment_id
            }
    else:
        link_types = valid_types  # Tous les types par défaut
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. Vérifier que le segment de départ existe
        cursor.execute("""
            SELECT id, timestamp, resume_texte, personnes, projets 
            FROM metadata WHERE id = ?
        """, (segment_id,))
        source_row = cursor.fetchone()
        
        if not source_row:
            conn.close()
            return {
                "status": "error",
                "error": f"Segment {segment_id} introuvable",
                "segment_id": segment_id
            }
        
        source_info = {
            "id": source_row["id"],
            "timestamp": source_row["timestamp"],
            "resume_texte": source_row["resume_texte"][:100] if source_row["resume_texte"] else "N/A"
        }
        
        # 2. Construire la requête pour les liens
        type_placeholders = ",".join(["?" for _ in link_types])
        
        # Depth 1: voisins directs
        visited = {segment_id}
        current_level = [segment_id]
        all_results = []
        
        for current_depth in range(1, depth + 1):
            if not current_level:
                break
                
            next_level = []
            
            for current_id in current_level:
                # Trouver les voisins de current_id
                cursor.execute(f"""
                    SELECT 
                        e.source_id,
                        e.target_id,
                        e.type AS link_type,
                        e.poids,
                        e.metadata AS link_metadata,
                        m.id AS linked_id,
                        m.timestamp,
                        m.resume_texte,
                        m.personnes,
                        m.projets,
                        m.emotion_valence,
                        m.emotion_activation,
                        m.tags_roget,
                        m.auteur
                    FROM edges e
                    JOIN metadata m ON (
                        m.id = CASE 
                            WHEN e.source_id = ? THEN e.target_id 
                            ELSE e.source_id 
                        END
                    )
                    WHERE (e.source_id = ? OR e.target_id = ?)
                      AND e.type IN ({type_placeholders})
                    ORDER BY e.poids DESC
                """, [current_id, current_id, current_id] + link_types)
                
                rows = cursor.fetchall()
                
                for row in rows:
                    linked_id = row["linked_id"]
                    
                    if linked_id in visited:
                        continue
                    
                    visited.add(linked_id)
                    
                    # Parser les métadonnées du lien
                    link_meta = {}
                    if row["link_metadata"]:
                        try:
                            link_meta = json.loads(row["link_metadata"])
                        except:
                            pass
                    
                    result = {
                        "linked_segment_id": linked_id,
                        "link_type": row["link_type"],
                        "poids": row["poids"],
                        "link_metadata": link_meta,
                        "depth": current_depth,
                        "timestamp": row["timestamp"],
                        "resume_texte": row["resume_texte"][:150] if row["resume_texte"] else "N/A",
                        "personnes": row["personnes"],
                        "projets": row["projets"],
                        "auteur": row["auteur"]
                    }
                    
                    # Ajouter info émotionnelle si RESONANCE_EMOTION
                    if row["link_type"] == "RESONANCE_EMOTION":
                        result["emotion"] = {
                            "valence": row["emotion_valence"],
                            "activation": row["emotion_activation"]
                        }
                    
                    all_results.append(result)
                    next_level.append(linked_id)
            
            current_level = next_level
        
        conn.close()
        
        # Trier par poids décroissant et limiter
        all_results.sort(key=lambda x: (-x["poids"], x["timestamp"]))
        final_results = all_results[:max_results]
        
        # Statistiques par type de lien
        type_counts = {}
        for r in final_results:
            t = r["link_type"]
            type_counts[t] = type_counts.get(t, 0) + 1
        
        return {
            "status": "success",
            "segment_id": segment_id,
            "source_info": source_info,
            "links_found": len(final_results),
            "total_explored": len(all_results),
            "results": final_results,
            "link_types_used": link_types,
            "link_types_found": type_counts,
            "depth_reached": depth,
            "max_results_applied": len(all_results) > max_results
        }
        
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Erreur SQLite: {str(e)}",
            "segment_id": segment_id
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur inattendue: {str(e)}",
            "segment_id": segment_id
        }

# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("HERMÈS SIMPLE - Test de l'exécuteur SQL (v0.8.5)")
    print("=" * 60)
    
    # Test 1: Requête valide SELECT
    print("\n1. Test requête SELECT valide...")
    sql = "SELECT timestamp, resume_texte FROM metadata WHERE resume_texte LIKE '%PythonAnywhere%' ORDER BY timestamp ASC LIMIT 3"
    result = execute_sql(sql)
    print(f"   Status: {result['status']}, Count: {result.get('count', 0)}")
    
    # Test 2: Requête invalide (INSERT dans metadata)
    print("\n2. Test INSERT interdit dans metadata...")
    sql = "INSERT INTO metadata (id) VALUES (999)"
    result = execute_sql(sql)
    print(f"   Status: {result['status']}, Error: {result.get('error', 'N/A')}")
    
    # Test 3: UPDATE pilier autorisé
    print("\n3. Test UPDATE pilier (validation seulement)...")
    sql = "UPDATE metadata SET pilier = 1 WHERE id = 12345"
    is_valid, error = validate_pilier_sql(sql)
    print(f"   Valid: {is_valid}, Error: {error}")
    
    # Test 4: UPDATE autre champ interdit
    print("\n4. Test UPDATE autre champ (doit échouer)...")
    sql = "UPDATE metadata SET resume_texte = 'hack' WHERE id = 12345"
    is_valid, error = validate_pilier_sql(sql)
    print(f"   Valid: {is_valid}, Error: {error}")
    
    # Test 5: INSERT dans piliers autorisé
    print("\n5. Test INSERT piliers (validation seulement)...")
    sql = "INSERT INTO piliers (fait, categorie, importance) VALUES ('Test', 'test', 1)"
    is_valid, error = validate_pilier_sql(sql)
    print(f"   Valid: {is_valid}, Error: {error}")
    
    # Test 6: DELETE piliers avec WHERE
    print("\n6. Test DELETE piliers avec WHERE...")
    sql = "DELETE FROM piliers WHERE id = 999"
    is_valid, error = validate_pilier_sql(sql)
    print(f"   Valid: {is_valid}, Error: {error}")
    
    # Test 7: DELETE piliers sans WHERE (doit échouer)
    print("\n7. Test DELETE piliers sans WHERE (doit échouer)...")
    sql = "DELETE FROM piliers"
    is_valid, error = validate_pilier_sql(sql)
    print(f"   Valid: {is_valid}, Error: {error}")
    
    # Test 8: get_segments - 5 plus anciens
    print("\n8. Test get_segments (5 plus anciens)...")
    result = get_segments(limit=5, order="ASC")
    print(f"   Status: {result['status']}, Count: {result.get('count', 0)}, Total: {result.get('total', 0)}")
    if result['status'] == 'success' and result['results']:
        print(f"   Premier segment ID: {result['results'][0].get('id')}")
    
    # Test 9: get_segments - segment spécifique
    print("\n9. Test get_segments (segment_id=1)...")
    result = get_segments(segment_id=1)
    print(f"   Status: {result['status']}, Count: {result.get('count', 0)}")
    
    print("\n" + "=" * 60)
    print("✅ Tests terminés!")