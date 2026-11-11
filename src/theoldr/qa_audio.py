"""Contrôle des jonctions : retranscrit la vidéo raccourcie et vérifie que les mots
de part et d'autre de chaque coupe sont bien entendus (pas de mot mangé ou tronqué)."""
import re
from difflib import SequenceMatcher

from .qa import joints

MODEL = "mlx-community/whisper-small.en-mlx"
EDGE_WORDS = 3
WINDOW_SECONDS = 2.5
MIN_MATCH = 0.7


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
    """Part des caractères attendus retrouvés près de la jonction (tolère « 2.08 » / « 2 08 », « gonna »...)."""
    target = "".join(normalize(word) for word in expected)
    nearby = "".join(text for text, start, end in heard if abs(start - around) <= WINDOW_SECONDS)
    if not target:
        return 1.0
    matcher = SequenceMatcher(None, target, nearby, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(target)


def check_joints(media_path, cuts, sentences):
    texts = {sentence["id"]: sentence["text"] for sentence in sentences}
    heard = heard_words(media_path)
    report = []
    for number, time in enumerate(joints(cuts)):
        before = texts[cuts[number]["last"]].split()[-EDGE_WORDS:]
        after_id = cuts[number + 1]["first"]
        after = texts[after_id].split()[:EDGE_WORDS]
        ratio_before = found(before, heard, time - 1.0)
        ratio_after = found(after, heard, time + 1.0)
        ok = min(ratio_before, ratio_after) >= MIN_MATCH
        report.append({"joint": number + 1, "time": round(time, 2), "ok": ok,
                       "match": round(min(ratio_before, ratio_after), 2),
                       "end_of_previous": " ".join(before), "start_of_next": " ".join(after),
                       "heard": " ".join(text for text, start, end in heard if abs(start - time) <= 2.0)})
    return report
