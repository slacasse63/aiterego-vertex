BEGIN TRANSACTION;
DROP TABLE IF EXISTS "edges";
CREATE TABLE edges (
        source_id INTEGER,
        target_id INTEGER,
        type TEXT,                  -- 'SUIT_CHRONO', 'MEME_SESSION', 'SEMANTIQUE'
        poids REAL DEFAULT 1.0,
        metadata JSON,
        PRIMARY KEY (source_id, target_id, type),
        FOREIGN KEY (source_id) REFERENCES metadata(id),
        FOREIGN KEY (target_id) REFERENCES metadata(id)
    );
DROP TABLE IF EXISTS "metadata";
CREATE TABLE metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                token_start INTEGER NOT NULL,
                source_file TEXT NOT NULL,
                source_nature TEXT DEFAULT 'trace',
                source_format TEXT DEFAULT 'txt',
                source_origine TEXT DEFAULT 'local_ollama',
                auteur TEXT,
                tags_roget TEXT,
                personnes TEXT,
                lieux TEXT,
                projets TEXT,
                organisations TEXT,
                type_contenu TEXT,
                emotion_valence REAL,
                emotion_activation REAL,
                cognition_certitude REAL,
                cognition_complexite REAL,
                cognition_abstraction REAL,
                physique_energie REAL,
                physique_stress REAL,
                comm_clarte REAL,
                comm_formalite REAL,
                resume_texte TEXT,
                resume_mots_cles TEXT,
                date_creation TEXT DEFAULT (datetime('now'))
            , pilier INTEGER DEFAULT 0, tic TEXT DEFAULT '[]', relations TEXT DEFAULT '[]', vecteur_trildasa TEXT, ego_version TEXT DEFAULT 'Iris_2.1', modele TEXT DEFAULT 'gemini-2.0-flash-exp', poids_mnemique REAL DEFAULT 0.5, climat_session TEXT, timestamp_epoch INTEGER);
DROP TABLE IF EXISTS "piliers";
CREATE TABLE piliers (id INTEGER PRIMARY KEY AUTOINCREMENT, fait TEXT NOT NULL, categorie TEXT, importance INTEGER DEFAULT 1 CHECK(importance BETWEEN 0 AND 3), source_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (source_id) REFERENCES metadata(id));
DROP INDEX IF EXISTS "idx_auteur";
CREATE INDEX idx_auteur ON metadata(auteur);
DROP INDEX IF EXISTS "idx_edges_source";
CREATE INDEX idx_edges_source ON edges(source_id);
DROP INDEX IF EXISTS "idx_edges_target";
CREATE INDEX idx_edges_target ON edges(target_id);
DROP INDEX IF EXISTS "idx_edges_type";
CREATE INDEX idx_edges_type ON edges(type);
DROP INDEX IF EXISTS "idx_emotion_valence";
CREATE INDEX idx_emotion_valence ON metadata(emotion_valence);
DROP INDEX IF EXISTS "idx_iris_reflexions";
CREATE INDEX idx_iris_reflexions ON metadata(auteur, type_contenu) WHERE auteur = 'iris_internal';
DROP INDEX IF EXISTS "idx_metadata_pilier";
CREATE INDEX idx_metadata_pilier ON metadata(pilier);
DROP INDEX IF EXISTS "idx_modele_ego";
CREATE INDEX idx_modele_ego ON metadata(modele, ego_version);
DROP INDEX IF EXISTS "idx_piliers_categorie";
CREATE INDEX idx_piliers_categorie ON piliers(categorie);
DROP INDEX IF EXISTS "idx_piliers_importance";
CREATE INDEX idx_piliers_importance ON piliers(importance);
DROP INDEX IF EXISTS "idx_poids_mnemique";
CREATE INDEX idx_poids_mnemique ON metadata(poids_mnemique);
DROP INDEX IF EXISTS "idx_source_file";
CREATE INDEX idx_source_file ON metadata(source_file);
DROP INDEX IF EXISTS "idx_timestamp";
CREATE INDEX idx_timestamp ON metadata(timestamp);
DROP INDEX IF EXISTS "idx_timestamp_epoch";
CREATE INDEX idx_timestamp_epoch ON metadata(timestamp_epoch);
DROP INDEX IF EXISTS "idx_token_start";
CREATE INDEX idx_token_start ON metadata(token_start);
DROP INDEX IF EXISTS "idx_type_contenu";
CREATE INDEX idx_type_contenu ON metadata(type_contenu);
COMMIT;
