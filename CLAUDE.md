# TheoLDR : procédure pour un agent

Outil qui raccourcit les vidéos YouTube de Theo (@theo) **uniquement par coupes** : pas d'ajout, pas de réordonnancement. Deux sorties par vidéo : `tldr.mp4` (5 à 15 min) et `ttldr.mp4` (1 à 2 min). Theo a donné son accord ; la publication sur X se fait à la main.

## Lancer
```
uv run --extra qa theoldr latest          # dernière vidéo longue de la chaîne, si pas déjà faite
uv run --extra qa theoldr run <url|id>    # une vidéo précise
uv run theoldr status                     # vidéos traitées
```
Sans `--extra qa`, tout marche sauf le contrôle Whisper des jonctions.
Durée : 5 à 15 min par vidéo, surtout les appels à Claude. Une vidéo déjà faite n'est pas retraitée sans `--redo`.
Juste après la sortie d'une vidéo, YouTube n'a parfois pas encore les sous-titres auto : l'outil le dit, il suffit de relancer plus tard.

## Étapes et fichiers (`videos/<id>/`)
Chaque étape écrit son fichier et est sautée s'il existe déjà. En cas de plantage, relancer la même commande.

| Étape | Fichier | Module |
|---|---|---|
| métadonnées, sous-titres auto json3, vidéo 720p | `meta.json`, `subs.json3`, `source.mp4` | `fetch.py` |
| phrases horodatées | `transcript.json` | `transcript.py` |
| silences, coupes propres possibles après chaque phrase | `silences.json` | `silences.py` |
| sponsors (SponsorBlock) | `sponsor.json` | `sponsor.py` |
| plan de la vidéo (agent) | `outline.json` | `select.py` |
| TLDR : sélection, 2 juges (à l'aveugle et fidélité), jusqu'à 3 tours ; puis TTLDR choisi dans le TLDR, même boucle | `attempts/tldr_roundN.json`, `attempts/ttldr_roundN.json`, `selection.json` | `select.py` |
| rendu ffmpeg | `cuts_*.json`, `tldr.mp4`, `ttldr.mp4` | `render.py` |
| contrôles | `qa.json`, `sheet_*.jpg`, `post.txt` | `qa.py`, `qa_audio.py` |

`source.mp4` est supprimé à la fin si tout est OK (`--keep-source` pour le garder).

## Refaire une partie
- `--redo select` : refait le plan et la sélection (après un changement de prompts).
- `--redo selection` : garde le plan, refait la sélection.
- `--redo render` : refait seulement le rendu.
- Retouche à la main : modifier les plages `first`/`last` de `tldr` ou `ttldr` dans `selection.json`, puis relancer `run` (le rendu détecte que les coupes ont changé). Il faut `source.mp4` : s'il a été supprimé, il est retéléchargé.

## Principes à respecter
- L'agent choisit des **identifiants de phrases**, jamais des temps. Les temps de coupe viennent des silences (`cut_after`), ce qui évite de couper un mot.
- Une plage ne peut commencer ou finir que sur une frontière avec silence ; `normalize()` l'étend sinon.
- Les appels `claude -p` sont isolés (`agent.py`) : dossier vide, aucun outil, `--safe-mode`. Ne pas retirer ces options : le juge à l'aveugle ne doit voir que le texte gardé.
- Notes des juges : un extrait continu de l'original non coupé obtient 4 à 6/10 en fluidité. Elles ne servent qu'à comparer les tours. Le critère de réussite est : aucun problème bloquant, fidélité ≥ 8, durée dans les bornes, TTLDR en 6 morceaux au plus. Si aucun tour ne passe, le meilleur est rendu quand même (`passed: false` dans `qa.json`).
- Les révisions ne reçoivent que les problèmes bloquants : demander plus de couverture fait ajouter des fragments et hache la vidéo.
- `outline.json` et `selection.json` portent une empreinte du transcript : si `transcript.py` change, ils sont refaits automatiquement.
- Whisper transcrit mal les extraits d'autres personnes sur fond de musique (vidéos de réaction) : une jonction signalée là est souvent une fausse alerte. Vérifier en retranscrivant quelques secondes autour.

## Vérifier un résultat
1. `qa.json` : durées, scores, `joints` (Whisper entend les mots attendus de part et d'autre de chaque coupe).
2. `sheet_tldr.jpg` : image juste avant et juste après chaque coupe.
3. Lire le texte gardé (voir `kept_text()` dans `select.py`) comme un spectateur.
