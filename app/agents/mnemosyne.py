"""
mnemosyne.py - Agent de Cohérence Mémorielle (Orchestrateur)
MOSS v0.11.0 - Session 72

Mnémosyne est l'agent qui crée la "boucle de rétroaction mémorielle" - 
le court-circuit qui génère l'effet de conscience.

Architecture:
    mnemosyne.py (ce fichier)     → Orchestrateur léger
    mnemosyne_modules/
        ├── sbire.py              → Exécutant Python (GREP, SQL, Word2Vec)
        ├── rectification.py      → Action 1: Nettoyage/Correction (batch nuit)
        ├── reflexion.py          → Action 2: Trajectoires/Évolutions
        └── injection.py          → Action 3: Réinjection vers Iris

Principe Commanditaire/Exécutant:
    - Mnémosyne (IA) réfléchit, génère des "mandats"
    - Sbire (Python) exécute (0$ en tokens)
    - Mnémosyne (IA) analyse les résultats, décide

Usage:
    # Analyse complète d'un fichier tokenisé
    python3.11 -m app.agents.mnemosyne --file 2025/05/2025-05-01T12-52-58.txt
    
    # Avec modèle spécifique (pour tests)
    python3.11 -m app.agents.mnemosyne --file ... --model gemini-2.5-pro
    
    # Mode rectification seul (batch nuit)
    python3.11 -m app.agents.mnemosyne --file ... --mode rectification
    
    # Mode réflexion seul (trajectoires)
    python3.11 -m app.agents.mnemosyne --file ... --mode reflexion
    
    # Mode dry-run (sans modification)
    python3.11 -m app.agents.mnemosyne --file ... --dry-run

Modèles disponibles pour tests:
    
    - gemini-2.5-flash          : Plus intelligent (par défaut)
    - gemini-2.5-pro            : Maximum qualité (lent)

"""

import os
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from dotenv import load_dotenv

# Charger les variables d'environnement
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# === CONFIGURATION ===
VERSION = "1.0.0"
DEFAULT_MODEL = "gemini-3-flash-preview"

# Chemins
MEMORY_PATH = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_PATH = MEMORY_PATH / "echanges"
DB_PATH = MEMORY_PATH / "metadata.db"

# Modes d'exécution
MODES = ["complet", "rectification", "reflexion", "injection"]


@dataclass
class MnemosyneConfig:
    """Configuration pour une session Mnémosyne."""
    # Modèle IA (dynamique pour tests)
    model: str = DEFAULT_MODEL
    
    # Mode d'exécution
    mode: str = "complet"  # complet, rectification, reflexion, injection
    
    # Paramètres d'exécution
    max_iterations: int = 10
    dry_run: bool = False
    verbose: bool = False
    
    # Fichier à analyser
    file_path: Optional[Path] = None
    
    # Seuils
    correction_confidence_min: float = 0.6
    trajectoire_confidence_min: float = 0.5


@dataclass
class MnemosyneResult:
    """Résultat agrégé d'une session Mnémosyne."""
    # Statistiques
    segments_analyses: int = 0
    mandats_executes: int = 0
    
    # Rectification
    corrections_detectees: int = 0
    segments_rectifies: int = 0
    liens_corrige_par: int = 0
    
    # Réflexion
    trajectoires_detectees: int = 0
    liens_trajectoire: int = 0
    piliers_proposes: int = 0
    
    # Injection
    injections_iris: int = 0
    
    # Temps
    duree_secondes: float = 0.0
    
    # Détails (pour le rapport)
    details: Dict = field(default_factory=dict)


