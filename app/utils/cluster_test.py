#!/usr/bin/env python3
"""
cluster_test_v2.py - Test Word2Vec sur fichiers .txt des échanges
Lit directement les fichiers de conversation pour un corpus plus riche
"""

import re
from pathlib import Path
from gensim.models import Word2Vec
from gensim.models.phrases import Phrases, Phraser

# === CONFIGURATION ===
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_DIRS = [
    MEMORY_DIR / "echanges" / "2024",
    MEMORY_DIR / "echanges" / "2025",
]
MODEL_PATH = MEMORY_DIR / "clusters_full.model"

# Stopwords français/anglais basiques
STOPWORDS = {
    'le', 'la', 'les', 'de', 'du', 'des', 'un', 'une', 'et', 'est', 'en', 
    'que', 'qui', 'dans', 'pour', 'sur', 'avec', 'ce', 'se', 'ne', 'pas',
    'plus', 'par', 'son', 'sa', 'ses', 'au', 'aux', 'ou', 'mais', 'donc',
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'to', 'of', 'in',
    'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
    'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
    'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his',
    'our', 'their', 'what', 'which', 'who', 'whom', 'when', 'where', 'why',
    'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
    'too', 'very', 'just', 'also', 'now', 'here', 'there', 'then', 'if',
    'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles', 'on', 'ça',
    'ai', 'as', 'a', 'avons', 'avez', 'ont', 'suis', 'es', 'sommes', 'êtes',
    'sont', 'été', 'être', 'avoir', 'fait', 'faire', 'dit', 'dire', 'peut',
    'veux', 'peux', 'dois', 'faut', 'tout', 'tous', 'toute', 'toutes',
    'même', 'autre', 'autres', 'bien', 'très', 'peu', 'encore', 'déjà',
    'comme', 'quand', 'comment', 'où', 'pourquoi', 'parce', 'car', 'si',
    'oui', 'non', 'ok', 'donc', 'alors', 'mais', 'cela', 'ceci', 'ici',
    'là', 'puis', 'après', 'avant', 'entre', 'sous', 'chez', 'vers',
    'user', 'assistant', 'human', 'claude', 'chatgpt'  # Marqueurs de conversation
}


def tokenize(text):
    """Tokenize et filtre les stopwords"""
    if not text:
        return []
    # Lowercase et split sur non-alphanumérique (garde les accents)
    words = re.findall(r'[a-zàâäéèêëïîôùûüÿœæç0-9]+', text.lower())
    # Filtre stopwords et mots trop courts
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def load_corpus_from_files(directories):
    """Charge le corpus depuis les fichiers .txt de plusieurs dossiers"""
    corpus = []
    total_chars = 0
    total_files = 0
    
    for directory in directories:
        print(f"📂 Lecture de {directory}")
        
        if not directory.exists():
            print(f"   ⚠️ Dossier introuvable: {directory}")
            continue
        
        # Récursif pour aller dans les sous-dossiers (01, 02, 03...)
        txt_files = list(directory.glob("**/*.txt"))
        print(f"   📄 {len(txt_files)} fichiers trouvés")
        total_files += len(txt_files)
        
        for filepath in txt_files:
            try:
                content = filepath.read_text(encoding='utf-8')
                total_chars += len(content)
                
                paragraphs = content.split('\n\n')
                for para in paragraphs:
                    if len(para) > 50:
                        tokens = tokenize(para)
                        if len(tokens) > 5:
                            corpus.append(tokens)
            except Exception as e:
                pass  # Ignore les erreurs silencieusement
    
    print(f"\n📊 TOTAL: {total_files} fichiers, {total_chars:,} caractères")
    print(f"📝 {len(corpus)} paragraphes chargés pour l'entraînement")
    return corpus


