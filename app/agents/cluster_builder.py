"""
cluster_builder.py - Générateur de modèle Word2Vec pour expansion sémantique
MOSS v0.10.4 - Session 70

Entraîne un modèle Word2Vec sur le corpus de conversations pour permettre
l'expansion de requêtes dans Hermès.

Usage:
    # Génération complète
    python3.11 -m app.agents.cluster_builder
    
    # Avec options
    python3.11 -m app.agents.cluster_builder --output models/clusters.model --min-count 3
    
    # Test interactif après génération
    python3.11 -m app.agents.cluster_builder --interactive

Résultats attendus (corpus ~77K segments):
    - Vocabulaire: ~150-180K termes
    - Expressions n-grams: ~100-130K
    - Temps d'entraînement: ~20-30 secondes
    - Taille modèle: ~6-8 Mo
"""

import re
import argparse
import unicodedata
from pathlib import Path
from typing import List, Set, Optional

# === CONFIGURATION ===
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_DIRS = [
    MEMORY_DIR / "echanges" / "2024",
    MEMORY_DIR / "echanges" / "2025",
    MEMORY_DIR / "echanges" / "2026",
]
DEFAULT_MODEL_PATH = MEMORY_DIR / "models" / "clusters.model"

# Version
VERSION = "1.0"

# Stopwords français/anglais
STOPWORDS = {
    # Français - articles, prépositions, pronoms
    'le', 'la', 'les', 'de', 'du', 'des', 'un', 'une', 'et', 'est', 'en',
    'que', 'qui', 'dans', 'pour', 'sur', 'avec', 'ce', 'se', 'ne', 'pas',
    'plus', 'par', 'son', 'sa', 'ses', 'au', 'aux', 'ou', 'mais', 'donc',
    'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles', 'on', 'ça',
    'ai', 'as', 'a', 'avons', 'avez', 'ont', 'suis', 'es', 'sommes', 'êtes',
    'sont', 'été', 'être', 'avoir', 'fait', 'faire', 'dit', 'dire', 'peut',
    'veux', 'peux', 'dois', 'faut', 'tout', 'tous', 'toute', 'toutes',
    'même', 'autre', 'autres', 'bien', 'très', 'peu', 'encore', 'déjà',
    'comme', 'quand', 'comment', 'où', 'pourquoi', 'parce', 'car', 'si',
    'oui', 'non', 'ok', 'donc', 'alors', 'mais', 'cela', 'ceci', 'ici',
    'là', 'puis', 'après', 'avant', 'entre', 'sous', 'chez', 'vers',
    
    # Anglais - articles, prépositions, pronoms
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
    
    # Marqueurs de conversation à ignorer
    'user', 'assistant', 'human', 'claude', 'chatgpt', 'gpt', 'iris'
}


def normalize_text(text: str) -> str:
    """
    Normalise le texte pour équivalence accents.
    'mémoire' et 'memoire' deviennent 'memoire'
    """
    # NFD décompose les accents, puis on encode en ASCII en ignorant les erreurs
    normalized = unicodedata.normalize('NFD', text)
    return normalized.encode('ascii', 'ignore').decode('utf-8')


def tokenize(text: str, normalize_accents: bool = True) -> List[str]:
    """Tokenize et filtre les stopwords."""
    if not text:
        return []
    
    # Optionnel: normaliser les accents
    if normalize_accents:
        text = normalize_text(text)
    
    # Lowercase et split sur non-alphanumérique
    words = re.findall(r'[a-zàâäéèêëïîôùûüÿœæç0-9]+', text.lower())
    
    # Filtre stopwords et mots trop courts
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def load_corpus(directories: List[Path], normalize_accents: bool = True) -> List[List[str]]:
    """Charge le corpus depuis les fichiers .txt."""
    corpus = []
    total_chars = 0
    total_files = 0
    
    print(f"\n📚 Chargement du corpus...")
    
    for directory in directories:
        if not directory.exists():
            continue
        
        txt_files = list(directory.glob("**/*.txt"))
        total_files += len(txt_files)
        
        for filepath in txt_files:
            try:
                content = filepath.read_text(encoding='utf-8')
                total_chars += len(content)
                
                # Split en paragraphes
                paragraphs = content.split('\n\n')
                for para in paragraphs:
                    if len(para) > 50:
                        tokens = tokenize(para, normalize_accents)
                        if len(tokens) > 5:
                            corpus.append(tokens)
            except Exception:
                pass
    
    print(f"   📄 {total_files} fichiers")
    print(f"   📝 {total_chars:,} caractères")
    print(f"   📦 {len(corpus)} paragraphes")
    
    return corpus


