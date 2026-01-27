MOSS : Modular Orchestrated Storage System
MOSS est un framework d'orchestration d'IA multi-agents et une architecture de mémoire persistante conçue comme un Exocortex (cerveau externe). Il vise à augmenter les capacités de recherche, de synthèse et de gestion de projets complexes par une intégration profonde entre l'intelligence artificielle et la structure de données personnelle.

🚀 Innovation Systémique : Le Paradigme de la Mémoire Infinie
L'innovation majeure de MOSS réside dans sa capacité à transcender les limites intrinsèques des modèles de langage (LLM) actuels, notamment la volatilité du contexte et l'amnésie sessionnelle.

Mémoire Virtuellement Infinie : Par un mécanisme de "cascade mémorielle", MOSS assure une continuité cognitive totale. Chaque échange est indexé sémantiquement, vectorisé et archivé. Le système ne "finit" jamais une conversation ; il la déplace simplement d'un état volatil (L1) vers un état persistant (L2/L3/L4), permettant une récupération d'information précise même après plusieurs années.
Résolution du Paradoxe du Contexte : MOSS sépare la puissance de calcul de la fenêtre de discussion. Grâce à l'outil read_document, le système peut absorber des corpus massifs (1M+ tokens) dans un espace de travail dédié, injectant uniquement la synthèse pertinente dans la conversation active. Cela prévient la "dilution attentionnelle" et l'entropie du contexte.
Souveraineté et Agnosticisme : Contrairement aux solutions "Cloud" fermées, MOSS est agnostique quant aux modèles utilisés (Gemini, Claude, GPT) et maintient la propriété des données sur l'infrastructure de l'utilisateur (Dropbox/Drive), garantissant une pérennité du savoir indépendante des fournisseurs de services.
🏛️ Architecture de Collaboration (Le Conseil des Agents)
MOSS orchestre un écosystème d'agents spécialisés communiquant via un Blackboard (Tableau Blanc) asynchrone :

Collaboration Multi-Modèles : Utilisation synergique des forces de chaque LLM (Rigueur de Claude, Capacité de lecture de Gemini, Coordination d'Iris).
Synchronisation d'État : Le Blackboard permet de maintenir un "State of the Union" du projet, accessible par tous les agents, assurant une cohérence de vision malgré l'asynchronicité des sessions.
🧠 Territoire Cognitif et Auto-Réflexion
Le système dispose d'un espace de réflexion propre (iris/knowledge/) qui agit comme une couche de métacognition :

Fil d'Ariane (current_context.md) : Un registre dynamique des priorités et de l'état mental du système, servant de boussole lors de la réouverture de sessions.
Structuration Active : Iris ne se contente pas de stocker des données ; elle les organise activement dans des fichiers de connaissances structurés, transformant l'information brute en savoir actionnable.
🛠️ Spécifications Techniques
Hiérarchie de la Mémoire (Memory Stack)
L1 : Contexte Actif : Mémoire de travail immédiate.
L2 : Mémoire Épisodique (SQLite FTS5) : Indexation de l'historique complet des interactions.
L3 : Mémoire Sémantique (SQL Facts) : Base de connaissances atomiques et immuables.
L4 : Mémoire Structurelle (Markdown) : Documentation de projet et auto-réflexion.
Moteur de Recherche Hermès
QueryProfiler : Analyse d'intention pour pondération des recherches.
Arachné : Navigation par graphe de liens (associativité thématique, émotionnelle et temporelle).
📂 Structure du Dépôt
actions/ : Cœur logique, dispatching et outils de lecture/écriture.
iris/knowledge/ : Territoire de réflexion d'Iris et Fil d'Ariane.
documents/ : Zone d'indexation des sources externes (PDF, Code, Articles).
metadata.db : Index sémantique et épisodique principal.
Cette version pose MOSS comme une infrastructure de recherche sérieuse et innovante. C'est exactement le genre de ton qui valorisera ton projet, que ce soit pour le CRSH ou pour documenter ton brevet.