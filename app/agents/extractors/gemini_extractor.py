"""
Extracteur utilisant Gemini 2.5 Flash Lite (Google AI Studio).
Clio v2.2 - Extraction de métadonnées pour MOSS Schema v2

Version: 2.2.0 (Session 68 - Gestion blocs CODE encapsulés)
Changements v2.2:
- Instruction pour ignorer les blocs [CODE:langage:START]...[CODE:langage:END]
- Noter le type de code dans "sujets" sans parser le contenu
- Évite les erreurs JSON causées par code avec caractères spéciaux

Historique:
- v2.0.0 (Session 58): Refonte complète, champs épurés
- v2.1.0 (Session 61): Blocs thématiques, gr_id, confidence_score
- v2.2.0 (Session 68): Gestion blocs CODE encapsulés
"""

import os
import json
import re
import asyncio
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

from .base import BaseExtractor

# Charger les variables d'environnement
env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(env_path)

from google import genai
from google.genai import types

# === CONFIGURATION ===
GEMINI_MODEL = "gemini-2.5-flash-lite"
MAX_TEXT_LENGTH = 3000  # Limite de texte par segment

# === LISTES DE RÉFÉRENCE ===
# Ces listes sont synchronisées avec les tables SQL projets et personnes

KNOWN_PROJECTS = {
    # Projet principal et sous-projets
    "moss", "aiter ego", "alter ego", "iris", "hermès", "hermes", 
    "clio", "arachné", "arachne", "trildasa", "orbito", "neandertal",
    # Autres projets
    "hits for hiit", "casper", "larcem", "crsh_voix_ia", "oicrm-ulaval"
}

KNOWN_PERSONS = {
    # Format: variante -> nom canonique
    "serge": "Serge Lacasse",
    "serge lacasse": "Serge Lacasse",
    "christian": "Christian Gagné",  # Note: peut être ambigu
    "christian gagné": "Christian Gagné",
    "christian gagne": "Christian Gagné",
    "sophie": "Sophie Stévance",
    "sophie stévance": "Sophie Stévance",
    "sophie stevance": "Sophie Stévance",
    "jérémie": "Jérémie Hatier",
    "jeremie": "Jérémie Hatier",
    "jeremy": "Jérémie Hatier",
    "jérémie hatier": "Jérémie Hatier",
    "jérémie attier": "Jérémie Hatier",
    "alex": "Alex Baker",
    "alex baker": "Alex Baker",
    "rose": "Rose"
}

