import argparse
import json
import re
import shutil
import subprocess
import sys

from .common import CHANNEL_URL, SkipVideo, ROOT, VIDEOS_DIR, log, read_json, video_dir, video_id_from, write_json
from .fetch import YTDLP, fetch
from .qa import check, write_post
from .render import media_duration, render_version
from .select import final_ranges, select
from .silences import detect_silences, mark_boundaries
from .sponsor import fetch_sponsors, mark_sponsors
from .system import acquire_lock, keep_awake, notify, open_folder
from .transcript import build_transcript

STEP_FILES = {
    "select": ["outline.json", "selection.json", "attempts"],
    "selection": ["selection.json", "attempts"],
    "render": ["tldr.mp4", "ttldr.mp4", "cuts_tldr.json", "cuts_ttldr.json"],
}
REQUIRED_TOOLS = ["ffmpeg", "ffprobe", "node", "claude"]
MIN_NODE_MAJOR = 22  # yt-dlp ignores an older Node and then fails to read YouTube
HANDLED_ERRORS = (RuntimeError, ValueError, subprocess.CalledProcessError)


def missing_tools():
    """Programs a run calls that are not on the PATH."""
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def tool_output(command):
    """What a short command prints, or None if it cannot run."""
    try:
        result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout


def node_major(version_output):
    """22 for 'v22.11.0'; None when the version cannot be read."""
    match = re.match(r"v(\d+)\.", version_output or "")
    return int(match.group(1)) if match else None


def claude_logged_out(status_output):
    """True only when `claude auth status` clearly says so: an older CLI without that command is not blocked."""
    try:
        return json.loads(status_output or "").get("loggedIn") is False
    except (json.JSONDecodeError, AttributeError):
        return False


def setup_problem():
    """Why a run cannot start, or None. Checked before anything is downloaded."""
    missing = missing_tools()
    if missing:
        return f"Not found on the PATH: {', '.join(missing)}. See the Quick start in README.md."
    major = node_major(tool_output(["node", "--version"]))
    if major is not None and major < MIN_NODE_MAJOR:
        return f"Node {major} is too old: yt-dlp needs Node {MIN_NODE_MAJOR} or newer."
    if claude_logged_out(tool_output(["claude", "auth", "status"])):
        return "Claude Code is not logged in: run `claude` once and sign in, then run this again."
    return None


def short_error(error):
    """The line that says what went wrong, without the rest of the tool's output."""
    text = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR:")]
    if errors:
        return errors[-1].removeprefix("ERROR:").strip()
    return lines[-1] if lines else type(error).__name__


def prepare(video_id, folder, whisper_captions=False):
    meta = fetch(video_id, folder, whisper_captions)
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


def process(url_or_id, redo=None, keep_source=False, whisper_captions=False):
    video_id = video_id_from(url_or_id)
    folder = video_dir(video_id)
    if (folder / "qa.json").exists() and not redo:
        print(f"Already processed: {folder} (use --redo to redo a step)")
        return folder
    if redo:
        reset(folder, redo)
    for stale in ("qa.json", "post.txt", "error.txt"):
        (folder / stale).unlink(missing_ok=True)
    try:
        meta, sentences = prepare(video_id, folder, whisper_captions)
        return finish(video_id, folder, meta, sentences, keep_source)
    except Exception as error:
        if isinstance(error, SkipVideo):
            (folder / "error.txt").write_text(f"{error}\n", encoding="utf-8")
        log(folder, f"Failed: {error}", show=not isinstance(error, HANDLED_ERRORS))  # main() prints the short version
        notify(f"Failed on {video_id}: {str(error)[:80]}")
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
    log(folder, f"Done: TLDR {reports['tldr']['actual_seconds'] / 60:.1f} min, "
                f"TTLDR {reports['ttldr']['actual_seconds']:.0f} s, scores {selection['scores']}")
    all_ok = all(report["duration_ok"] for report in reports.values())
    bad_joints = sum(1 for report in reports.values() for joint in report["joints"] or [] if not joint["ok"])
    if bad_joints:
        log(folder, f"Warning: {bad_joints} joint(s) where Whisper does not hear the expected words (see qa.json)")
    if all_ok and not keep_source:
        (folder / "source.mp4").unlink()
    notify(f"{meta['title']}: TLDR and TTLDR ready")
    return folder


