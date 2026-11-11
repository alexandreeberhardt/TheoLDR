"""Quick checks, without network or Claude, of everything that depends on the system."""
import subprocess

import pytest

from theoldr import qa, render, system
from theoldr.common import read_json, video_id_from, write_json
from theoldr.qa_audio import spoken_words, word_heard

CUTS = [{"first": "s1", "last": "s1", "start": 1.0, "end": 3.0},
        {"first": "s3", "last": "s3", "start": 5.0, "end": 7.5},
        {"first": "s5", "last": "s5", "start": 9.0, "end": 11.0}]


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(path)], check=True)
    return path


def test_render_and_contact_sheet(source, tmp_path):
    out = tmp_path / "tldr.mp4"
    render.render(source, CUTS[:2], out)
    assert abs(render.media_duration(out) - 4.5) < 0.2
    render.render(source, CUTS, out)  # replaces the existing file
    assert abs(render.media_duration(out) - 6.5) < 0.2
    assert qa.contact_sheet(out, CUTS, tmp_path / "sheet.jpg").stat().st_size > 0


def test_lock_is_exclusive(tmp_path):
    first = system.acquire_lock(tmp_path / "lock")
    assert first is not None
    assert system.acquire_lock(tmp_path / "lock") is None
    first.close()
    assert system.acquire_lock(tmp_path / "lock") is not None


def test_json_keeps_unicode(tmp_path):
    data = {"title": "Théo’s “TLDR” 🚀"}
    write_json(tmp_path / "meta.json", data)
    assert read_json(tmp_path / "meta.json") == data


def test_video_id():
    assert video_id_from("https://www.youtube.com/watch?v=GtJKFhztgdM&t=3") == "GtJKFhztgdM"
    assert video_id_from("https://youtu.be/GtJKFhztgdM") == "GtJKFhztgdM"


def test_word_matching():
    assert spoken_words("[applause] so >> here we go") == ["so", "here", "we", "go"]
    assert word_heard("going", ["gonna"])
    assert not word_heard("train", ["rain"])
