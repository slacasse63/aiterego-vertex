BEGIN TRANSACTION;
DROP TABLE IF EXISTS "edges";
CREATE TABLE edges (
    source_id INTEGER,
    target_id INTEGER,
    type TEXT,                                  -- 'SUIT_CHRONO', 'MEME_SESSION', 'SEMANTIQUE', 'MEME_GROUPE'
    poids REAL DEFAULT 1.0,
    metadata JSON,
    PRIMARY KEY (source_id, target_id, type),
    FOREIGN KEY (source_id) REFERENCES metadata(id),
    FOREIGN KEY (target_id) REFERENCES metadata(id)
);
DROP TABLE IF EXISTS "metadata";
CREATE TABLE metadata (
    -- Identifiant
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Localisation temporelle
    timestamp TEXT NOT NULL,
    timestamp_epoch INTEGER,
    
    -- Localisation dans le fichier
    token_start INTEGER NOT NULL,
    token_end INTEGER,                          -- NOUVEAU: position fin
    
    -- Source
    source_file TEXT NOT NULL,
    source_nature TEXT DEFAULT 'trace',         -- trace, document, reflexion
    source_format TEXT DEFAULT 'txt',           -- txt, pdf, md
    source_origine TEXT DEFAULT 'gemini',       -- gemini, chatgpt, claude, local
    
    -- Auteur
    auteur TEXT,                                -- human, assistant, iris_internal
    
    -- Émotions (Russell Circumplex)
    emotion_valence REAL,                       -- -1 (négatif) à +1 (positif)
    emotion_activation REAL,                    -- 0 (calme) à 1 (intense)
    
    -- Classification sémantique
    tags_roget TEXT,                            -- JSON array, max 5 tags CC-SSSS-TTTT
    
    -- Entités
    personnes TEXT DEFAULT '[]',                -- JSON array
    projets TEXT DEFAULT '[]',                  -- JSON array (liste contrôlée)
    sujets TEXT DEFAULT '[]',                   -- NOUVEAU: JSON array, max 5
    lieux TEXT DEFAULT '[]',                    -- JSON array (vide pour now, futur GPS)
    
    -- Résumé
    resume_texte TEXT,                          -- Max 200 tokens (~150 mots)
    
    -- Groupement
    gr_id INTEGER,                              -- NOUVEAU: Grouping ID (segments liés)
    
    -- Métadonnées système
    pilier INTEGER DEFAULT 0,
    vecteur_trildasa TEXT,
    poids_mnemique REAL DEFAULT 0.5,
    ego_version TEXT DEFAULT 'Iris_2.1',
    modele TEXT DEFAULT 'gemini-2.5-flash-lite',
    date_creation TEXT DEFAULT (datetime('now'))
, confidence_score REAL, statut_verite INTEGER DEFAULT 0, organisations TEXT DEFAULT '[]');
DROP TABLE IF EXISTS "organisations";
CREATE TABLE organisations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE,
    variantes TEXT DEFAULT '[]',
    type TEXT DEFAULT 'organisation',
    description TEXT,
    actif INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
DROP TABLE IF EXISTS "personnes";
CREATE TABLE personnes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_canonique TEXT NOT NULL,                -- "Jérémie Hatier"
    variantes TEXT DEFAULT '[]',                -- JSON: ["Jérémie", "Jeremie", "Jeremy"]
    contexte TEXT,                              -- "MOSS, physique, collaborateur"
    domaine TEXT DEFAULT 'professionnel',       -- professionnel, famille, personnel
    actif INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
DROP TABLE IF EXISTS "personnes_candidats";
CREATE TABLE personnes_candidats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_detecte TEXT NOT NULL,
    contexte TEXT,                              -- Extrait du segment où détecté
    domaine_suggere TEXT,                       -- professionnel, famille, personnel
    segment_id INTEGER,                         -- Référence au segment source
    timestamp_detection TEXT DEFAULT (datetime('now')),
    valide INTEGER DEFAULT NULL,                -- NULL=en attente, 1=ajouté, 0=rejeté
    FOREIGN KEY (segment_id) REFERENCES metadata(id)
);
DROP TABLE IF EXISTS "piliers";
CREATE TABLE piliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fait TEXT NOT NULL,
    categorie TEXT,
    importance INTEGER DEFAULT 1 CHECK(importance BETWEEN 0 AND 3),
    source_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES metadata(id)
);
DROP TABLE IF EXISTS "projets";
CREATE TABLE projets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE,
    parent_id INTEGER,                          -- NULL si projet racine
    description TEXT,
    actif INTEGER DEFAULT 1,                    -- 1=en cours, 0=archivé
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES projets(id)
);
DROP TABLE IF EXISTS "projets_candidats";
CREATE TABLE projets_candidats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_detecte TEXT NOT NULL,
    contexte TEXT,                              -- Extrait du segment où détecté
    segment_id INTEGER,                         -- Référence au segment source
    timestamp_detection TEXT DEFAULT (datetime('now')),
    valide INTEGER DEFAULT NULL,                -- NULL=en attente, 1=ajouté, 0=rejeté
    FOREIGN KEY (segment_id) REFERENCES metadata(id)
);
DROP VIEW IF EXISTS "v_personnes_recherche";
CREATE VIEW v_personnes_recherche AS
SELECT 
    id,
    nom_canonique,
    variantes,
    contexte,
    domaine,
    -- Génère un pattern de recherche pour SQL LIKE
    nom_canonique || ' ' || COALESCE(variantes, '') as recherche_texte