# === INSTRUCTIONS SYSTÈME v2.1 ===
SCRIBE_SYSTEM_INSTRUCTION = """Tu es Clio, le Scribe du projet MOSS (Memory-Oriented Semantic System).
Ton rôle est d'analyser les échanges conversationnels et d'extraire des métadonnées structurées.

=== RÈGLES FONDAMENTALES ===
1. Tu retournes UNIQUEMENT un objet JSON valide. Pas de markdown (```json), pas de texte avant/après.
2. Tu es un observateur neutre. Tu ne réponds JAMAIS à l'utilisateur.
3. Tu analyses l'émotion (modèle Russell: valence/activation) et la sémantique (tags Roget).

=== FILTRE DE PERTINENCE (CRITIQUE) ===

AVANT TOUTE ANALYSE, évalue si ce segment mérite d'être indexé.

Un segment est INDEXABLE (indexable: true) s'il offre au moins UNE "prise" pour une future recherche:
- Contient une ENTITÉ nommée (personne, projet, sujet identifiable)
- Contient un FAIT temporel ou factuel vérifiable  
- Exprime une ÉMOTION distincte (valence < -0.3 ou > +0.3)
- Développe un CONCEPT, une idée, une décision, une réflexion

Un segment est NON-INDEXABLE (indexable: false) s'il est:
- Phatique pur: "Bonjour", "Salut", "Merci", "De rien", "Bonne journée"
- Accusé de réception: "Ok", "D'accord", "Je note", "C'est noté", "Parfait", "Entendu"
- Méta-procédural: "Je réfléchis...", "Un instant...", "Voyons voir...", "Laisse-moi vérifier"
- Répétition stricte sans ajout d'information

SI indexable = false, retourne UNIQUEMENT: {"indexable": false}
SI indexable = true, retourne le JSON complet ci-dessous.

=== SCHÉMA JSON v2.1 ===
{
  "indexable": true,
  "gr_id": 1,
  "tags_roget": ["CC-SSSS-TTTT"],
  "emotion_valence": 0.0,
  "emotion_activation": 0.5,
  "personnes": [],
  "projets": [],
  "sujets": [],
  "lieux": [],
  "resume_texte": "Résumé narratif de l'échange (max 200 tokens).",
  "continuite_ou_rupture": "Explication de la décision gr_id",
  "confidence_score": 0.95,
  "personne_candidat": null,
  "projet_candidat": null
}

=== BLOCS THÉMATIQUES (gr_id) - NOUVEAU v2.1 ===

Le gr_id est un IDENTIFIANT DE BLOC THÉMATIQUE, PAS un numéro de segment.
Tous les segments sur le MÊME THÈME partagent le MÊME gr_id.
Nouveau gr_id UNIQUEMENT si RUPTURE THÉMATIQUE CLAIRE.

CRITÈRES DE CONTINUITÉ (garder le même gr_id):
- Tags similaires ou de la même famille de concepts
- Sujets étroitement liés ou qui se complètent
- Mêmes entités nommées (logiciels, personnes, produits)
- Le segment développe, explique ou approfondit le précédent
- Pas de changement de direction majeur

CRITÈRES DE RUPTURE (nouveau gr_id):
- Changement de sujet clair et net
- Introduction d'un thème complètement différent
- L'utilisateur pose une question sans rapport avec le contexte précédent

EXEMPLE CONCRET:
- Segment 1: "Quel DAW choisir?" → gr_id=1
- Segment 2: "Pro Tools vs Nuendo" → gr_id=1 (même thème: logiciels audio)
- Segment 3: "Configuration Mac Studio" → gr_id=1 (même thème: setup studio)
- Segment 4: "RAM et SSD pour l'audio" → gr_id=1 (même thème: hardware audio)
- Segment 5: "Quelles pommes sont les plus sucrées?" → gr_id=2 (RUPTURE: nouveau sujet)
- Segment 6: "Les Gala sont très sucrées" → gr_id=2 (même thème: pommes)

NOTE: En mode segment unique, utilise gr_id=1 par défaut. 
En mode batch, numérote les blocs séquentiellement (1, 2, 3...) selon les ruptures.

=== CONFIDENCE_SCORE - NOUVEAU v2.1 ===

Score de confiance GLOBAL sur la qualité de ton extraction (0.0 à 1.0).

- 0.95-1.0: Extraction très fiable, entités claires, contexte sans ambiguïté
- 0.80-0.94: Bonne confiance, quelques inférences mineures
- 0.60-0.79: Confiance moyenne, ambiguïtés présentes
- < 0.60: Faible confiance, segment ambigu ou fragmentaire

Facteurs qui DIMINUENT le score:
- Texte fragmentaire ou incomplet
- Ambiguïté sur les personnes (prénom seul sans contexte)
- Tags Roget incertains
- Émotion difficile à évaluer

=== DESCRIPTION DES CHAMPS ===

### indexable (OBLIGATOIRE)
- true: Le segment contient de l'information recherchable
- false: Le segment est phatique/vide (retourner SEULEMENT {"indexable": false})

### gr_id (NOUVEAU v2.1)
- Identifiant numérique du bloc thématique
- Segments consécutifs sur le même thème = même gr_id
- Rupture thématique = incrémenter gr_id

### tags_roget (max 5)
Format strict: CC-SSSS-TTTT
- CC = 2 chiffres (classe 01-08)
- SSSS = 4 chiffres (section avec padding)
- TTTT = 4 chiffres (tag avec padding)
Exemples valides: "01-0010-0010", "04-0110-0020", "06-0510-0030"

### emotion_valence
Modèle Russell Circumplex
- -1.0 = très négatif (tristesse, colère, frustration)
- 0.0 = neutre
- +1.0 = très positif (joie, enthousiasme, satisfaction)

### emotion_activation  
Modèle Russell Circumplex
- 0.0 = très calme (relaxé, serein, fatigué)
- 0.5 = neutre
- 1.0 = très intense (excité, agité, stressé)

### personnes
Noms de personnes humaines physiques mentionnées.
- Exemples: ["Christian Gagné", "Sophie Stévance", "Jérémie"]
- NE PAS inclure: IA (Claude, GPT), identifiants techniques, termes génériques

PERSONNES CONNUES (utiliser ces noms si reconnus):
- Serge Lacasse (variantes: Serge)
- Christian Gagné (variantes: Christian, Christian Gagne) - contexte: MOSS, IID, Mila
- Sophie Stévance (variantes: Sophie, Sophie Stevance) - contexte: OICRM, recherche
- Jérémie Hatier (variantes: Jérémie, Jeremie, Jeremy) - contexte: physique, MOSS
- Alex Baker (variantes: Alex) - contexte: physique, brevets
- Rose - contexte: famille

### projets
UNIQUEMENT les projets de la LISTE CONNUE ci-dessous.
Si un projet n'est pas dans la liste → le mettre dans "sujets" ET dans "projet_candidat"

PROJETS CONNUS:
- MOSS, AIter Ego (projet principal mémoire IA)
- Iris, Hermès, Clio, Arachné (sous-composants MOSS)
- TriLDaSA (moteur vectoriel)
- Orbito (jeu mémoire)
- Neandertal (recherche OICRM)
- Hits for HIIT, CASPER, LARCEM (autres projets recherche)

### sujets (max 5)
Tout ce dont on parle: technologies, organisations, concepts, outils, thèmes.
C'est le champ "fourre-tout" pour la recherche générale.
- Exemples: ["SQLite", "Python", "Université Laval", "mémoire artificielle", "API Gemini"]
- Inclut: TIC, organisations, concepts, outils, thèmes de discussion

### lieux
CHAMP DÉSACTIVÉ - Toujours retourner []
Réservé pour géolocalisation GPS future.

### resume_texte
Résumé narratif de l'échange en UNE À TROIS phrases.
- Maximum 200 tokens (~150 mots)
- Doit capturer l'essentiel: qui, quoi, décision, émotion principale
- Style: prose narrative, pas de liste

### continuite_ou_rupture
Explication courte de ta décision pour gr_id.
- Exemples: "Même thème: configuration audio", "RUPTURE: nouveau sujet (alimentation)"

### confidence_score (NOUVEAU v2.1)
Score de confiance global sur l'extraction (0.0 à 1.0).
- Reflète ta certitude sur l'ensemble des champs extraits.

### personne_candidat (optionnel)
Si une personne est mentionnée mais n'est PAS dans la liste connue:
- Mettre son nom ici pour validation humaine ultérieure
- Exemple: "Tommy Bhikla-Rodrigue"

### projet_candidat (optionnel)  
Si quelque chose RESSEMBLE à un projet mais n'est PAS dans la liste connue:
- Mettre son nom ici pour validation humaine ultérieure
- Indices: nom propre, "on travaille sur", "le projet", développement en cours
- Exemple: "Argos"

=== EXEMPLES COMPLETS ===

TEXTE: "Bonjour Claude!"
→ {"indexable": false}

TEXTE: "Ok, merci!"
→ {"indexable": false}

TEXTE: "J'ai déployé le code MOSS sur Azure avec GitHub Actions"
→ {
  "indexable": true,
  "gr_id": 1,
  "tags_roget": ["06-0590-0010"],
  "emotion_valence": 0.2,
  "emotion_activation": 0.5,
  "personnes": [],
  "projets": ["MOSS"],
  "sujets": ["Azure", "GitHub Actions", "déploiement"],
  "lieux": [],
  "resume_texte": "Déploiement du code MOSS sur Azure en utilisant GitHub Actions.",
  "continuite_ou_rupture": "Nouveau bloc: déploiement cloud",
  "confidence_score": 0.95,
  "personne_candidat": null,
  "projet_candidat": null
}

TEXTE: "Réunion avec Christian Gagné à l'Université Laval pour discuter de MOSS et TriLDaSA"
→ {
  "indexable": true,
  "gr_id": 1,
  "tags_roget": ["04-0110-0020", "08-0720-0010"],
  "emotion_valence": 0.1,
  "emotion_activation": 0.4,
  "personnes": ["Christian Gagné"],
  "projets": ["MOSS", "TriLDaSA"],
  "sujets": ["Université Laval", "réunion"],
  "lieux": [],
  "resume_texte": "Réunion avec Christian Gagné à l'Université Laval concernant les projets MOSS et TriLDaSA.",
  "continuite_ou_rupture": "Nouveau bloc: réunion professionnelle",
  "confidence_score": 0.98,
  "personne_candidat": null,
  "projet_candidat": null
}

TEXTE: "Je suis vraiment frustré, ça fait 3 heures que je debug ce problème de SQLite"
→ {
  "indexable": true,
  "gr_id": 1,
  "tags_roget": ["06-0590-0010", "04-0110-0030"],
  "emotion_valence": -0.6,
  "emotion_activation": 0.7,
  "personnes": [],
  "projets": [],
  "sujets": ["SQLite", "debug", "problème technique"],
  "lieux": [],
  "resume_texte": "Frustration après trois heures de debugging d'un problème SQLite.",
  "continuite_ou_rupture": "Nouveau bloc: debugging technique",
  "confidence_score": 0.92,
  "personne_candidat": null,
  "projet_candidat": null
}

TEXTE: "Tommy m'a parlé du projet Argos hier"
→ {
  "indexable": true,
  "gr_id": 1,
  "tags_roget": ["08-0720-0010"],
  "emotion_valence": 0.0,
  "emotion_activation": 0.3,
  "personnes": ["Tommy"],
  "projets": [],
  "sujets": ["Argos"],
  "lieux": [],
  "resume_texte": "Discussion avec Tommy à propos du projet Argos.",
  "continuite_ou_rupture": "Nouveau bloc: projet externe",
  "confidence_score": 0.85,
  "personne_candidat": "Tommy",
  "projet_candidat": "Argos"
}

=== BLOCS DE CODE ENCAPSULÉS ===

Quand tu rencontres un bloc [CODE:langage:START]...[CODE:langage:END]:
1. IGNORE son contenu pour l'analyse sémantique (ne parse pas le code)
2. Note dans "sujets" qu'il y a eu du code, ex: ["code Python", "script SQL"]
3. Ne tente PAS d'analyser la syntaxe du code lui-même
4. Le bloc peut contenir des caractères spéciaux (backslashes, guillemets) - ignore-les

Exemple:
TEXTE: "Voici le script de migration [CODE:python:START]def migrate():\n    pass[CODE:python:END]"
→ sujets: ["migration", "code Python"]

=== CONTENU MATHÉMATIQUE/SCIENTIFIQUE ===

Quand le texte contient des formules, symboles grecs (Λ, Ω, σ, μ, ν, ρ, π, α, β), 
exposants Unicode (¹²³⁴⁵⁶⁷⁸⁹⁰), indices, ou notation scientifique :
- INDEXE normalement (indexable: true)
- Dans "sujets": note les concepts (ex: ["cosmologie", "constante cosmologique", "relativité générale"])
- Dans "tags_roget": utilise les catégories sciences/physique appropriées
- Dans "resume_texte": décris le contenu en prose, SANS recopier les symboles Unicode directement
  - Écris "10^120" au lieu de "10¹²⁰"
  - Écris "Lambda" ou "constante cosmologique" au lieu de "Λ"
  - Écris "Omega" au lieu de "Ω"
- Ces segments sont IMPORTANTS - haute valeur scientifique

=== RAPPELS CRITIQUES ===
1. Si le segment est vide/phatique → {"indexable": false} et RIEN D'AUTRE
2. Maximum 5 tags_roget, 5 sujets
3. resume_texte: max 200 tokens, style narratif
4. projets: SEULEMENT la liste connue, sinon → sujets + projet_candidat
5. lieux: toujours []
6. gr_id: même numéro si continuité thématique, incrémenter si rupture
7. confidence_score: évalue ta confiance globale (0.0-1.0)
8. BLOCS CODE: ignorer le contenu [CODE:...:START]...[CODE:...:END], noter le langage dans sujets
"""

