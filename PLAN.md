# TheoLDR : plan

> Plan initial, conservé pour mémoire. Le fonctionnement réel est décrit dans `CLAUDE.md` (sélection en deux boucles TLDR puis TTLDR, juges recalibrés, révisions ciblées).

Objectif : pour chaque nouvelle vidéo YouTube de Theo (@theo, t3dotgg), produire deux versions raccourcies, uniquement par coupes, sans ajout ni réordonnancement :
- **TTLDR** : 1 à 2 min (sous-ensemble du TLDR)
- **TLDR** : 5 à 15 min, durée choisie selon la densité de la vidéo

Theo a donné son accord. Publication sur X faite à la main (X Premium), l'outil prépare un brouillon de post.

## Contraintes
- Mac M4, 16 Go de RAM, chauffe vite : un seul process lourd à la fois, pas de modèle local lourd par défaut.
- Disque : 5,4 Go libres. Source 720p (environ 150 Mo pour 48 min), supprimée après rendu réussi. Contrôle d'espace libre avant tout téléchargement.
- Agent : `claude -p` (abonnement de l'utilisateur), isolé, sorties JSON validées par schéma.
- Tout doit être relançable : chaque étape écrit son fichier et est sautée si le fichier existe.

## Arborescence
```
theoldr/
  pyproject.toml          # uv, Python 3.12+, yt-dlp[default]
  theoldr/
    cli.py                # theoldr run <url> | theoldr latest | theoldr status
    fetch.py              # yt-dlp : vidéo 720p, sous-titres auto json3, métadonnées
    sponsor.py            # API SponsorBlock (segments sponsor/selfpromo)
    transcript.py         # json3 -> mots horodatés -> phrases numérotées
    silences.py           # ffmpeg silencedetect -> silences + frontières coupables
    agent.py              # appel claude -p isolé (dossier vide, sans outils, schéma JSON)
    select.py             # passes plan, sélection, vérification
    snap.py               # phrases -> intervalles de temps calés sur les silences
    render.py             # ffmpeg : trim + concat + micro-fondus audio
    qa.py                 # contrôles automatiques du rendu
    latest.py             # dernière vidéo longue non traitée de @theo
  prompts/plan.md, select.md, verify.md
  videos/<id>/            # un dossier par vidéo
  CLAUDE.md               # procédure pour un agent
```

Dossier par vidéo :
```
meta.json  source.mp4  subs.json3  sponsor.json  transcript.json  silences.json
outline.json  selection.json  verify.json  cuts_tldr.json  cuts_ttldr.json
tldr.mp4  ttldr.mp4  post.txt  qa.json  log.txt
```

## Étapes

1. **fetch** : `yt-dlp --js-runtimes node -f "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]" --merge-output-format mp4`, `--write-auto-subs --sub-format json3 --sub-langs "en-orig,en"`, `--write-info-json`. Toujours la piste **auto** (seule à avoir un horodatage par mot) ; les sous-titres manuels ne servent qu'en dernier recours. Ignorer Shorts (< 3 min) et lives en cours.
2. **sponsor** : SponsorBlock `GET /api/skipSegments?videoID=...&categories=...`, paramètre encodé en URL. Un 404 signifie « aucun segment », pas une erreur. Segments exclus d'office. Si SponsorBlock n'a rien (vidéo trop récente), l'agent repère le sponsor dans le transcript.
3. **transcript** : json3 donne le début de chaque mot (`tOffsetMs`). Fin d'un mot = début du suivant. Les sous-titres auto sont ponctués : découpe en phrases sur `. ? !`, repli sur les silences réels si une vidéo n'a pas de ponctuation. Phrases numérotées `S0001`, avec début, fin, durée, texte. Pas de chapitres requis. Repli si pas de sous-titres : mlx-whisper `small` avec timestamps au mot, lancé seul, après contrôle d'espace disque.
4. **silences** : `ffmpeg -af silencedetect=n=-35dB:d=0.2` sur l'audio seul. Chaque frontière entre phrases est marquée **coupable** si un silence existe à ±0,6 s (environ 78 % des cas mesurés).
5. **outline (agent, passe 1)** : à partir du transcript complet et du titre, l'agent produit le plan : thèse, points clés dans l'ordre, conclusion, avec les plages de phrases associées, et une estimation de densité qui fixe la durée cible du TLDR (5 à 15 min).
6. **sélection (agent, passe 2)** : l'agent choisit des plages de **phrases** (identifiants, jamais des timestamps) pour le TLDR, puis un sous-ensemble pour le TTLDR. Le prompt donne la durée de chaque phrase et indique les frontières coupables ; une plage ne peut commencer ou finir que sur une frontière coupable (sinon le script l'étend à la plus proche). Règles : ordre chronologique, chaque point du plan couvert dans le TLDR, thèse et conclusion dans les deux, pas de sponsor, pas d'intro/outro rituelle. Le script valide (identifiants, ordre, inclusion TTLDR dans TLDR, bornes absolues 5-15 min et 1-2 min) et renvoie l'écart chiffré à l'agent si invalide (2 essais).
7. **vérification (agent, passe 3)** : un appel isolé ne reçoit **que** le texte conservé. Il signale les références orphelines (« comme je disais », terme jamais introduit), les sauts de logique, et note la compréhension sur 10. Si note < 7 : la passe 2 est relancée avec ces retours (2 boucles max).
8. **issue de secours** : si les boucles échouent, on rend quand même la meilleure tentative et on le signale dans `qa.json`. Une vidéo produit toujours un résultat.
9. **snap** : chaque plage devient un intervalle [début, fin], bornes au milieu du silence le plus proche. Fusion des plages séparées de moins de 1,5 s, suppression des plages < 2 s. Durées et inclusion recalculées après snap.
10. **render** : un seul ffmpeg avec `trim`/`atrim` + `setpts`/`asetpts` + `afade` 20 ms en entrée et sortie de chaque segment + `concat`. Encodage `h264_videotoolbox`, AAC 160k, `+faststart`. Sortie 720p.
11. **qa** : durée réelle vs prévue, nombre de coupes, plus petit segment, niveau audio à chaque jonction (avertissement si une coupe tombe hors silence). Planche de vignettes aux coupes pour contrôle visuel.
12. **post** : `post.txt` avec titre, durée, lien vers la vidéo originale. Notification macOS à la fin. Suppression de `source.mp4` si qa OK.

