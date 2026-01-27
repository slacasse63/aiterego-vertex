"""
arachne.py - v2.2 (MOSS Module)
"La Toile Complète : Cohésion thématique + Résonance sémantique"

Session 63 - Ajout des liens demandés par Iris :
- MEME_GROUPE : Segments partageant le même gr_id (blocs thématiques Clio)
- TAGS_PARTAGES : Segments partageant le même tag Roget principal

Changements v2.2 :
- NOUVEAU: tisser_groupes_thematiques() - liens par gr_id
- NOUVEAU: tisser_tags_partages() - liens par tag_roget[0]
- main() appelle les 5 fonctions de tissage

Changements v2.1 (conservés) :
- Seuil Intensité : > 0.6 (Filtre le bruit quotidien)
- Seuil Similarité : < 0.1 (Exige une correspondance exacte)
- Fenêtre : 20 (Focalisation locale)
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
import sys
import logging
import math

# === CONFIGURATION ===
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
DB_PATH = MEMORY_DIR / "metadata.db"
SESSION_THRESHOLD = 300 

# === REGLAGES v2.1 (émotions) ===
SEUIL_INTENSITE = 0.6   # On ignore les émotions faibles (|v| < 0.6)
SEUIL_SIMILARITE = 0.10 # Il faut que les émotions soient très proches
TAILLE_FENETRE = 20     # On compare avec les 20 derniers segments émotionnels forts

# === REGLAGES v2.2 (groupes/tags) ===
MIN_GROUPE_SIZE = 2     # Minimum de segments pour créer des liens MEME_GROUPE
POIDS_MEME_GROUPE = 1.8 # Poids fort - cohésion thématique directe
POIDS_TAGS_PARTAGES = 1.3  # Poids moyen - similarité sémantique

logging.basicConfig(level=logging.INFO, format='🕷️  %(message)s')


def get_db_connection():
    if not DB_PATH.exists():
        logging.error(f"Base introuvable: {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def safe_json_load(json_str):
    if not json_str: return []
    try: return json.loads(json_str)
    except: return []


def init_arachne_web(conn):
    cursor = conn.cursor()
    try: cursor.execute("ALTER TABLE edges ADD COLUMN metadata JSON")
    except: pass
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS edges (
        source_id INTEGER,
        target_id INTEGER,
        type TEXT,
        poids REAL DEFAULT 1.0,
        metadata JSON,
        PRIMARY KEY (source_id, target_id, type),
        FOREIGN KEY (source_id) REFERENCES metadata(id),
        FOREIGN KEY (target_id) REFERENCES metadata(id)
    )
    """)
    conn.commit()


