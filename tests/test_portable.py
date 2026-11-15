"""Quick checks, without network or Claude, of everything that depends on the system."""
import subprocess

import pytest

from theoldr import cli, fetch, qa, render, select, system, transcript
from theoldr.common import read_json, tool_name, video_id_from, write_json
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


def test_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.missing_tools() == cli.REQUIRED_TOOLS


def test_node_version():
    assert cli.node_major("v22.11.0\n") == 22
    assert cli.node_major("v18.19.1") == 18
    assert cli.node_major(None) is None
    assert cli.node_major("not a version") is None


def test_claude_login():
    assert cli.claude_logged_out('{"loggedIn": false}')
    assert not cli.claude_logged_out('{"loggedIn": true, "authMethod": "claude.ai"}')
    assert not cli.claude_logged_out("error: unknown command 'auth'")  # older CLI: not blocked
    assert not cli.claude_logged_out(None)


def test_setup_problem(monkeypatch):
    outputs = {"node": "v18.19.1", "claude": '{"loggedIn": true}'}
    monkeypatch.setattr(cli, "missing_tools", lambda: [])
    monkeypatch.setattr(cli, "tool_output", lambda command: outputs[command[0]])
    assert "Node 18 is too old" in cli.setup_problem()
    outputs["node"] = "v22.0.0"
    assert cli.setup_problem() is None
    outputs["claude"] = '{"loggedIn": false}'
    assert "not logged in" in cli.setup_problem()


def test_short_error():
    ytdlp = RuntimeError("yt_dlp failed:\nWARNING: No supported JavaScript runtime\n"
                         "ERROR: [youtube] abc: Sign in to confirm you're not a bot\n")
    assert cli.short_error(ytdlp) == "[youtube] abc: Sign in to confirm you're not a bot"
    assert cli.short_error(ValueError("No YouTube ID found in: notanid")) == "No YouTube ID found in: notanid"
    failed = subprocess.CalledProcessError(1, ["yt-dlp"], stderr="ERROR: Unable to download webpage\n")
    assert cli.short_error(failed) == "Unable to download webpage"
    assert tool_name(["/usr/bin/python3", "-m", "yt_dlp", "--encoding"]) == "yt_dlp"
    assert tool_name(["ffmpeg", "-v", "error"]) == "ffmpeg"


def test_whisper_captions_read_like_youtube_ones(tmp_path):
    words = [(" We're", 0.5, 0.7), (" not", 0.7, 0.9), (" engineers.", 0.9, 1.4), ("  ", 1.4, 1.5),
             (" So", 2.0, 2.1), (" what", 2.1, 2.3), (" are", 2.3, 2.4), (" we?", 2.4, 2.8)]
    write_json(tmp_path / "subs.json3", fetch.whisper_subs(words))
    sentences = transcript.build_transcript(tmp_path / "subs.json3", tmp_path / "transcript.json", 10.0)
    assert [sentence["text"] for sentence in sentences] == ["We're not engineers.", "So what are we?"]
    assert sentences[0]["start"] == 0.5 and sentences[0]["next_start"] == 2.0
    assert sentences[1]["last_word_start"] == 2.4 and sentences[1]["next_start"] == 10.0


def test_captions_note():
    assert select.captions_note({"title": "x"}) == ""
    assert ">>" in select.captions_note({"captions": "whisper"})
