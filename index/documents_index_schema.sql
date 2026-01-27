-- ============================================================================
-- MOSS/AIter Ego - Table documents_index v1.0
-- ============================================================================
-- Date: 2026-01-16
-- Auteur: Serge Lacasse & Claude (Mission 002 SCS)
-- Base: metadata.db (table séparée des échanges conversationnels)
-- ============================================================================
-- 
-- ARCHITECTURE (validée par Iris - 2026-01-13):
-- - Option B adoptée: Chunking par sections/pages avec liens parent-enfant
-- - URIs canoniques pour portabilité Mac Studio ↔ MacBook
-- - Hybride: SQL + FTS5 + Roget (pas de tout-vectoriel)
-- ============================================================================

-- Table principale des documents indexés
CREATE TABLE IF NOT EXISTS documents_index (
    -- === IDENTIFICATION ===
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,                    -- UUID du document parent
    chunk_id TEXT,                           -- UUID du chunk (NULL si document atomique)
    chunk_index INTEGER DEFAULT 0,           -- Position du chunk dans le document (0 = premier)
    parent_doc_id TEXT,                      -- Référence au document parent (pour chunks)
    
    -- === LOCALISATION ===
    file_path TEXT NOT NULL,                 -- Chemin relatif depuis la source
    source_type TEXT NOT NULL,               -- 'local_dropbox', 'google_drive', 'url', 'local'
    source_uri TEXT NOT NULL,                -- URI canonique: dropbox://..., gdrive://..., file://...
    
    -- === INTÉGRITÉ ===
    checksum TEXT NOT NULL,                  -- MD5 du fichier complet (12 chars)
    content_hash TEXT,                       -- SHA-256 du contenu texte extrait (détection modifications)
    file_size INTEGER,                       -- Taille en octets
    
    -- === MÉTADONNÉES FICHIER ===
    filename TEXT NOT NULL,                  -- Nom du fichier
    mime_type TEXT,                          -- Type MIME (application/pdf, text/markdown, etc.)
    extension TEXT,                          -- Extension (.pdf, .md, .docx)
    language TEXT DEFAULT 'fr',              -- Langue détectée (fr, en, etc.)
    
    -- === CONTENU ===
    content TEXT,                            -- Texte brut extrait (pour FTS5)
    content_tokens INTEGER,                  -- Nombre de tokens estimés
    page_start INTEGER,                      -- Page de début (pour PDF)
    page_end INTEGER,                        -- Page de fin (pour PDF)
    section_title TEXT,                      -- Titre de section (si détecté)
    
    -- === INDEXATION SÉMANTIQUE ===
    roget_codes TEXT,                        -- JSON array: ["02-0010-0050", "06-0030-0080"]
    roget_primary TEXT,                      -- Code Roget principal (pour filtres rapides)
    keywords TEXT,                           -- JSON array: mots-clés extraits
    summary TEXT,                            -- Résumé généré par Mistral
    
    -- === EMBEDDINGS (optionnel, pour recherche vectorielle pure) ===
    embedding_vector BLOB,                   -- Vecteur embedding (si utilisé)
    embedding_model TEXT,                    -- Modèle utilisé pour l'embedding
    
    -- === MÉTADONNÉES DOCUMENT ===
    title TEXT,                              -- Titre du document (si extrait)
    author TEXT,                             -- Auteur (si extrait)
    date_created TEXT,                       -- Date création document (si extraite)
    date_modified TEXT,                      -- Date modification fichier
    
    -- === CLASSIFICATION ===
    domain TEXT,                             -- Domaine: recherche, personnel, technique, administratif
    project TEXT,                            -- Projet associé: MOSS, CRSH, etc.
    tags TEXT,                               -- JSON array: tags manuels
    
    -- === STATUT INDEXATION ===
    indexed_at TEXT NOT NULL,                -- Timestamp indexation ISO8601
    last_verified TEXT,                      -- Dernière vérification d'existence
    indexation_status TEXT DEFAULT 'complete', -- 'pending', 'partial', 'complete', 'error'
    indexation_error TEXT,                   -- Message d'erreur si échec
    
    -- === CONTRAINTES ===
    UNIQUE(source_uri, chunk_index)          -- Un seul chunk par position par URI
);

-- === INDEX POUR PERFORMANCES ===

-- Recherche par document
CREATE INDEX IF NOT EXISTS idx_documents_doc_id ON documents_index(doc_id);
CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents_index(parent_doc_id);

-- Recherche par source
CREATE INDEX IF NOT EXISTS idx_documents_source_uri ON documents_index(source_uri);
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents_index(source_type);