def build_model(corpus: List[List[str]], min_count: int = 2, vector_size: int = 100):
    """Entraîne le modèle Word2Vec avec détection de phrases."""
    try:
        from gensim.models import Word2Vec
        from gensim.models.phrases import Phrases, Phraser
    except ImportError:
        raise ImportError("gensim requis: pip install gensim")
    
    print(f"\n🔗 Détection des expressions (n-grams)...")
    
    # Détecte les expressions fréquentes (ex: "mémoire_agnostique")
    phrases = Phrases(corpus, min_count=min_count, threshold=5)
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
    
    print(f"\n🧠 Entraînement Word2Vec...")
    model = Word2Vec(
        sentences=corpus_phrases,
        vector_size=vector_size,
        window=5,
        min_count=min_count,
        workers=4,
        epochs=15
    )
    
    print(f"   → Vocabulaire: {len(model.wv)} termes")
    
    return model, phraser


def test_similarity(model, terme: str, top_n: int = 10) -> List[tuple]:
    """Teste la similarité pour un terme."""
    terme_lower = terme.lower()
    
    # Essayer aussi la version normalisée
    terme_normalized = normalize_text(terme_lower)
    
    for t in [terme_lower, terme_normalized]:
        if t in model.wv:
            return model.wv.most_similar(t, topn=top_n)
    
    return []


def interactive_mode(model):
    """Mode interactif pour tester des termes."""
    print("\n" + "=" * 60)
    print("🎮 MODE INTERACTIF")
    print("   Tape un mot pour voir ses similaires, 'q' pour quitter")
    print("=" * 60)
    
    while True:
        terme = input("\n> ").strip()
        if terme.lower() in ['q', 'quit', 'exit']:
            break
        if terme:
            similaires = test_similarity(model, terme)
            if similaires:
                print(f"\n🔍 Termes similaires à '{terme}':")
                for mot, score in similaires:
                    print(f"   {score:.3f} - {mot}")
            else:
                print(f"   ⚠️ '{terme}' pas dans le vocabulaire")


def main():
    parser = argparse.ArgumentParser(
        description="Générateur de modèle Word2Vec pour MOSS",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=f"Chemin de sortie du modèle (défaut: {DEFAULT_MODEL_PATH})"
    )
    parser.add_argument(
        "--min-count", "-m",
        type=int,
        default=2,
        help="Occurrences minimum pour inclure un terme (défaut: 2)"
    )
    parser.add_argument(
        "--vector-size", "-v",
        type=int,
        default=100,
        help="Dimensions des vecteurs (défaut: 100)"
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Désactiver la normalisation des accents"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Lancer le mode interactif après génération"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"🔧 CLUSTER BUILDER v{VERSION}")
    print("=" * 60)
    
    # 1. Charger le corpus
    normalize = not args.no_normalize
    corpus = load_corpus(ECHANGES_DIRS, normalize_accents=normalize)
    
    if not corpus:
        print("❌ Corpus vide, abandon")
        return 1
    
    # 2. Entraîner le modèle
    model, phraser = build_model(corpus, min_count=args.min_count, vector_size=args.vector_size)
    
    # 3. Créer le dossier de sortie si nécessaire
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # 4. Sauvegarder
    print(f"\n💾 Sauvegarde: {args.output}")
    model.save(str(args.output))
    
    # 5. Stats finales
    print(f"\n{'='*60}")
    print("✅ RÉSUMÉ")
    print(f"{'='*60}")
    print(f"   Paragraphes: {len(corpus)}")
    print(f"   Vocabulaire: {len(model.wv)} termes")
    print(f"   Modèle: {args.output}")
    if args.output.exists():
        size_mb = args.output.stat().st_size / 1024 / 1024
        print(f"   Taille: {size_mb:.1f} Mo")
    
    # 6. Tests de similarité
    print(f"\n{'='*60}")
    print("📊 TESTS DE SIMILARITÉ")
    print(f"{'='*60}")
    
    termes_test = ["memoire", "moss", "alex", "brevet", "iris", "hermes", "scribe"]
    for terme in termes_test:
        similaires = test_similarity(model, terme, top_n=5)
        if similaires:
            print(f"\n🔍 '{terme}':")
            for mot, score in similaires:
                print(f"   {score:.3f} - {mot}")
    
    # 7. Mode interactif optionnel
    if args.interactive:
        interactive_mode(model)
    
    return 0


if __name__ == "__main__":
    exit(main())
