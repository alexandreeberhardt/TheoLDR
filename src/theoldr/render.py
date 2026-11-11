import subprocess

from .common import read_json, write_json

FADE = 0.02
VIDEO_BITRATE = "3500k"


def build_cuts(sentences, ranges):
    """Plages d'IDs -> intervalles [début, fin] en secondes, calés sur les silences."""
    index = {sentence["id"]: position for position, sentence in enumerate(sentences)}
    cuts = []
    for item in ranges:
        first = index[item["first"]]
        last = index[item["last"]]
        start = 0.0 if first == 0 else sentences[first - 1]["cut_after"]
        end = sentences[last]["cut_after"]
        cuts.append({"first": item["first"], "last": item["last"], "start": round(start, 3), "end": round(end, 3)})
    return cuts


def filter_graph(cuts):
    parts = []
    labels = []
    for number, cut in enumerate(cuts):
        length = cut["end"] - cut["start"]
        parts.append(f"[0:v]trim=start={cut['start']}:end={cut['end']},setpts=PTS-STARTPTS[v{number}]")
        parts.append(f"[0:a]atrim=start={cut['start']}:end={cut['end']},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={FADE},afade=t=out:st={max(length - FADE, 0):.3f}:d={FADE}[a{number}]")
        labels.append(f"[v{number}][a{number}]")
    parts.append(f"{''.join(labels)}concat=n={len(cuts)}:v=1:a=1[v][a]")
    return ";".join(parts)


def render(source, cuts, out_path):
    temporary = out_path.with_suffix(".part.mp4")
    first_start = cuts[0]["start"]
    last_end = cuts[-1]["end"]
    shifted = [{**cut, "start": round(cut["start"] - first_start, 3), "end": round(cut["end"] - first_start, 3)}
               for cut in cuts]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{first_start:.3f}", "-to", f"{last_end:.3f}", "-i", str(source),
               "-filter_complex", filter_graph(shifted), "-map", "[v]", "-map", "[a]",
               "-c:v", "h264_videotoolbox", "-b:v", VIDEO_BITRATE, "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", str(temporary)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    temporary.rename(out_path)


def media_duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                             str(path)], capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def render_version(folder, sentences, ranges, name):
    out_path = folder / f"{name}.mp4"
    cuts_path = folder / f"cuts_{name}.json"
    cuts = build_cuts(sentences, ranges)
    if out_path.exists() and cuts_path.exists() and read_json(cuts_path) == cuts:
        return cuts
    render(folder / "source.mp4", cuts, out_path)
    write_json(cuts_path, cuts)
    return cuts
