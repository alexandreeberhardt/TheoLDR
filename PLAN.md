# TheoLDR: plan

> Initial plan, kept for the record. How the tool actually works is described in `CLAUDE.md` (selection in two loops, TLDR then TTLDR, recalibrated judges, targeted revisions).

Goal: for each new YouTube video by Theo (@theo, t3dotgg), produce two shortened versions, by cutting only, with nothing added or reordered:
- **TTLDR**: 1 to 2 min (subset of the TLDR)
- **TLDR**: 5 to 15 min, length chosen from the video's density

Theo has agreed. Posting on X is done by hand (X Premium); the tool prepares a draft post.

## Constraints
- M4 Mac, 16 GB of RAM, heats up quickly: one heavy process at a time, no heavy local model by default.
- Disk: 5.4 GB free. 720p source (about 150 MB for 48 min), deleted after a successful render. Free space checked before any download.
- Agent: `claude -p` (the user's subscription), isolated, JSON outputs validated against a schema.
- Everything must be resumable: each step writes its file and is skipped if the file exists.

## Layout
```
theoldr/
  pyproject.toml          # uv, Python 3.12+, yt-dlp[default]
  theoldr/
    cli.py                # theoldr run <url> | theoldr latest | theoldr status
    fetch.py              # yt-dlp: 720p video, json3 auto captions, metadata
    sponsor.py            # SponsorBlock API (sponsor/selfpromo segments)
    transcript.py         # json3 -> timestamped words -> numbered sentences
    silences.py           # ffmpeg silencedetect -> silences + cuttable boundaries
    agent.py              # isolated claude -p call (empty folder, no tools, JSON schema)
    select.py             # outline, selection, verification passes
    snap.py               # sentences -> time intervals snapped to silences
    render.py             # ffmpeg: trim + concat + short audio fades
    qa.py                 # automatic checks of the render
    latest.py             # latest long unprocessed video from @theo
  prompts/plan.md, select.md, verify.md
  videos/<id>/            # one folder per video
  CLAUDE.md               # guide for an agent
```

Folder per video:
```
meta.json  source.mp4  subs.json3  sponsor.json  transcript.json  silences.json
outline.json  selection.json  verify.json  cuts_tldr.json  cuts_ttldr.json
tldr.mp4  ttldr.mp4  post.txt  qa.json  log.txt
```

## Steps

1. **fetch**: `yt-dlp --js-runtimes node -f "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]" --merge-output-format mp4`, `--write-auto-subs --sub-format json3 --sub-langs "en-orig,en"`, `--write-info-json`. Always the **auto** track (the only one with per-word timestamps); manual captions are a last resort only. Skip Shorts (< 3 min) and ongoing lives.
2. **sponsor**: SponsorBlock `GET /api/skipSegments?videoID=...&categories=...`, URL-encoded parameter. A 404 means "no segments", not an error. Segments are always excluded. If SponsorBlock has nothing (video too recent), the agent spots the sponsor in the transcript.
3. **transcript**: json3 gives the start of each word (`tOffsetMs`). End of a word = start of the next one. Auto captions are punctuated: split into sentences on `. ? !`, falling back on real silences if a video has no punctuation. Sentences numbered `S0001`, with start, end, duration, text. No chapters needed. Fallback without captions: mlx-whisper `small` with word timestamps, run alone, after a disk space check.
4. **silences**: `ffmpeg -af silencedetect=n=-35dB:d=0.2` on the audio only. Each boundary between sentences is marked **cuttable** if a silence exists within ±0.6 s (about 78% of measured cases).
5. **outline (agent, pass 1)**: from the full transcript and the title, the agent produces the outline: thesis, key points in order, conclusion, with their sentence ranges, and a density estimate that sets the TLDR target length (5 to 15 min).
6. **selection (agent, pass 2)**: the agent picks ranges of **sentences** (IDs, never timestamps) for the TLDR, then a subset for the TTLDR. The prompt gives each sentence's duration and shows the cuttable boundaries; a range can only start or end on a cuttable boundary (otherwise the script widens it to the nearest one). Rules: chronological order, every point of the outline covered in the TLDR, thesis and conclusion in both, no sponsor, no ritual intro/outro. The script validates (IDs, order, TTLDR inside TLDR, hard limits 5-15 min and 1-2 min) and sends the measured gap back to the agent if invalid (2 attempts).
7. **verification (agent, pass 3)**: an isolated call receives **only** the kept text. It flags orphan references ("as I was saying", a term never introduced), logic jumps, and rates understanding out of 10. If the score is < 7: pass 2 runs again with this feedback (2 loops max).
8. **fallback**: if the loops fail, the best attempt is rendered anyway and flagged in `qa.json`. A video always produces a result.
9. **snap**: each range becomes a [start, end] interval, bounds in the middle of the nearest silence. Ranges less than 1.5 s apart are merged, ranges < 2 s are removed. Lengths and inclusion recomputed after snapping.
10. **render**: a single ffmpeg with `trim`/`atrim` + `setpts`/`asetpts` + 20 ms `afade` in and out of each segment + `concat`. `h264_videotoolbox` encoding, AAC 160k, `+faststart`. 720p output.
11. **qa**: actual vs planned length, number of cuts, shortest segment, audio level at each joint (warning if a cut falls outside a silence). Contact sheet of thumbnails at the cuts for a visual check.
12. **post**: `post.txt` with title, length, link to the original video. macOS notification at the end. `source.mp4` deleted if qa is OK.

## Agent calls
- `claude -p` run from an empty temporary folder, without tools or MCP (`--tools ""`, `--strict-mcp-config`, restricted `--setting-sources`), with a dedicated `--system-prompt`, text on stdin, output through `--json-schema`. That way the global CLAUDE.md does not interfere and pass 3 cannot read the full transcript.
- Flag combination validated by a test call at the very start of the night.
- A quota error is not invalid JSON: wait and resume, without using up an attempt.

## Triggering (manual for now)
- `theoldr run <url>`: processes one video.
- `theoldr latest`: lists the latest videos with `yt-dlp --flat-playlist --playlist-end 5 "https://www.youtube.com/@theo/videos"` (the YouTube RSS feed returns 404) and processes the most recent one not done yet.
- Run under `caffeinate -i`, with a lock to prevent two simultaneous runs.
- `CLAUDE.md` describes how an agent reruns, debugs or edits a selection (edit `selection.json` then rerun from snap).

## Plan for the night
1. Install `yt-dlp[default]` with uv, validate the isolated `claude -p` call, write the code step by step.
2. Test on the 5 videos in `links.txt`, one at a time, cleaning the disk between each.
3. For each video: check the qa, look at the contact sheet, read the output transcript as a viewer would.
4. Tune prompts and thresholds, rerun the failed videos.
5. Code review by a subagent, fixes, atomic git commits (no push).
6. Test `theoldr latest` end to end.
7. Morning report: videos produced, lengths, verification scores, weak points.

## Decisions
- Sponsors cut (approved).
- Manual triggering (approved).
- TLDR length varies with density (default choice).
