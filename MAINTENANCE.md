# 🔧 Guide de Maintenance — AIter Ego / MOSS

## Outils disponibles

Tous les scripts sont dans `app/utils/`.

---

## 1. Détection et suppression des doublons

**Script :** `detect_duplicates.py`

**Quand l'utiliser :**
- Après un gros import rétroactif
- Si tu soupçonnes des doublons
- Maintenance occasionnelle (1x par semaine)

**Commandes :**

```bash
cd ~/Dropbox/aiterego/app

# Vérifier s'il y a des doublons
python3 utils/detect_duplicates.py

# Voir les détails de chaque doublon
python3 utils/detect_duplicates.py --details

# Supprimer les doublons (avec confirmation)
python3 utils/detect_duplicates.py --delete

# Supprimer sans confirmation
python3 utils/detect_duplicates.py --delete --force
```

**Comment ça marche :**
- Un doublon = même `timestamp` (à la microseconde) + même `source_origine`
- Le script garde le premier (ID le plus bas) et supprime les autres

---

## 2. Suppression de conversations des exports JSON

**Script :** `delete_conversation.py`

**Quand l'utiliser :**
- Avant un import rétroactif pour nettoyer les exports ChatGPT/Claude
- Pour supprimer des conversations personnelles ou non pertinentes

**Commandes :**

```bash
cd ~/Dropbox/aiterego/app

# Lancer l'outil interactif
python3 utils/delete_conversation.py
```

**Commandes interactives :**
- Coller un titre → supprime la conversation
- `liste` → voir les 20 premiers titres
- `cherche mot` → chercher dans les titres
- `quit` → sauvegarder et quitter

**Note :** Le fichier cible est hardcodé : `~/Dropbox/aiterego_memory/echanges/exports/chatgpt/sources/conversations_serge.json`

---

## 3. Vérifications SQLite rapides

**Commandes directes :**

```bash
# Nombre de segments par source
sqlite3 ~/Dropbox/aiterego_memory/metadata.db \
  "SELECT source_origine, COUNT(*) FROM metadata GROUP BY source_origine;"

# Plage de dates
sqlite3 ~/Dropbox/aiterego_memory/metadata.db \
  "SELECT MIN(timestamp), MAX(timestamp) FROM metadata;"

# Segments d'un jour précis
sqlite3 ~/Dropbox/aiterego_memory/metadata.db \
  "SELECT timestamp, source_origine, auteur FROM metadata WHERE timestamp LIKE '2025-12-16%' ORDER BY timestamp;"

# Nombre total de segments
sqlite3 ~/Dropbox/aiterego_memory/metadata.db \
  "SELECT COUNT(*) FROM metadata;"

# Nombre de liens Arachné
sqlite3 ~/Dropbox/aiterego_memory/metadata.db \
  "SELECT type, COUNT(*) FROM edges GROUP BY type;"
```

---

## 4. Logs

**Emplacements :**

```
~/Dropbox/aiterego_memory/logs/
├── moss_YYYY-MM-DD.log    # Logs du serveur principal
├── democrone.log          # Logs du réveil nocturne d'Iris
└── fil_d_ariane.log       # Fil d'Ariane des réflexions
```

**Consulter les logs récents :**

```bash
# Dernières lignes du log du jour
tail -50 ~/Dropbox/aiterego_memory/logs/moss_$(date +%Y-%m-%d).log

# Suivre en temps réel
tail -f ~/Dropbox/aiterego_memory/logs/moss_$(date +%Y-%m-%d).log

# Logs Démocrone
cat ~/Dropbox/aiterego_memory/logs/democrone.log
```

---

## 5. Backups

**Base de données :**

```bash
# Backup manuel
cp ~/Dropbox/aiterego_memory/metadata.db ~/Dropbox/aiterego_memory/metadata_backup_$(date +%Y%m%d).db
```

**Branches Git :**
- Toujours créer une branche avant une grosse modification
- `git checkout -b backup-avant-modif`

---

## 6. Redémarrage du serveur

```bash
cd ~/Dropbox/aiterego/app

# Arrêter (Ctrl+C si en foreground, ou)
pkill -f "python3 main.py"

# Relancer
python3 main.py
```

---

## 7. Checklist maintenance hebdomadaire

- [ ] `python3 utils/detect_duplicates.py` — vérifier les doublons
- [ ] Vérifier les logs pour des erreurs
- [ ] `SELECT COUNT(*) FROM metadata` — noter la croissance
- [ ] Backup de metadata.db si gros changements

---

## 8. En cas de problème

**Le serveur ne démarre pas :**
1. Vérifier les logs
2. Vérifier que le port 5001 est libre : `lsof -i :5001`
3. Vérifier la connexion à la DB

**Erreur tiktoken `<|endoftext|>` :**
- Ajouter `disallowed_special=()` aux appels `encoding.encode()` dans `context_window.py`

**Doublons après import :**
- Normal si import avant la mise à jour de `scribe_retro.py`
- Lancer `python3 utils/detect_duplicates.py --delete`

---

*Dernière mise à jour : 2025-12-30 (Session 50)*