FROM personnes
WHERE actif = 1;
DROP VIEW IF EXISTS "v_projets_hierarchie";
CREATE VIEW v_projets_hierarchie AS
WITH RECURSIVE projet_tree AS (
    -- Projets racines
    SELECT id, nom, parent_id, description, actif, 0 as niveau, nom as chemin
    FROM projets
    WHERE parent_id IS NULL
    
    UNION ALL
    
    -- Sous-projets
    SELECT p.id, p.nom, p.parent_id, p.description, p.actif, 
           pt.niveau + 1, pt.chemin || ' > ' || p.nom
    FROM projets p
    JOIN projet_tree pt ON p.parent_id = pt.id
)
SELECT * FROM projet_tree ORDER BY chemin;
DROP INDEX IF EXISTS "idx_auteur";
CREATE INDEX idx_auteur ON metadata(auteur);
DROP INDEX IF EXISTS "idx_confidence_score";
CREATE INDEX idx_confidence_score ON metadata(confidence_score);
DROP INDEX IF EXISTS "idx_edges_source";
CREATE INDEX idx_edges_source ON edges(source_id);
DROP INDEX IF EXISTS "idx_edges_target";
CREATE INDEX idx_edges_target ON edges(target_id);
DROP INDEX IF EXISTS "idx_edges_type";
CREATE INDEX idx_edges_type ON edges(type);
DROP INDEX IF EXISTS "idx_emotion_valence";
CREATE INDEX idx_emotion_valence ON metadata(emotion_valence);
DROP INDEX IF EXISTS "idx_gr_id";
CREATE INDEX idx_gr_id ON metadata(gr_id);
DROP INDEX IF EXISTS "idx_iris_reflexions";
CREATE INDEX idx_iris_reflexions ON metadata(auteur, source_nature) 
    WHERE auteur = 'iris_internal';
DROP INDEX IF EXISTS "idx_modele_ego";
CREATE INDEX idx_modele_ego ON metadata(modele, ego_version);
DROP INDEX IF EXISTS "idx_organisations_actif";
CREATE INDEX idx_organisations_actif ON organisations(actif);
DROP INDEX IF EXISTS "idx_personnes_actif";
CREATE INDEX idx_personnes_actif ON personnes(actif);
DROP INDEX IF EXISTS "idx_personnes_cand_valide";
CREATE INDEX idx_personnes_cand_valide ON personnes_candidats(valide);
DROP INDEX IF EXISTS "idx_personnes_domaine";
CREATE INDEX idx_personnes_domaine ON personnes(domaine);
DROP INDEX IF EXISTS "idx_pilier";
CREATE INDEX idx_pilier ON metadata(pilier);
DROP INDEX IF EXISTS "idx_piliers_categorie";
CREATE INDEX idx_piliers_categorie ON piliers(categorie);
DROP INDEX IF EXISTS "idx_piliers_importance";
CREATE INDEX idx_piliers_importance ON piliers(importance);
DROP INDEX IF EXISTS "idx_poids_mnemique";
CREATE INDEX idx_poids_mnemique ON metadata(poids_mnemique);
DROP INDEX IF EXISTS "idx_projets_actif";
CREATE INDEX idx_projets_actif ON projets(actif);
DROP INDEX IF EXISTS "idx_projets_cand_valide";
CREATE INDEX idx_projets_cand_valide ON projets_candidats(valide);
DROP INDEX IF EXISTS "idx_projets_parent";
CREATE INDEX idx_projets_parent ON projets(parent_id);
DROP INDEX IF EXISTS "idx_source_file";
CREATE INDEX idx_source_file ON metadata(source_file);
DROP INDEX IF EXISTS "idx_timestamp";
CREATE INDEX idx_timestamp ON metadata(timestamp);
DROP INDEX IF EXISTS "idx_timestamp_epoch";
CREATE INDEX idx_timestamp_epoch ON metadata(timestamp_epoch);
DROP INDEX IF EXISTS "idx_token_start";
CREATE INDEX idx_token_start ON metadata(token_start);
COMMIT;