def audio_joints(folder, name, cuts, sentences):
    """Whisper check of the joints, if the 'qa' extra is installed (uv sync --extra qa)."""
    from .qa_audio import check_joints, whisper_available
    if not whisper_available():
        return None
    try:
        return check_joints(folder / f"{name}.mp4", cuts, sentences)
    except Exception as error:
        log(folder, f"Whisper check failed: {error}")
        return None


def latest_long_videos(count=5):
    result = subprocess.run(YTDLP + ["--flat-playlist", "--playlist-end", str(count),
                                     "--print", "%(id)s|%(duration)s|%(title)s", CHANNEL_URL],
                            capture_output=True, encoding="utf-8", errors="replace", check=True)
    videos = []
    for line in result.stdout.strip().splitlines():
        video_id, duration, title = line.split("|", 2)
        if duration not in ("NA", "None") and float(duration) >= 180:
            videos.append((video_id, title))
    return videos


def status():
    folders = sorted(VIDEOS_DIR.glob("*/"))
    if not folders:
        print("No video processed yet.")
    for folder in folders:
        meta_path = folder / "meta.json"
        title = read_json(meta_path)["title"] if meta_path.exists() else "?"
        qa_path = folder / "qa.json"
        if qa_path.exists():
            state = "done"
        elif (folder / "error.txt").exists():
            state = "failed"
        else:
            state = "in progress"
        print(f"{folder.name}  {state:20}  {title}")


def main():
    parser = argparse.ArgumentParser(prog="theoldr", description="TLDRs of Theo's videos, by cutting only.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="process one video (URL or ID)")
    run_parser.add_argument("video")
    run_parser.add_argument("--redo", choices=sorted(STEP_FILES), help="redo from this step")
    run_parser.add_argument("--keep-source", action="store_true", help="keep source.mp4")
    latest_parser = commands.add_parser("latest", help="process the latest video not done yet")
    latest_parser.add_argument("--keep-source", action="store_true")
    for command_parser in (run_parser, latest_parser):
        command_parser.add_argument("--whisper-captions", action="store_true",
                                    help="transcribe with Whisper instead of using YouTube's captions")
    commands.add_parser("status", help="list processed videos")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # Windows uses cp1252 when output is redirected

    if args.command == "status":
        status()
        return
    problem = setup_problem()
    if problem:
        sys.exit(problem)
    lock = acquire_lock(ROOT / ".theoldr.lock")
    if lock is None:
        sys.exit("Another TheoLDR run is already in progress.")
    keep_awake()
    try:
        folder = run_command(args)
    except HANDLED_ERRORS as error:
        sys.exit(f"Failed: {short_error(error)}")
    if folder is None:
        return
    print(f"Results: {folder}")
    open_folder(folder)


def run_command(args):
    """The folder of the processed video, or None when there was nothing to do."""
    if args.command == "run":
        return process(args.video, args.redo, args.keep_source, args.whisper_captions)
    pending = [(video_id, title) for video_id, title in latest_long_videos()
               if not (VIDEOS_DIR / video_id / "qa.json").exists()
               and not (VIDEOS_DIR / video_id / "error.txt").exists()]
    if not pending:
        print("Nothing new: the latest videos are already processed "
              "(failed ones can be retried with `theoldr run <id>`).")
        return None
    video_id, title = pending[0]
    print(f"Processing: {title}")
    return process(video_id, keep_source=args.keep_source, whisper_captions=args.whisper_captions)
