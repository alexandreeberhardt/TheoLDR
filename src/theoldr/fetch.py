import json
import sys

from .common import SkipVideo, check_free_space, log, read_json, run, write_json

YTDLP = [sys.executable, "-m", "yt_dlp", "--js-runtimes", "node", "--no-progress", "--no-playlist"]
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
    raise RuntimeError("Pas encore de sous-titres automatiques anglais. YouTube les génère quelques minutes "
                       "à quelques heures après la sortie : réessayer plus tard.")


def fetch_video(video_id, folder):
    source = folder / "source.mp4"
    if source.exists():
        return source
    check_free_space()
    url = f"https://www.youtube.com/watch?v={video_id}"
    run(YTDLP + ["-f", VIDEO_FORMAT, "--merge-output-format", "mp4", "-o", str(source), url], attempts=3)
    return source


def fetch(video_id, folder):
    meta = fetch_meta(video_id, folder)
    if meta["live_status"] in ("is_live", "is_upcoming"):
        raise RuntimeError("Live en cours ou à venir : réessayer quand la vidéo sera publiée")
    if (meta["duration"] or 0) < 180:
        raise SkipVideo("Vidéo trop courte (Short)")
    log(folder, f"Vidéo : {meta['title']} ({meta['duration'] // 60} min)")
    fetch_subs(video_id, folder)
    fetch_video(video_id, folder)
    log(folder, "Téléchargement terminé")
    return meta