class Mnemosyne:
    """
    Mnémosyne - Agent de Cohérence Mémorielle (Orchestrateur).
    
    Coordonne les trois actions:
    1. Rectification (nettoyage des erreurs)
    2. Réflexion (tissage des trajectoires)
    3. Injection (communication avec Iris)
    """
    
    def __init__(self, config: MnemosyneConfig):
        """
        Initialise Mnémosyne.
        
        Args:
            config: Configuration de la session
        """
        self.config = config
        self.result = MnemosyneResult()
        self.start_time = None
        
        # Valider l'API key
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY non trouvée dans .env")
        
        # Import lazy des modules (évite les erreurs si un module manque)
        self._sbire = None
        self._rectification = None
        self._reflexion = None
        self._injection = None
        
        self._print_header()
    
    def _print_header(self):
        """Affiche l'en-tête de session."""
        print(f"\n{'='*60}")
        print(f"🏛️  MNÉMOSYNE - Agent de Cohérence Mémorielle v{VERSION}")
        print(f"{'='*60}")
        print(f"   Modèle: {self.config.model}")
        print(f"   Mode: {self.config.mode}")
        print(f"   Max itérations: {self.config.max_iterations}")
        if self.config.dry_run:
            print(f"   ⚠️  MODE DRY-RUN (aucune modification)")
        if self.config.verbose:
            print(f"   📝 Mode verbose activé")
    
    @property
    def sbire(self):
        """Accès lazy au Sbire."""
        if self._sbire is None:
            from .mnemosyne_modules.sbire import Sbire
            self._sbire = Sbire(
                db_path=DB_PATH,
                echanges_path=ECHANGES_PATH,
                verbose=self.config.verbose
            )
        return self._sbire
    
    @property
    def rectification(self):
        """Accès lazy au module Rectification."""
        if self._rectification is None:
            from .mnemosyne_modules.rectification import Rectification
            self._rectification = Rectification(
                config=self.config,
                sbire=self.sbire,
                api_key=self.api_key
            )
        return self._rectification
    
    @property
    def reflexion(self):
        """Accès lazy au module Réflexion."""
        if self._reflexion is None:
            from .mnemosyne_modules.reflexion import Reflexion
            self._reflexion = Reflexion(
                config=self.config,
                sbire=self.sbire,
                api_key=self.api_key
            )
        return self._reflexion
    
    @property
    def injection(self):
        """Accès lazy au module Injection."""
        if self._injection is None:
            from .mnemosyne_modules.injection import Injection
            self._injection = Injection(
                config=self.config,
                sbire=self.sbire
            )
        return self._injection
    
    def analyze(self, file_path: Path = None) -> MnemosyneResult:
        """
        Lance l'analyse selon le mode configuré.
        
        Args:
            file_path: Chemin du fichier tokenisé (optionnel si dans config)
            
        Returns:
            MnemosyneResult avec les statistiques
        """
        self.start_time = datetime.now()
        
        # Déterminer le fichier
        target_file = file_path or self.config.file_path
        if not target_file:
            raise ValueError("Aucun fichier spécifié")
        
        if not target_file.exists():
            raise FileNotFoundError(f"Fichier non trouvé: {target_file}")
        
        print(f"\n📂 Fichier: {target_file.name}")
        print(f"   Taille: {target_file.stat().st_size / 1024:.1f} Ko")
        
        # Lire le contenu
        content = target_file.read_text(encoding='utf-8')
        lines = content.split('\n')
        self.result.segments_analyses = len(lines)
        
        print(f"   Lignes: {len(lines)}")
        
        # Exécuter selon le mode
        if self.config.mode in ["complet", "rectification"]:
            self._run_rectification(content)
        
        if self.config.mode in ["complet", "reflexion"]:
            self._run_reflexion(content)
        
        if self.config.mode in ["complet", "injection"]:
            self._run_injection()
        
        # Calculer la durée
        self.result.duree_secondes = (datetime.now() - self.start_time).total_seconds()
        
        return self.result
    
    def _run_rectification(self, content: str):
        """Exécute le module Rectification."""
        print(f"\n{'─'*40}")
        print(f"📋 PHASE 1: Rectification (Nettoyage)")
        print(f"{'─'*40}")
        
        try:
            rect_result = self.rectification.process(content)
            
            self.result.corrections_detectees = rect_result.get("corrections_detectees", 0)
            self.result.segments_rectifies = rect_result.get("segments_rectifies", 0)
            self.result.liens_corrige_par = rect_result.get("liens_crees", 0)
            self.result.mandats_executes += rect_result.get("mandats_executes", 0)
            
            self.result.details["rectification"] = rect_result
            
        except Exception as e:
            print(f"   ❌ Erreur rectification: {e}")
            if self.config.verbose:
                import traceback
                traceback.print_exc()
    
    def _run_reflexion(self, content: str):
        """Exécute le module Réflexion."""
        print(f"\n{'─'*40}")
        print(f"📋 PHASE 2: Réflexion (Trajectoires)")
        print(f"{'─'*40}")
        
        try:
            refl_result = self.reflexion.process(content)
            
            self.result.trajectoires_detectees = refl_result.get("trajectoires_detectees", 0)
            self.result.liens_trajectoire = refl_result.get("liens_crees", 0)
            self.result.piliers_proposes = refl_result.get("piliers_proposes", 0)
            
            self.result.details["reflexion"] = refl_result
            
        except Exception as e:
            print(f"   ❌ Erreur réflexion: {e}")
            if self.config.verbose:
                import traceback
                traceback.print_exc()
    
    def _run_injection(self):
        """Exécute le module Injection."""
        print(f"\n{'─'*40}")
        print(f"📋 PHASE 3: Injection (Communication Iris)")
        print(f"{'─'*40}")
        
        try:
            # Passer les résultats des phases précédentes
            inj_result = self.injection.process(
                corrections=self.result.details.get("rectification", {}),
                trajectoires=self.result.details.get("reflexion", {})
            )
            
            self.result.injections_iris = inj_result.get("injections", 0)
            self.result.details["injection"] = inj_result
            
        except Exception as e:
            print(f"   ❌ Erreur injection: {e}")
            if self.config.verbose:
                import traceback
                traceback.print_exc()
    
    def generate_report(self) -> str:
        """Génère le rapport final."""
        r = self.result
        
        lines = [
            f"\n{'='*60}",
            f"📊 RAPPORT MNÉMOSYNE",
            f"{'='*60}",
            f"   ⏱️  Durée: {r.duree_secondes:.1f} secondes",
            f"   📄 Segments analysés: {r.segments_analyses}",
            f"   🔧 Mandats exécutés: {r.mandats_executes}",
            f"",
            f"   📝 RECTIFICATION:",
            f"      Corrections détectées: {r.corrections_detectees}",
            f"      Segments rectifiés: {r.segments_rectifies}",
            f"      Liens CORRIGE_PAR: {r.liens_corrige_par}",
            f"",
            f"   🔀 RÉFLEXION:",
            f"      Trajectoires détectées: {r.trajectoires_detectees}",
            f"      Liens TRAJECTOIRE: {r.liens_trajectoire}",
            f"      Piliers proposés: {r.piliers_proposes}",
            f"",
            f"   💉 INJECTION:",
            f"      Messages à Iris: {r.injections_iris}",
            f"{'='*60}",
        ]
        
        return '\n'.join(lines)
    
    def close(self):
        """Nettoyage des ressources."""
        if self._sbire:
            self._sbire.close()