## Appels agent
- `claude -p` lancé depuis un dossier temporaire vide, sans outils ni MCP (`--tools ""`, `--strict-mcp-config`, `--setting-sources` restreint), avec `--system-prompt` dédié, texte sur stdin, sortie via `--json-schema`. Ainsi le CLAUDE.md global n'interfère pas et la passe 3 ne peut pas lire le transcript complet.
- Combinaison de flags validée par un appel d'essai en tout début de nuit.
- Une erreur de quota n'est pas un JSON invalide : on attend et on reprend, sans consommer d'essai.

## Déclenchement (manuel pour l'instant)
- `theoldr run <url>` : traite une vidéo.
- `theoldr latest` : liste les dernières vidéos avec `yt-dlp --flat-playlist --playlist-end 5 "https://www.youtube.com/@theo/videos"` (le flux RSS YouTube renvoie 404) et traite la plus récente pas encore faite.
- Lancé sous `caffeinate -i`, verrou pour éviter deux runs simultanés.
- `CLAUDE.md` décrit comment un agent relance, débogue ou retouche une sélection (modifier `selection.json` puis relancer à partir de snap).

## Plan de la nuit
1. Installer `yt-dlp[default]` via uv, valider l'appel `claude -p` isolé, écrire le code étape par étape.
2. Tester sur les 5 vidéos de `liens.txt`, une à la fois, avec nettoyage disque entre chaque.
3. Pour chaque vidéo : vérifier le qa, regarder la planche de vignettes, relire le transcript de sortie comme un spectateur.
4. Ajuster prompts et seuils, relancer les vidéos ratées.
5. Relecture du code par un sous-agent, corrections, commits git atomiques (pas de push).
6. Tester `theoldr latest` de bout en bout.
7. Rapport du matin : vidéos produites, durées, notes de vérification, points faibles.

## Décisions
- Sponsors coupés (validé).
- Déclenchement manuel (validé).
- Durée du TLDR variable selon la densité (choix par défaut).
