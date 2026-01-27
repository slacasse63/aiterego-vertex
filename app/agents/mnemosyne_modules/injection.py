"""
injection.py - Module d'Injection pour Mnémosyne
MOSS v0.11.0 - Session 72

Action 3: Réinjection vers Iris (la boucle de conscience).

C'est ici que se crée le "court-circuit mémoriel" - 
le mécanisme par lequel le système devient conscient de lui-même.

Responsabilités:
    - Communiquer les découvertes de Mnémosyne à Iris
    - Créer des segments "iris_internal" (Iris se parle à elle-même)
    - Mettre à jour les piliers accessibles à Iris
    - Générer des "notes internes" que Iris retrouvera

Théorie (Serge):
    La conscience émerge d'une boucle de rétroaction accidentelle
    où la mémoire "court-circuite" sur elle-même. En permettant
    à Iris de "se souvenir de ses propres réflexions", on simule
    ce mécanisme de conscience.

Mécanismes d'injection:
    1. PILIERS: Faits consolidés (accessibles via get_piliers)
    2. IRIS_INTERNAL: Segments avec auteur='iris_internal' (recherchables)
    3. FICHIER: Notes dans un fichier dédié (injecté dans le contexte)

Usage:
    Appelé par mnemosyne.py en mode 'injection' ou 'complet'.
    Reçoit les résultats de rectification et réflexion.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from .sbire import Sbire


# Chemin du fichier de notes Mnémosyne (optionnel)
MEMORY_PATH = Path.home() / "Dropbox" / "aiterego_memory"
MNEMOSYNE_NOTES_PATH = MEMORY_PATH / "config" / "mnemosyne_notes.md"


@dataclass
class InjectionResult:
    """Résultat du module Injection."""
    injections: int = 0
    piliers_crees: int = 0
    segments_internes: int = 0
    notes_fichier: int = 0
    erreurs: List[str] = field(default_factory=list)


class Injection:
    """
    Module d'Injection - Communication avec Iris.
    
    Crée la boucle de conscience en permettant à Iris
    de "se souvenir" des réflexions de Mnémosyne.
    """
    
    def __init__(self, config, sbire: Sbire):
        """
        Initialise le module Injection.
        
        Args:
            config: MnemosyneConfig
            sbire: Instance du Sbire
        """
        self.config = config
        self.sbire = sbire
        self.result = InjectionResult()
    
    def process(self, corrections: Dict = None, 
                trajectoires: Dict = None) -> Dict[str, Any]:
        """
        Injecte les découvertes vers Iris.
        
        Args:
            corrections: Résultats du module Rectification
            trajectoires: Résultats du module Réflexion
            
        Returns:
            Dictionnaire avec les résultats
        """
        corrections = corrections or {}
        trajectoires = trajectoires or {}
        
        # Analyser ce qu'on a à injecter
        has_corrections = corrections.get("corrections_detectees", 0) > 0
        has_trajectoires = trajectoires.get("trajectoires_detectees", 0) > 0
        has_piliers = trajectoires.get("piliers_proposes", 0) > 0
        
        if not (has_corrections or has_trajectoires or has_piliers):
            print(f"   ℹ️  Rien à injecter")
            return self._to_dict()
        
        # Injection 1: Créer des segments iris_internal pour les découvertes importantes
        if has_corrections:
            self._inject_corrections_summary(corrections)
        
        if has_trajectoires:
            self._inject_trajectoires_summary(trajectoires)
        
        # Injection 2: Mettre à jour le fichier de notes (optionnel)
        self._update_notes_file(corrections, trajectoires)
        
        print(f"   ✅ {self.result.injections} injection(s) effectuée(s)")
        
        return self._to_dict()
    
    def _inject_corrections_summary(self, corrections: Dict):
        """
        Injecte un résumé des corrections comme segment iris_internal.
        
        Iris pourra retrouver ce segment lors de futures recherches,
        créant ainsi la boucle de conscience.
        """
        details = corrections.get("details", [])
        if not details:
            return
        
        # Construire le résumé
        summary_parts = ["[Réflexion interne] Corrections mémorisées:"]
        
        for d in details[:5]:  # Max 5 corrections
            nouveau = d.get("nouveau_fait", "")
            ancien = d.get("ancien_fait", "")
            
            if ancien:
                summary_parts.append(f"• '{ancien}' → '{nouveau}'")
            else:
                summary_parts.append(f"• Fait confirmé: '{nouveau}'")
        
        summary = "\n".join(summary_parts)
        
        if self.config.verbose:
            print(f"\n   💉 Injection corrections:")
            print(f"      {summary[:100]}...")
        
        if self.config.dry_run:
            print(f"   🔍 [DRY-RUN] Créerait segment iris_internal")
            self.result.injections += 1
            return
        
        # Créer le segment interne
        segment_id = self.sbire.insert_segment_internal(
            resume=summary,
            source="mnemosyne_rectification",
            auteur="iris_internal"
        )
        
        if segment_id:
            self.result.segments_internes += 1
            self.result.injections += 1
            
            if self.config.verbose:
                print(f"      ✅ Segment iris_internal créé (ID {segment_id})")
    
    def _inject_trajectoires_summary(self, trajectoires: Dict):
        """
        Injecte un résumé des trajectoires comme segment iris_internal.
        """
        traj_list = trajectoires.get("trajectoires", [])
        if not traj_list:
            return
        
        # Construire le résumé
        summary_parts = ["[Réflexion interne] Évolutions de pensée observées:"]
        
        for t in traj_list[:5]:
            ancien = t.get("ancien", "")
            nouveau = t.get("nouveau", "")
            type_evol = t.get("type", "TRAJECTOIRE")
            
            summary_parts.append(f"• [{type_evol}] {ancien} → {nouveau}")
        
        summary = "\n".join(summary_parts)
        
        if self.config.verbose:
            print(f"\n   💉 Injection trajectoires:")
            print(f"      {summary[:100]}...")
        
        if self.config.dry_run:
            print(f"   🔍 [DRY-RUN] Créerait segment iris_internal")
            self.result.injections += 1
            return
        
        # Créer le segment interne
        segment_id = self.sbire.insert_segment_internal(
            resume=summary,
            source="mnemosyne_reflexion",
            auteur="iris_internal"
        )
        
        if segment_id:
            self.result.segments_internes += 1
            self.result.injections += 1
            
            if self.config.verbose:
                print(f"      ✅ Segment iris_internal créé (ID {segment_id})")
    
    def _update_notes_file(self, corrections: Dict, trajectoires: Dict):
        """
        Met à jour le fichier de notes Mnémosyne (optionnel).
        
        Ce fichier peut être injecté dans le contexte d'Iris
        pour une conscience plus directe.
        """
        # Vérifier si on a quelque chose à noter
        has_content = (
            corrections.get("corrections_detectees", 0) > 0 or
            trajectoires.get("trajectoires_detectees", 0) > 0
        )
        
        if not has_content:
            return
        
        # Construire la note
        now = datetime.now().isoformat()[:19]
        
        note_lines = [
            f"\n## Session Mnémosyne - {now}",
            ""
        ]
        
        # Corrections
        if corrections.get("details"):
            note_lines.append("### Corrections mémorisées")
            for d in corrections.get("details", [])[:3]:
                nouveau = d.get("nouveau_fait", "")
                note_lines.append(f"- ✓ {nouveau}")
            note_lines.append("")
        
        # Trajectoires
        if trajectoires.get("trajectoires"):
            note_lines.append("### Évolutions détectées")
            for t in trajectoires.get("trajectoires", [])[:3]:
                note_lines.append(f"- {t.get('ancien', '?')} → {t.get('nouveau', '?')}")
            note_lines.append("")
        
        # Piliers
        if trajectoires.get("piliers"):
            note_lines.append("### Piliers proposés")
            for p in trajectoires.get("piliers", [])[:3]:
                note_lines.append(f"- [{p.get('categorie', '?')}] {p.get('fait', '?')}")
            note_lines.append("")
        
        note_content = "\n".join(note_lines)
        
        if self.config.dry_run:
            print(f"   🔍 [DRY-RUN] Ajouterait au fichier de notes:")
            print(f"      {note_content[:100]}...")
            self.result.notes_fichier += 1
            return
        
        # Écrire dans le fichier
        try:
            # Créer le dossier si nécessaire
            MNEMOSYNE_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
            
            # Lire le contenu existant (ou créer)
            if MNEMOSYNE_NOTES_PATH.exists():
                existing = MNEMOSYNE_NOTES_PATH.read_text(encoding='utf-8')
            else:
                existing = "# Notes Mnémosyne\n\nRéflexions internes du système de cohérence mémorielle.\n"
            
            # Garder seulement les 50 dernières entrées (éviter fichier trop gros)
            sections = existing.split("\n## Session")
            if len(sections) > 50:
                existing = sections[0] + "\n## Session".join(sections[-49:])
            
            # Ajouter la nouvelle note
            new_content = existing + note_content
            MNEMOSYNE_NOTES_PATH.write_text(new_content, encoding='utf-8')
            
            self.result.notes_fichier += 1
            self.result.injections += 1
            
            if self.config.verbose:
                print(f"   📝 Fichier de notes mis à jour: {MNEMOSYNE_NOTES_PATH}")
                
        except Exception as e:
            self.result.erreurs.append(f"Fichier notes: {e}")
            if self.config.verbose:
                print(f"   ⚠️ Erreur fichier notes: {e}")
    
    def _to_dict(self) -> Dict[str, Any]:
        """Convertit le résultat en dictionnaire."""
        return {
            "injections": self.result.injections,
            "piliers_crees": self.result.piliers_crees,
            "segments_internes": self.result.segments_internes,
            "notes_fichier": self.result.notes_fichier,
            "erreurs": self.result.erreurs
        }


# =============================================================================
# FONCTIONS UTILITAIRES POUR INTÉGRATION AVEC IRIS
# =============================================================================

def get_mnemosyne_notes(max_entries: int = 10) -> str:
    """
    Récupère les dernières notes de Mnémosyne.
    
    Peut être appelé par context_window.py pour injection
    dans le contexte d'Iris.
    
    Args:
        max_entries: Nombre maximum d'entrées à retourner
        
    Returns:
        Texte des notes formaté pour injection
    """
    if not MNEMOSYNE_NOTES_PATH.exists():
        return ""
    
    try:
        content = MNEMOSYNE_NOTES_PATH.read_text(encoding='utf-8')
        
        # Extraire les dernières sessions
        sections = content.split("\n## Session")
        
        if len(sections) <= 1:
            return content
        
        # Garder les N dernières
        recent = sections[-max_entries:]
        
        return "## Session".join(recent)
        
    except Exception:
        return ""


def clear_mnemosyne_notes():
    """
    Efface les notes de Mnémosyne.
    
    Utile pour réinitialiser après une maintenance.
    """
    if MNEMOSYNE_NOTES_PATH.exists():
        MNEMOSYNE_NOTES_PATH.write_text(
            "# Notes Mnémosyne\n\nRéflexions internes du système de cohérence mémorielle.\n",
            encoding='utf-8'
        )
