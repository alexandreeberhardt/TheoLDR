import subprocess
import tempfile
from pathlib import Path

from .common import format_time, write_json
from .render import media_duration


def joints(cuts):
    """Times of the joints in the shortened video."""
    times = []
    elapsed = 0.0
    for cut in cuts[:-1]:
        elapsed += cut["end"] - cut["start"]
        times.append(elapsed)
    return times


def contact_sheet(video_path, cuts, out_path, columns=6):
    """Contact sheet: for each joint, the frame just before and just after the cut."""
    times = joints(cuts)
    if not times:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for time in times:
            for offset in (-0.15, 0.15):
                frame = Path(tmp) / f"{len(frames):04d}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(time + offset, 0):.2f}",
                                "-i", str(video_path), "-frames:v", "1", "-vf", "scale=320:-2",
                                str(frame)], check=True)
                frames.append(frame)
        rows = (len(frames) + columns - 1) // columns
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-start_number", "0",
                        "-i", str(Path(tmp) / "%04d.jpg"), "-vf", f"tile={columns}x{rows}:padding=4:color=white",
                        "-frames:v", "1", str(out_path)], check=True)
    return out_path


def check(folder, name, cuts):
    path = folder / f"{name}.mp4"
    planned = sum(cut["end"] - cut["start"] for cut in cuts)
    actual = media_duration(path)
    lengths = [cut["end"] - cut["start"] for cut in cuts]
    report = {
        "planned_seconds": round(planned, 1),
        "actual_seconds": round(actual, 1),
        "segments": len(cuts),
        "shortest_segment": round(min(lengths), 1),
        "duration_ok": abs(actual - planned) < 1.0,
        "sheet": str(contact_sheet(path, cuts, folder / f"sheet_{name}.jpg")),
    }
    return report


def write_post(folder, meta, selection, reports):
    lines = [
        f"TheoLDR: {meta['title']}",
        "",
        f"TLDR ({format_time(reports['tldr']['actual_seconds'])}) and TTLDR "
        f"({format_time(reports['ttldr']['actual_seconds'])}) of the {format_time(meta['duration'])} video, "
        "made by cutting only.",
        f"Original: {meta['url']}",
    ]
    (folder / "post.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(folder / "qa.json", {"scores": selection["scores"], "passed": selection["passed"],
                                    "rounds": selection["rounds"], **reports})
