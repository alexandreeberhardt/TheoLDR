import json
import sys

from .common import SkipVideo, check_free_space, log, read_json, run, write_json

YTDLP = [sys.executable, "-m", "yt_dlp", "--encoding", "utf-8", "--js-runtimes", "node",
         "--no-progress", "--no-playlist"]
VIDEO_FORMAT = "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]"


def fetch_meta(video_id, folder):
    meta_path = folder / "meta.json"
    if meta_path.exists():
        return read_json(meta_path)
    url = f"https://www.youtube.com/watch?v={video_id}"
    result = run(YTDLP + ["--dump-single-json", "--skip-download", url], attempts=3)
    info = json.loads(result.stdout)
    meta = {
        "id": video_id,
        "url": url,
        "title": info.get("title"),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "live_status": info.get("live_status"),
        "chapters": info.get("chapters") or [],
        "description": info.get("description") or "",
    }
    if meta["live_status"] not in ("is_live", "is_upcoming") and meta["duration"]:
        write_json(meta_path, meta)
    return meta


def fetch_subs(video_id, folder):
    """YouTube's English auto captions, or None when YouTube has not made them yet."""
    subs_path = folder / "subs.json3"
    if subs_path.exists():
        return subs_path
    url = f"https://www.youtube.com/watch?v={video_id}"
    for lang in ["en-orig", "en"]:
        run(YTDLP + ["--skip-download", "--write-auto-subs", "--sub-format", "json3",
                     "--sub-langs", lang, "-o", str(folder / "subs"), url], attempts=3)
        candidate = folder / f"subs.{lang}.json3"
        if candidate.exists():
            candidate.rename(subs_path)
            return subs_path
    return None


def whisper_subs(words):
    """Whisper's (word, start, end) list in the json3 layout of YouTube's captions."""
    events = [{"tStartMs": round(start * 1000), "segs": [{"utf8": word.strip()}]}
              for word, start, end in words if word.strip()]
    return {"source": "whisper", "events": events}


def transcribe_subs(source, folder):
    """Captions made on this machine, for a video YouTube has not captioned yet."""
    from .qa_audio import raw_words, whisper_available
    if not whisper_available():
        raise RuntimeError("No English auto captions yet. YouTube makes them a few minutes to a few hours "
                           "after release: try again later, or install Whisper to transcribe here "
                           "(`uv sync --extra qa`).")
    subs = whisper_subs(raw_words(source))
    if not subs["events"]:
        raise RuntimeError("Whisper heard no speech in this video.")
    write_json(folder / "subs.json3", subs)


def fetch_video(video_id, folder):
    source = folder / "source.mp4"
    if source.exists():
        return source
    check_free_space()
    url = f"https://www.youtube.com/watch?v={video_id}"
    run(YTDLP + ["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "-o", str(source), url], attempts=3)
    return source


def fetch(video_id, folder, whisper_captions=False):
    """whisper_captions: transcribe here without asking YouTube for its captions."""
    meta = fetch_meta(video_id, folder)
    if meta["live_status"] in ("is_live", "is_upcoming"):
        raise RuntimeError("Live or upcoming stream: try again once the video is published")
    if (meta["duration"] or 0) < 180:
        raise SkipVideo("Video too short (Short)")
    log(folder, f"Video: {meta['title']} ({meta['duration'] // 60} min)")
    subs_path = folder / "subs.json3"
    if not whisper_captions:
        fetch_subs(video_id, folder)
    source = fetch_video(video_id, folder)
    log(folder, "Download finished")
    if not subs_path.exists():
        reason = "asked for" if whisper_captions else "YouTube has no captions yet"
        log(folder, f"Transcribing with Whisper ({reason})")
        transcribe_subs(source, folder)
    if read_json(subs_path).get("source") == "whisper" and meta.get("captions") != "whisper":
        meta["captions"] = "whisper"
        write_json(folder / "meta.json", meta)
    return meta