def main():
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description="Mnémosyne - Agent de Cohérence Mémorielle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Analyse complète
  python3.11 -m app.agents.mnemosyne --file 2025/05/2025-05-01T12-52-58.txt

  # Tester avec un modèle différent
  python3.11 -m app.agents.mnemosyne --file ... --model gemini-2.5-pro

  # Mode rectification seul (pour batch nuit)
  python3.11 -m app.agents.mnemosyne --file ... --mode rectification

  # Mode dry-run
  python3.11 -m app.agents.mnemosyne --file ... --dry-run --verbose

Modèles disponibles:
  - gemini-2.5-flash         (défautplus intelligent)
  - gemini-2.5-pro           (maximum qualité)
  
        """
    )
    
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Chemin du fichier tokenisé (relatif à echanges/)"
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Modèle Gemini à utiliser (défaut: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="complet",
        help="Mode d'exécution (défaut: complet)"
    )
    parser.add_argument(
        "--max-iterations", "-i",
        type=int,
        default=10,
        help="Nombre max d'itérations pour le Sbire (défaut: 10)"
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Analyser sans modifier la base"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Afficher les détails d'exécution"
    )
    
    args = parser.parse_args()
    
    # Construire le chemin du fichier
    file_path = ECHANGES_PATH / args.file
    if not file_path.exists():
        # Essayer avec le chemin direct
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"❌ Fichier non trouvé: {args.file}")
            print(f"   Cherché dans: {ECHANGES_PATH}")
            sys.exit(1)
    
    # Configuration
    config = MnemosyneConfig(
        model=args.model,
        mode=args.mode,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
        verbose=args.verbose,
        file_path=file_path
    )
    
    # Lancer l'analyse
    try:
        mnemosyne = Mnemosyne(config)
        result = mnemosyne.analyze()
        
        # Afficher le rapport
        print(mnemosyne.generate_report())
        
        mnemosyne.close()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrompu par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