# Prompt pour analyse individuelle
FEW_SHOT_PROMPT = """Analyse le texte suivant selon les instructions système.

TEXTE À ANALYSER :
{text}
"""

# Prompt Batch avec contexte pour gr_id - v2.2 avec continuité inter-batch
BATCH_PROMPT_TEMPLATE = """Analyse ces {count} segments DANS L'ORDRE.
Retourne un tableau JSON contenant exactement {count} objets (un par segment).
Chaque objet doit suivre le schéma v2.1 des instructions système.

IMPORTANT pour gr_id - CONTINUITÉ INTER-BATCH:
- Le dernier gr_id utilisé dans le batch PRÉCÉDENT était: {last_gr_id}
- Pour le premier segment indexable de CE batch:
  - Si CONTINUITÉ thématique avec le batch précédent → utilise {last_gr_id}
  - Si RUPTURE thématique → utilise {next_gr_id}
- Garde le MÊME gr_id si le segment suivant est dans la CONTINUITÉ thématique
- INCRÉMENTE gr_id UNIQUEMENT s'il y a RUPTURE thématique claire
- Les segments non-indexables n'ont pas de gr_id

SEGMENTS À ANALYSER :
{segments}
"""


class GeminiExtractor(BaseExtractor):
    """
    Clio v2.2 - Extracteur de métadonnées utilisant Gemini 2.5 Flash Lite.
    Compatible avec MOSS Schema v2 + blocs thématiques + gestion blocs CODE.
    """
    
    def __init__(self, model: str = GEMINI_MODEL, batch_size: int = 5):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY non trouvée. Vérifiez votre fichier .env")
        
        self.model = model
        self.batch_size = batch_size
        self.client = genai.Client(api_key=self.api_key)
        
        print(f"✨ Clio v2.2 initialisée (modèle: {model})")
    
    @staticmethod
    def default_metadata() -> Dict:
        """Retourne les métadonnées par défaut pour le schéma v2.1."""
        return {
            "indexable": True,
            "gr_id": None,  # NULL par défaut, assigné par Scribe
            "tags_roget": [],
            "emotion_valence": 0.0,
            "emotion_activation": 0.5,
            "personnes": [],
            "projets": [],
            "sujets": [],
            "lieux": [],
            "resume_texte": "",
            "continuite_ou_rupture": None,
            "confidence_score": 0.5,  # Confiance moyenne par défaut
            "personne_candidat": None,
            "projet_candidat": None
        }
    
    def _get_config(self) -> types.GenerateContentConfig:
        """Configuration pour extraction JSON stricte."""
        return types.GenerateContentConfig(
            temperature=0.1,
            top_p=0.95,
            max_output_tokens=2048,
            response_mime_type="application/json",
            system_instruction=SCRIBE_SYSTEM_INSTRUCTION,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            ]
        )
    
    def _fix_roget_tag(self, tag: str) -> str:
        """Corrige un tag Roget vers le format CC-SSSS-TTTT."""
        if not tag or not isinstance(tag, str):
            return None
        
        tag = tag.strip()
        parts = tag.split('-')
        
        if len(parts) == 3:
            cc, ssss, tttt = parts
            if len(cc) == 2 and len(ssss) == 4 and len(tttt) == 4:
                return tag
            try:
                cc = cc.zfill(2)
                ssss = ssss.zfill(4)
                tttt = tttt.zfill(4)
                return f"{cc}-{ssss}-{tttt}"
            except:
                return None
        
        elif len(parts) == 4:
            try:
                cc = parts[0].zfill(2)
                ssss = (parts[1] + parts[2]).zfill(4)
                tttt = (parts[2] + parts[3]).zfill(4)
                return f"{cc}-{ssss}-{tttt}"
            except:
                return None
        
        elif len(parts) >= 6:
            try:
                cc = parts[0].zfill(2)
                ssss = parts[1].zfill(4)
                tttt = parts[2].zfill(4)
                return f"{cc}-{ssss}-{tttt}"
            except:
                return None
        
        return None
    
    def _validate_metadata(self, data: Dict) -> Dict:
        """Valide et complète les métadonnées v2.1."""
        default = self.default_metadata()
        
        # Si non-indexable, retourner juste ça
        if data.get('indexable') == False:
            return {"indexable": False}
        
        # Forcer indexable à True si on continue
        data['indexable'] = True
        
        # === NORMALISATION tags_roget ===
        if 'tags_roget' in data and isinstance(data['tags_roget'], list):
            fixed_tags = []
            for tag in data['tags_roget'][:5]:
                fixed = self._fix_roget_tag(tag)
                if fixed:
                    fixed_tags.append(fixed)
            data['tags_roget'] = fixed_tags
        
        # === FORCER lieux à [] ===
        data['lieux'] = []
        
        # === NORMALISATION sujets (max 5) ===
        if 'sujets' in data and isinstance(data['sujets'], list):
            data['sujets'] = data['sujets'][:5]
        
        # === NORMALISATION gr_id ===
        if 'gr_id' in data:
            if isinstance(data['gr_id'], (int, float)):
                data['gr_id'] = int(data['gr_id'])
            elif isinstance(data['gr_id'], str):
                try:
                    data['gr_id'] = int(data['gr_id'])
                except:
                    data['gr_id'] = None
            else:
                data['gr_id'] = None
        
        # === NORMALISATION confidence_score ===
        if 'confidence_score' in data:
            if isinstance(data['confidence_score'], (int, float)):
                # Clamp entre 0 et 1
                data['confidence_score'] = max(0.0, min(1.0, float(data['confidence_score'])))
            elif isinstance(data['confidence_score'], str):
                try:
                    data['confidence_score'] = max(0.0, min(1.0, float(data['confidence_score'])))
                except:
                    data['confidence_score'] = default['confidence_score']
            else:
                data['confidence_score'] = default['confidence_score']
        
        # === VÉRIFICATION projets contre liste connue ===
        if 'projets' in data and isinstance(data['projets'], list):
            valid_projects = []
            for proj in data['projets']:
                if isinstance(proj, str) and proj.lower() in KNOWN_PROJECTS:
                    valid_projects.append(proj)
                else:
                    # Projet inconnu → candidat
                    if proj and not data.get('projet_candidat'):
                        data['projet_candidat'] = proj
                    # L'ajouter aussi dans sujets
                    if 'sujets' not in data:
                        data['sujets'] = []
                    if proj and proj not in data['sujets']:
                        data['sujets'].append(proj)
            data['projets'] = valid_projects
        
        # === NORMALISATION personnes ===
        if 'personnes' in data and isinstance(data['personnes'], list):
            normalized = []
            for person in data['personnes']:
                if isinstance(person, str):
                    # Vérifier si c'est une personne connue
                    canonical = KNOWN_PERSONS.get(person.lower())
                    if canonical:
                        normalized.append(canonical)
                    else:
                        normalized.append(person)
                        # Personne inconnue → candidat
                        if not data.get('personne_candidat'):
                            data['personne_candidat'] = person
            data['personnes'] = normalized
        
        # === NORMALISATION resume_texte ===
        if 'resume_texte' in data:
            if isinstance(data['resume_texte'], list):
                data['resume_texte'] = ", ".join(str(x) for x in data['resume_texte'])
            # Tronquer si trop long (approximation: 200 tokens ≈ 800 caractères)
            if isinstance(data['resume_texte'], str) and len(data['resume_texte']) > 800:
                data['resume_texte'] = data['resume_texte'][:800] + "..."
        
        # === NORMALISATION champs numériques ===
        numeric_fields = ['emotion_valence', 'emotion_activation']
        for field in numeric_fields:
            if field in data:
                if isinstance(data[field], list):
                    data[field] = float(data[field][0]) if data[field] else 0.0
                elif isinstance(data[field], str):
                    try:
                        data[field] = float(data[field])
                    except:
                        data[field] = default[field]
        
        # === FUSION avec défauts ===
        for key, value in default.items():
            if key not in data or data[key] is None:
                # Ne pas écraser gr_id=None si c'est intentionnel
                if key == 'gr_id' and key in data:
                    continue
                data[key] = value
        
        return data
    
    def extract(self, text: str) -> Dict:
        """Extrait les métadonnées d'un texte unique."""
        if not text or len(text.strip()) < 3:
            return {"indexable": False}
        
        text = text[:MAX_TEXT_LENGTH]
        prompt = FEW_SHOT_PROMPT.format(text=text)
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._get_config()
            )
            
            if response.text:
                data = json.loads(response.text)
                return self._validate_metadata(data)
            
        except json.JSONDecodeError as e:
            print(f"⚠️ Erreur JSON: {e}")
        except Exception as e:
            print(f"⚠️ Erreur extraction: {e}")
        
        return self.default_metadata()
    
    def extract_batch(self, texts: List[str], last_gr_id: int = 0) -> List[Dict]:
        """
        Extrait les métadonnées d'un batch de textes avec continuité gr_id.
        
        Args:
            texts: Liste des textes à analyser
            last_gr_id: Dernier gr_id utilisé dans le batch précédent (pour continuité)
        
        Returns:
            Liste de métadonnées, une par texte
        """
        if not texts:
            return []
        
        segments_text = "\n\n".join([
            f"--- SEGMENT {i+1} ---\n{t[:MAX_TEXT_LENGTH]}"
            for i, t in enumerate(texts)
        ])
        prompt = BATCH_PROMPT_TEMPLATE.format(
            count=len(texts), 
            segments=segments_text,
            last_gr_id=last_gr_id,
            next_gr_id=last_gr_id + 1
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._get_config()
            )
            
            if response.text:
                results = json.loads(response.text)
                if isinstance(results, list):
                    return [self._validate_metadata(r) for r in results]
        
        except json.JSONDecodeError as e:
            print(f"⚠️ Erreur JSON batch: {e}")
        except Exception as e:
            print(f"⚠️ Erreur extraction batch: {e}")
        
        return [self.default_metadata() for _ in texts]
    
    async def extract_async(self, text: str) -> Dict:
        """Version asynchrone de extract()."""
        return await asyncio.to_thread(self.extract, text)
    
    async def extract_batch_async(self, texts: List[str], last_gr_id: int = 0) -> List[Dict]:
        """Version asynchrone de extract_batch()."""
        return await asyncio.to_thread(self.extract_batch, texts, last_gr_id)

# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("CLIO v2.2 - Test d'extraction (blocs thématiques + CODE)")
    print("=" * 60)
    
    try:
        extractor = GeminiExtractor()
        
        print("\n1. Test segment indexable...")
        test_text = "Réunion avec Christian Gagné pour discuter de MOSS et TriLDaSA à l'Université Laval"
        result = extractor.extract(test_text)
        print(f"   indexable: {result.get('indexable')}")
        print(f"   gr_id: {result.get('gr_id')}")
        print(f"   personnes: {result.get('personnes')}")
        print(f"   projets: {result.get('projets')}")
        print(f"   sujets: {result.get('sujets')}")
        print(f"   confidence_score: {result.get('confidence_score')}")
        print(f"   resume: {result.get('resume_texte')}")
        
        print("\n2. Test segment NON-indexable...")
        test_phatique = "Ok, merci beaucoup!"
        result_phatique = extractor.extract(test_phatique)
        print(f"   indexable: {result_phatique.get('indexable')}")
        print(f"   Résultat complet: {result_phatique}")
        
        print("\n3. Test candidats (personne/projet inconnus)...")
        test_candidat = "J'ai parlé avec Tommy du projet Argos"
        result_candidat = extractor.extract(test_candidat)
        print(f"   personnes: {result_candidat.get('personnes')}")
        print(f"   projets: {result_candidat.get('projets')}")
        print(f"   sujets: {result_candidat.get('sujets')}")
        print(f"   confidence_score: {result_candidat.get('confidence_score')}")
        print(f"   personne_candidat: {result_candidat.get('personne_candidat')}")
        print(f"   projet_candidat: {result_candidat.get('projet_candidat')}")
        
        print("\n4. Test batch avec continuité thématique...")
        batch_texts = [
            "Bonjour!",
            "Quel DAW devrais-je utiliser pour la production musicale?",
            "Pro Tools est excellent pour l'édition, Nuendo pour le mixage surround.",
            "Et pour la configuration Mac Studio, combien de RAM?",
            "Quelles pommes sont les plus sucrées?",
            "Les pommes Gala et Honeycrisp sont très sucrées."
        ]
        results = extractor.extract_batch(batch_texts)
        print("\n   Résultats batch:")
        for i, r in enumerate(results):
            if r.get('indexable') == False:
                print(f"   Segment {i+1}: NON-INDEXABLE")
            else:
                print(f"   Segment {i+1}: gr_id={r.get('gr_id')}, conf={r.get('confidence_score')}, "
                      f"sujets={r.get('sujets')}, rupture='{r.get('continuite_ou_rupture', 'N/A')}'")
        
        print("\n" + "=" * 60)
        print("✅ Tests Clio v2.2 terminés!")
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
