import re
import subprocess

from .common import read_json, write_json

NOISE_DB = -32
MIN_SILENCE = 0.08
MIN_TAIL_AFTER_WORD = 0.12
MIN_CUT_SILENCE = 0.12


def detect_silences(source, out_path):
    if out_path.exists():
        return read_json(out_path)
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-vn",
               "-af", f"silencedetect=n={NOISE_DB}dB:d={MIN_SILENCE}", "-f", "null", "-"]
    output = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", check=True).stderr
    starts = [float(value) for value in re.findall(r"silence_start: ([\d.]+)", output)]
    ends = [float(value) for value in re.findall(r"silence_end: ([\d.]+)", output)]
    silences = [[round(start, 3), round(end, 3)] for start, end in zip(starts, ends)]
    write_json(out_path, silences)
    return silences


def find_cut(silences, earliest, latest):
    """Middle of the longest silence (at least MIN_CUT_SILENCE) overlapping [earliest, latest], or None.

    A shorter silence may just be a consonant closure in the middle of the last word."""
    best = None
    best_length = MIN_CUT_SILENCE
    for start, end in silences:
        overlap_start = max(start, earliest)
        overlap_end = min(end, latest)
        length = overlap_end - overlap_start
        if length > best_length:
            best_length = length
            best = (overlap_start + overlap_end) / 2
    return best


def mark_boundaries(sentences, silences, duration):
    """Adds 'cut_after' to each sentence: the clean cut time after the sentence, or None."""
    for index, sentence in enumerate(sentences):
        if index + 1 == len(sentences):
            sentence["cut_after"] = duration
            continue
        earliest = sentence["last_word_start"] + MIN_TAIL_AFTER_WORD
        latest = sentence["next_start"] + 0.05
        sentence["cut_after"] = find_cut(silences, earliest, latest)
    return sentences