def build_model(corpus):
    """Entraîne Word2Vec avec détection de phrases"""
    print("\n🔗 Détection des expressions (n-grams)...")
    
    # Détecte les expressions fréquentes (ex: "mémoire_agnostique")
    # Baisse le threshold pour détecter plus d'expressions
    phrases = Phrases(corpus, min_count=2, threshold=5)
    phraser = Phraser(phrases)
    
    # Applique les phrases au corpus
    corpus_phrases = [phraser[doc] for doc in corpus]
    
    # Compte les expressions détectées
    expressions = set()
    for doc in corpus_phrases:
        for token in doc:
            if '_' in token:
                expressions.add(token)
    print(f"   → {len(expressions)} expressions détectées")
    if expressions:
        exemples = sorted(list(expressions))[:20]
        print(f"   Exemples: {exemples}")
    
    print("\n🧠 Entraînement Word2Vec...")
    model = Word2Vec(
        sentences=corpus_phrases,
        vector_size=100,      # Dimensions du vecteur
        window=5,             # Contexte de 5 mots
        min_count=2,          # Minimum 2 occurrences (baissé!)
        workers=4,            # Parallélisation
        epochs=15             # Plus de passes
    )
    
    print(f"   → Vocabulaire: {len(model.wv)} termes")
    return model, phraser


def test_similarity(model, terme, top_n=10):
    """Teste la similarité pour un terme"""
    print(f"\n🔍 Termes similaires à '{terme}':")
    
    terme_lower = terme.lower()
    if terme_lower not in model.wv:
        print(f"   ⚠️  '{terme}' pas dans le vocabulaire")
        # Cherche des termes qui contiennent le mot
        matches = [w for w in model.wv.key_to_index.keys() if terme_lower in w]
        if matches:
            print(f"   Termes contenant '{terme}': {matches[:10]}")
        return []
    
    similaires = model.wv.most_similar(terme_lower, topn=top_n)
    for mot, score in similaires:
        print(f"   {score:.3f} - {mot}")
    return similaires


def interactive_test(model):
    """Mode interactif pour tester des termes"""
    print("\n" + "=" * 60)
    print("🎮 MODE INTERACTIF")
    print("   Tape un mot pour voir ses similaires, 'q' pour quitter")
    print("=" * 60)
    
    while True:
        terme = input("\n> ").strip()
        if terme.lower() in ['q', 'quit', 'exit']:
            break
        if terme:
            test_similarity(model, terme)


def main():
    print("=" * 60)
    print("🧪 TEST CLUSTERS WORD2VEC - FICHIERS TXT")
    print("=" * 60)
    
    # 1. Charger le corpus
    corpus = load_corpus_from_files(ECHANGES_DIRS)
    if not corpus:
        print("❌ Corpus vide, abandon")
        return
    
    # 2. Entraîner le modèle
    model, phraser = build_model(corpus)
    
    # 3. Sauvegarder
    print(f"\n💾 Sauvegarde du modèle: {MODEL_PATH}")
    model.save(str(MODEL_PATH))
    
    # 4. Tests de similarité
    print("\n" + "=" * 60)
    print("📊 TESTS DE SIMILARITÉ")
    print("=" * 60)
    
    termes_test = [
        "mémoire",
        "memoire", 
        "délocalisée",
        "déportée",
        "alex",
        "serge",
        "api",
        "prototype",
        "architecture",
        "externe",
        "ssd",
        "gpt",
        "contexte"
    ]
    
    for terme in termes_test:
        test_similarity(model, terme)
    
    # 5. Stats finales
    print("\n" + "=" * 60)
    print("✅ RÉSUMÉ")
    print("=" * 60)
    print(f"   Paragraphes traités: {len(corpus)}")
    print(f"   Vocabulaire: {len(model.wv)} termes")
    print(f"   Modèle sauvé: {MODEL_PATH}")
    if MODEL_PATH.exists():
        print(f"   Taille: {MODEL_PATH.stat().st_size / 1024 / 1024:.1f} Mo")
    
    # 6. Mode interactif
    interactive_test(model)


if __name__ == "__main__":
    main()