def tisser_entites(conn, nom_colonne, type_lien):
    """Tissage Social et Projet (Inchangé car très efficace)"""
    cursor = conn.cursor()
    logging.info(f"Tissage des entités : {nom_colonne} ({type_lien})...")
    
    cursor.execute(f"SELECT id, {nom_colonne}, timestamp FROM metadata ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    derniere_vue = {}
    count_liens = 0

    for seg_id, json_val, _ in rows:
        entites = safe_json_load(json_val)
        noms_propres = []
        if isinstance(entites, list):
            for e in entites:
                if isinstance(e, list) and len(e) > 0: noms_propres.append(e[0])
                elif isinstance(e, str): noms_propres.append(e)
        
        for entite in noms_propres:
            entite_clean = entite.strip()
            if not entite_clean: continue
            if entite_clean in derniere_vue:
                prev_id = derniere_vue[entite_clean]
                if prev_id != seg_id:
                    cursor.execute("""
                    INSERT OR IGNORE INTO edges (source_id, target_id, type, poids, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """, (prev_id, seg_id, type_lien, 1.5, json.dumps({"sujet": entite_clean})))
                    count_liens += 1
            derniere_vue[entite_clean] = seg_id
            
    conn.commit()
    return count_liens


def tisser_emotions(conn):
    """
    v2.1 : Filtrage drastique pour ne garder que les 'Pics Émotionnels'.
    """
    cursor = conn.cursor()
    logging.info("Tissage des résonances émotionnelles (Mode Chirurgical)...")
    
    # FILTRE 1 : L'INTENSITÉ
    # On ne récupère même pas les segments "mous".
    cursor.execute(f"""
    SELECT id, emotion_valence, emotion_activation 
    FROM metadata 
    WHERE emotion_valence IS NOT NULL 
    AND (ABS(emotion_valence) >= {SEUIL_INTENSITE})
    ORDER BY timestamp ASC
    """)
    rows = cursor.fetchall()
    
    count_liens = 0
    fenetre = [] 
    
    for current in rows:
        c_id, c_val, c_act = current
        if c_val is None: continue
        c_act = c_act if c_act else 0.5
        
        # Comparaison avec la fenêtre glissante des 'N' derniers pics émotionnels
        for prev in fenetre:
            p_id, p_val, p_act = prev
            p_act = p_act if p_act else 0.5
            
            # FILTRE 2 : LA SIMILARITÉ (Distance Euclidienne)
            dist = math.sqrt((c_val - p_val)**2 + (c_act - p_act)**2)
            
            if dist < SEUIL_SIMILARITE:
                # On note la valence dans les métadonnées pour que l'Agent comprenne le lien
                meta = json.dumps({"val": round(c_val, 2), "act": round(c_act, 2)})
                
                cursor.execute("""
                INSERT OR IGNORE INTO edges (source_id, target_id, type, poids, metadata)
                VALUES (?, ?, 'RESONANCE_EMOTION', 1.2, ?)
                """, (p_id, c_id, meta))
                count_liens += 1
        
        fenetre.append(current)
        if len(fenetre) > TAILLE_FENETRE: fenetre.pop(0) # FILTRE 3 : FENÊTRE COURTE
        
    conn.commit()
    return count_liens


def tisser_groupes_thematiques(conn):
    """
    v2.2 : Liens entre segments du même bloc thématique (gr_id).
    
    C'est ce qu'Iris a demandé en priorité - la cohésion thématique
    permet de naviguer dans la mémoire par "blocs de sens".
    
    Un gr_id est assigné par Clio quand plusieurs segments consécutifs
    partagent le même sujet/thème dans une conversation.
    """
    cursor = conn.cursor()
    logging.info("Tissage des blocs thématiques (gr_id)...")
    
    # Récupérer tous les segments avec un gr_id non-null
    cursor.execute("""
        SELECT id, gr_id, source_file 
        FROM metadata 
        WHERE gr_id IS NOT NULL 
        ORDER BY gr_id, timestamp ASC
    """)
    rows = cursor.fetchall()
    
    # Grouper par gr_id
    groupes = {}
    for seg_id, gr_id, source_file in rows:
        key = (gr_id, source_file)  # Un gr_id est unique PAR fichier
        if key not in groupes:
            groupes[key] = []
        groupes[key].append(seg_id)
    
    count_liens = 0
    
    # Créer les liens entre segments du même groupe
    for (gr_id, source_file), segment_ids in groupes.items():
        if len(segment_ids) < MIN_GROUPE_SIZE:
            continue
        
        # Lier chaque segment avec les suivants du même groupe
        for i, source_id in enumerate(segment_ids):
            for target_id in segment_ids[i+1:]:
                meta = json.dumps({"gr_id": gr_id, "source_file": source_file})
                cursor.execute("""
                    INSERT OR IGNORE INTO edges (source_id, target_id, type, poids, metadata)
                    VALUES (?, ?, 'MEME_GROUPE', ?, ?)
                """, (source_id, target_id, POIDS_MEME_GROUPE, meta))
                count_liens += 1
    
    conn.commit()
    logging.info(f"   → {len(groupes)} groupes thématiques analysés")
    return count_liens


def tisser_tags_partages(conn):
    """
    v2.2 : Liens entre segments partageant le même tag Roget principal.
    
    Le tag principal (tags_roget[0]) représente le thème dominant du segment.
    Lier les segments par tag permet une navigation sémantique transversale
    à travers toute la mémoire.
    
    Utilise une fenêtre glissante pour éviter l'explosion combinatoire
    (comme tisser_emotions).
    """
    cursor = conn.cursor()
    logging.info("Tissage des tags sémantiques partagés...")
    
    # Récupérer tous les segments avec des tags
    cursor.execute("""
        SELECT id, tags_roget, timestamp 
        FROM metadata 
        WHERE tags_roget IS NOT NULL 
          AND tags_roget != '[]'
          AND tags_roget != ''
        ORDER BY timestamp ASC
    """)
    rows = cursor.fetchall()
    
    count_liens = 0
    # Dict: tag_principal -> liste des N derniers segment_ids avec ce tag
    derniers_par_tag = {}
    FENETRE_TAGS = 10  # On garde les 10 derniers segments par tag
    
    for seg_id, tags_json, _ in rows:
        tags = safe_json_load(tags_json)
        if not tags:
            continue
        
        # Extraire le tag principal (premier de la liste)
        tag_principal = None
        if isinstance(tags, list) and len(tags) > 0:
            first_tag = tags[0]
            if isinstance(first_tag, str):
                tag_principal = first_tag
            elif isinstance(first_tag, list) and len(first_tag) > 0:
                tag_principal = first_tag[0]
            elif isinstance(first_tag, dict) and 'tag' in first_tag:
                tag_principal = first_tag['tag']
        
        if not tag_principal:
            continue
        
        # Créer des liens avec les segments précédents ayant le même tag
        if tag_principal in derniers_par_tag:
            for prev_id in derniers_par_tag[tag_principal]:
                if prev_id != seg_id:
                    meta = json.dumps({"tag": tag_principal})
                    cursor.execute("""
                        INSERT OR IGNORE INTO edges (source_id, target_id, type, poids, metadata)
                        VALUES (?, ?, 'TAGS_PARTAGES', ?, ?)
                    """, (prev_id, seg_id, POIDS_TAGS_PARTAGES, meta))
                    count_liens += 1
        
        # Ajouter ce segment à la fenêtre du tag
        if tag_principal not in derniers_par_tag:
            derniers_par_tag[tag_principal] = []
        derniers_par_tag[tag_principal].append(seg_id)
        
        # Limiter la taille de la fenêtre
        if len(derniers_par_tag[tag_principal]) > FENETRE_TAGS:
            derniers_par_tag[tag_principal].pop(0)
    
    conn.commit()
    logging.info(f"   → {len(derniers_par_tag)} tags distincts analysés")
    return count_liens


def main():
    conn = get_db_connection()
    try:
        init_arachne_web(conn)
        
        # === TISSAGE ENTITÉS (v2.1) ===
        nb_pers = tisser_entites(conn, "personnes", "LIEN_PERSONNE")
        logging.info(f"   👥 {nb_pers} liens sociaux.")
        
        nb_proj = tisser_entites(conn, "projets", "LIEN_PROJET")
        logging.info(f"   🚀 {nb_proj} liens projets.")
        
        # === TISSAGE ÉMOTIONS (v2.1) ===
        nb_emo = tisser_emotions(conn)
        logging.info(f"   ❤️  {nb_emo} résonances émotionnelles FORTES.")
        
        # === TISSAGE THÉMATIQUE (v2.2 - NOUVEAU) ===
        nb_grp = tisser_groupes_thematiques(conn)
        logging.info(f"   🧩 {nb_grp} liens MEME_GROUPE (blocs thématiques).")
        
        nb_tags = tisser_tags_partages(conn)
        logging.info(f"   🏷️  {nb_tags} liens TAGS_PARTAGES (sémantique).")
        
        # === RÉSUMÉ ===
        total = nb_pers + nb_proj + nb_emo + nb_grp + nb_tags
        logging.info(f"   ═══════════════════════════════════")
        logging.info(f"   🕸️  TOTAL: {total} liens tissés")
        
    finally:
        conn.close()


if __name__ == "__main__":
    print("="*60)
    print("🕸️  ARACHNÉ v2.2 - TISSEUSE COMPLÈTE")
    print("   Cohésion thématique + Résonance sémantique")
    print("="*60)
    main()
