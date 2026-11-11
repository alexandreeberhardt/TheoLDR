import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEOS_DIR = ROOT / "videos"
PROMPTS_DIR = ROOT / "prompts"
CHANNEL_URL = "https://www.youtube.com/@theo/videos"
MIN_FREE_BYTES = 1_500_000_000


def video_id_from(url_or_id):
    patterns = [r"youtu\.be/([\w-]{11})", r"[?&]v=([\w-]{11})", r"shorts/([\w-]{11})", r"^([\w-]{11})$"]
    for pattern in patterns:
        match = re.search(pattern, url_or_id.strip())
        if match:
            return match.group(1)
    raise ValueError(f"Identifiant YouTube introuvable dans : {url_or_id}")


def video_dir(video_id):
    folder = VIDEOS_DIR / video_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def log(folder, message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with open(Path(folder) / "log.txt", "a") as handle:
        handle.write(line + "\n")


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def check_free_space():
    free = shutil.disk_usage(ROOT).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"Espace disque insuffisant : {free / 1e9:.1f} Go libres")


def format_time(seconds):
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"
