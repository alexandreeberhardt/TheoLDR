# TheoLDR: guide for an agent

A tool that shortens Theo's (@theo) YouTube videos **by cutting only**: nothing added, nothing reordered. Two outputs per video: `tldr.mp4` (5 to 15 min) and `ttldr.mp4` (1 to 2 min). Theo has agreed; posting on X is done by hand.

## Running
```
uv run --extra qa theoldr latest          # latest long video on the channel, if not done yet
uv run --extra qa theoldr run <url|id>    # a specific video
uv run theoldr status                     # processed videos
```
Without `--extra qa`, everything works except the Whisper check of the joints.
Runs on macOS, Linux and Windows. OS-specific code lives in `system.py`; the Whisper check uses MLX on Apple Silicon and faster-whisper elsewhere. Tests (no network, no Claude): `uv run pytest`, also run by the CI on all three systems.
Time: 5 to 15 min per video, mostly the Claude calls. A video already done is not processed again without `--redo`.
Right after a video comes out, YouTube sometimes has no auto captions yet: the tool says so, just run it again later.

## Steps and files (`videos/<id>/`)
Each step writes its file and is skipped if that file already exists. After a crash, run the same command again.

| Step | File | Module |
|---|---|---|
| metadata, json3 auto captions, 720p video | `meta.json`, `subs.json3`, `source.mp4` | `fetch.py` |
| timestamped sentences | `transcript.json` | `transcript.py` |
| silences, possible clean cuts after each sentence | `silences.json` | `silences.py` |
| sponsors (SponsorBlock) | `sponsor.json` | `sponsor.py` |
| video outline (agent) | `outline.json` | `select.py` |
| TLDR: selection, 2 judges (blind and fidelity), up to 3 rounds; then TTLDR chosen from the TLDR, same loop | `attempts/tldr_roundN.json`, `attempts/ttldr_roundN.json`, `selection.json` | `select.py` |
| ffmpeg render | `cuts_*.json`, `tldr.mp4`, `ttldr.mp4` | `render.py` |
| checks | `qa.json`, `sheet_*.jpg`, `post.txt` | `qa.py`, `qa_audio.py` |

`source.mp4` is deleted at the end if everything is OK (`--keep-source` to keep it).

## Redoing part of it
- `--redo select`: redoes the outline and the selection (after a prompt change).
- `--redo selection`: keeps the outline, redoes the selection.
- `--redo render`: redoes only the render.
- Manual edit: change the `first`/`last` ranges of `tldr` or `ttldr` in `selection.json`, then run `run` again (the render detects that the cuts changed). It needs `source.mp4`: if it was deleted, it is downloaded again.

## Principles to keep
- The agent picks **sentence IDs**, never times. Cut times come from the silences (`cut_after`), which avoids cutting a word.
- A range can only start or end on a boundary with a silence; `normalize()` widens it otherwise.
- The `claude -p` calls are isolated (`agent.py`): empty folder, no tools, `--safe-mode`. Do not remove these options: the blind judge must see only the kept text.
- Judge scores: a continuous uncut excerpt of the original gets 4 to 6/10 for flow. Scores are only used to compare rounds. The success criterion is: no blocking issue, fidelity ≥ 8, length within limits, TTLDR in 6 pieces at most. If no round passes, the best one is rendered anyway (`passed: false` in `qa.json`).
- Revisions only receive the blocking issues: asking for more coverage makes the agent add fragments and chops up the video.
- `outline.json` and `selection.json` carry a fingerprint of the transcript: if `transcript.py` changes, they are redone automatically.
- Whisper transcribes other people's clips over music badly (reaction videos): a joint flagged there is often a false alarm. Check by transcribing a few seconds around it.

## Checking a result
1. `qa.json`: lengths, scores, `joints` (Whisper hears the expected words on each side of every cut).
2. `sheet_tldr.jpg`: frame just before and just after each cut.
3. Read the kept text (see `kept_text()` in `select.py`) as a viewer would.
