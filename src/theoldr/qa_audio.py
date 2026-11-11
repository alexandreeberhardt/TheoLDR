"""Contrôle des jonctions : retranscrit la vidéo raccourcie et vérifie que les mots
de part et d'autre de chaque coupe sont bien entendus (pas de mot mangé ou tronqué)."""
import re

from .qa import joints

MODEL = "mlx-community/whisper-small.en-mlx"
EDGE_WORDS = 3
WINDOW_SECONDS = 2.5


def normalize(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def heard_words(media_path):
    import mlx_whisper

    result = mlx_whisper.transcribe(str(media_path), path_or_hf_repo=MODEL, word_timestamps=True,
                                    condition_on_previous_text=False)
    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            text = normalize(word["word"])
            if text:
                words.append((text, word["start"], word["end"]))
    return words


def found(expected, heard, around):
    nearby = {text for text, start, end in heard if abs(start - around) <= WINDOW_SECONDS}
    expected = [normalize(word) for word in expected if normalize(word)]
    hits = sum(1 for word in expected if word in nearby)
    return hits, len(expected)


def check_joints(media_path, cuts, sentences):
    texts = {sentence["id"]: sentence["text"] for sentence in sentences}
    heard = heard_words(media_path)
    report = []
    for number, time in enumerate(joints(cuts)):
        before = texts[cuts[number]["last"]].split()[-EDGE_WORDS:]
        after_id = cuts[number + 1]["first"]
        after = texts[after_id].split()[:EDGE_WORDS]
        hits_before, total_before = found(before, heard, time - 1.0)
        hits_after, total_after = found(after, heard, time + 1.0)
        ok = hits_before >= total_before - 1 and hits_after >= total_after - 1
        report.append({"joint": number + 1, "time": round(time, 2), "ok": ok,
                       "end_of_previous": " ".join(before), "start_of_next": " ".join(after),
                       "heard": " ".join(text for text, start, end in heard if abs(start - time) <= 2.0)})
    return report
