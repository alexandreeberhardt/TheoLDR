import argparse
import fcntl
import json
import os
import subprocess
import sys

from .common import CHANNEL_URL, SkipVideo, ROOT, VIDEOS_DIR, log, read_json, video_dir, video_id_from, write_json
from .fetch import YTDLP, fetch
from .qa import check, write_post
from .render import media_duration, render_version
from .select import final_ranges, select
from .silences import detect_silences, mark_boundaries
from .sponsor import fetch_sponsors, mark_sponsors
from .transcript import build_transcript

STEP_FILES = {
    "select": ["outline.json", "selection.json", "attempts"],
    "selection": ["selection.json", "attempts"],
    "render": ["tldr.mp4", "ttldr.mp4", "cuts_tldr.json", "cuts_ttldr.json"],
}


def prepare(video_id, folder):
    meta = fetch(video_id, folder)
    if "file_duration" not in meta:
        meta["file_duration"] = media_duration(folder / "source.mp4")
        write_json(folder / "meta.json", meta)
    duration = meta["file_duration"]
    sentences = build_transcript(folder / "subs.json3", folder / "transcript.json", duration)
    silences = detect_silences(folder / "source.mp4", folder / "silences.json")
    mark_boundaries(sentences, silences, duration)
    mark_sponsors(sentences, fetch_sponsors(video_id, folder / "sponsor.json"))
    return meta, sentences


def reset(folder, step):
    for name in STEP_FILES.get(step, []):
        path = folder / name
        if path.is_dir():
            for child in path.iterdir():
                child.unlink()
            path.rmdir()
        elif path.exists():
            path.unlink()


def process(url_or_id, redo=None, keep_source=False):
    video_id = video_id_from(url_or_id)
    folder = video_dir(video_id)
    if (folder / "qa.json").exists() and not redo:
        print(f"Déjà traitée : {folder} (utiliser --redo pour refaire une étape)")
        return folder
    if redo:
        reset(folder, redo)
    for stale in ("qa.json", "post.txt", "error.txt"):
        (folder / stale).unlink(missing_ok=True)
    try:
        meta, sentences = prepare(video_id, folder)
        return finish(video_id, folder, meta, sentences, keep_source)
    except Exception as error:
        if isinstance(error, SkipVideo):
            (folder / "error.txt").write_text(f"{error}\n")
        log(folder, f"Échec : {error}")
        notify(f"Échec sur {video_id} : {str(error)[:80]}")
        raise


def finish(video_id, folder, meta, sentences, keep_source):
    selection = select(sentences, meta, folder)
    ranges = final_ranges(sentences, selection, folder)
    reports = {}
    for name in ("tldr", "ttldr"):
        cuts = render_version(folder, sentences, ranges[name], name)
        reports[name] = check(folder, name, cuts)
        reports[name]["joints"] = audio_joints(folder, name, cuts, sentences)
    write_post(folder, meta, selection, reports)
    log(folder, f"Terminé : TLDR {reports['tldr']['actual_seconds'] / 60:.1f} min, "
                f"TTLDR {reports['ttldr']['actual_seconds']:.0f} s, scores {selection['scores']}")
    all_ok = all(report["duration_ok"] for report in reports.values())
    bad_joints = sum(1 for report in reports.values() for joint in report["joints"] or [] if not joint["ok"])
    if bad_joints:
        log(folder, f"Attention : {bad_joints} jonction(s) où Whisper n'entend pas les mots attendus (voir qa.json)")
    if all_ok and not keep_source:
        (folder / "source.mp4").unlink()
    notify(f"{meta['title']} : TLDR et TTLDR prêts")
    return folder


def audio_joints(folder, name, cuts, sentences):
    """Contrôle Whisper des jonctions, si l'extra 'qa' est installé (uv sync --extra qa)."""
    try:
        import mlx_whisper  # noqa: F401
        from .qa_audio import check_joints
    except ImportError:
        return None
    try:
        return check_joints(folder / f"{name}.mp4", cuts, sentences)
    except Exception as error:
        log(folder, f"Contrôle Whisper impossible : {error}")
        return None


def notify(message):
    script = f"display notification {json.dumps(message)} with title \"TheoLDR\""
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def latest_long_videos(count=5):
    result = subprocess.run(YTDLP + ["--flat-playlist", "--playlist-end", str(count),
                                     "--print", "%(id)s|%(duration)s|%(title)s", CHANNEL_URL],
                            capture_output=True, text=True, check=True)
    videos = []
    for line in result.stdout.strip().splitlines():
        video_id, duration, title = line.split("|", 2)
        if duration not in ("NA", "None") and float(duration) >= 180:
            videos.append((video_id, title))
    return videos


def status():
    for folder in sorted(VIDEOS_DIR.glob("*/")):
        meta_path = folder / "meta.json"
        title = read_json(meta_path)["title"] if meta_path.exists() else "?"
        qa_path = folder / "qa.json"
        if qa_path.exists():
            state = "fait"
        elif (folder / "error.txt").exists():
            state = "échec"
        else:
            state = "en cours"
        print(f"{folder.name}  {state:20}  {title}")


def main():
    parser = argparse.ArgumentParser(prog="theoldr", description="TLDR des vidéos de Theo, par coupes.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="traiter une vidéo (URL ou ID)")
    run_parser.add_argument("video")
    run_parser.add_argument("--redo", choices=sorted(STEP_FILES), help="refaire à partir de cette étape")
    run_parser.add_argument("--keep-source", action="store_true", help="garder source.mp4")
    latest_parser = commands.add_parser("latest", help="traiter la dernière vidéo pas encore faite")
    latest_parser.add_argument("--keep-source", action="store_true")
    commands.add_parser("status", help="lister les vidéos traitées")
    args = parser.parse_args()

    if args.command == "status":
        status()
        return
    lock = open(ROOT / ".theoldr.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Un autre run TheoLDR tourne déjà.")
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    if args.command == "run":
        folder = process(args.video, args.redo, args.keep_source)
    else:
        pending = [(video_id, title) for video_id, title in latest_long_videos()
                   if not (VIDEOS_DIR / video_id / "qa.json").exists()
                   and not (VIDEOS_DIR / video_id / "error.txt").exists()]
        if not pending:
            print("Rien de nouveau : les dernières vidéos sont déjà traitées "
                  "(celles en échec se relancent avec `theoldr run <id>`).")
            return
        video_id, title = pending[0]
        print(f"Traitement de : {title}")
        folder = process(video_id, keep_source=args.keep_source)
    print(f"Résultats : {folder}")
    subprocess.run(["open", str(folder)], check=False)