-- Recherche par contenu
CREATE INDEX IF NOT EXISTS idx_documents_roget_primary ON documents_index(roget_primary);
CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents_index(domain);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents_index(project);

-- Recherche par fichier
CREATE INDEX IF NOT EXISTS idx_documents_filename ON documents_index(filename);
CREATE INDEX IF NOT EXISTS idx_documents_extension ON documents_index(extension);
CREATE INDEX IF NOT EXISTS idx_documents_mime_type ON documents_index(mime_type);

-- Vérification intégrité
CREATE INDEX IF NOT EXISTS idx_documents_checksum ON documents_index(checksum);
CREATE INDEX IF NOT EXISTS idx_documents_indexed_at ON documents_index(indexed_at);

-- === FTS5 POUR RECHERCHE TEXTUELLE ===

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    content,                                 -- Texte brut
    summary,                                 -- Résumé
    keywords,                                -- Mots-clés
    title,                                   -- Titre
    section_title,                           -- Titre de section
    content='documents_index',               -- Table source
    content_rowid='id'                       -- Colonne rowid
);

-- Triggers pour synchroniser FTS5 avec la table principale

-- Insert
CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents_index BEGIN
    INSERT INTO documents_fts(rowid, content, summary, keywords, title, section_title)
    VALUES (new.id, new.content, new.summary, new.keywords, new.title, new.section_title);
END;

-- Delete
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents_index BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, content, summary, keywords, title, section_title)
    VALUES ('delete', old.id, old.content, old.summary, old.keywords, old.title, old.section_title);
END;

-- Update
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents_index BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, content, summary, keywords, title, section_title)
    VALUES ('delete', old.id, old.content, old.summary, old.keywords, old.title, old.section_title);
    INSERT INTO documents_fts(rowid, content, summary, keywords, title, section_title)
    VALUES (new.id, new.content, new.summary, new.keywords, new.title, new.section_title);
END;


-- ============================================================================
-- VUES UTILITAIRES
-- ============================================================================

-- Vue: Documents complets (sans chunks)
CREATE VIEW IF NOT EXISTS v_documents AS
SELECT 
    doc_id,
    filename,
    source_uri,
    source_type,
    mime_type,
    file_size,
    domain,
    project,
    roget_primary,
    indexed_at,
    COUNT(*) as chunk_count,
    SUM(content_tokens) as total_tokens
FROM documents_index
GROUP BY doc_id;

-- Vue: Chunks d'un document
CREATE VIEW IF NOT EXISTS v_document_chunks AS
SELECT 
    doc_id,
    chunk_id,
    chunk_index,
    section_title,
    page_start,
    page_end,
    content_tokens,
    roget_codes,
    summary
FROM documents_index
WHERE chunk_id IS NOT NULL
ORDER BY doc_id, chunk_index;

-- Vue: Documents par domaine
CREATE VIEW IF NOT EXISTS v_documents_by_domain AS
SELECT 
    domain,
    COUNT(DISTINCT doc_id) as document_count,
    SUM(content_tokens) as total_tokens
FROM documents_index
GROUP BY domain;

-- Vue: Documents récemment indexés
CREATE VIEW IF NOT EXISTS v_recent_documents AS
SELECT 
    doc_id,
    filename,
    source_uri,
    indexed_at,
    indexation_status
FROM documents_index
WHERE chunk_index = 0  -- Premier chunk seulement
ORDER BY indexed_at DESC
LIMIT 100;


-- ============================================================================
-- EXEMPLES DE REQUÊTES
-- ============================================================================

/*
-- Recherche FTS5 (texte libre)
SELECT d.* 
FROM documents_index d
JOIN documents_fts f ON d.id = f.rowid
WHERE documents_fts MATCH 'mémoire AND sémantique'
ORDER BY rank;

-- Recherche par code Roget
SELECT * FROM documents_index
WHERE roget_codes LIKE '%"04-0110%'  -- Cognition
ORDER BY indexed_at DESC;

-- Recherche hybride (FTS + filtre domaine)
SELECT d.* 
FROM documents_index d
JOIN documents_fts f ON d.id = f.rowid
WHERE documents_fts MATCH 'MOSS architecture'
  AND d.domain = 'technique'
ORDER BY rank;

-- Tous les chunks d'un document
SELECT * FROM documents_index
WHERE doc_id = 'uuid-du-document'
ORDER BY chunk_index;

-- Documents nécessitant ré-indexation (modifiés depuis)
SELECT * FROM documents_index
WHERE date_modified > indexed_at;

-- Statistiques par projet
SELECT 
    project,
    COUNT(DISTINCT doc_id) as docs,
    SUM(content_tokens) as tokens
FROM documents_index
GROUP BY project
ORDER BY tokens DESC;
*/
