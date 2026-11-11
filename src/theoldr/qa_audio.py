"""Joint check: transcribes the shortened video again and checks that the words
on both sides of each cut are heard (no swallowed or clipped word)."""
import re
from difflib import SequenceMatcher

from .qa import joints

MODEL = "mlx-community/whisper-small.en-mlx"
EDGE_WORDS = 3
WINDOW_SECONDS = 1.5
MIN_MATCH = 0.66


SPOKEN_FORMS = {"going": "gonna", "want": "wanna", "got": "gotta"}
ANNOTATION = re.compile(r"^\[.*\]$|^>>$")


def normalize(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def spoken_words(text):
    """Words actually spoken: without annotations ([applause], >>)."""
    return [word for word in text.replace("[", " [").replace("]", "] ").split() if not ANNOTATION.match(word)]


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


def word_heard(word, heard_texts):
    """Is the expected word heard, alone or joined with the next one ("2.08" heard as "2 08")?

    Exact match for short words: "rain" for "train" is precisely a swallowed word."""
    candidates = heard_texts + [a + b for a, b in zip(heard_texts, heard_texts[1:])]
    if word in candidates or SPOKEN_FORMS.get(word) in candidates:
        return True
    if len(word) >= 4 and any(word in candidate for candidate in heard_texts):
        return True
    if len(word) < 6:
        return False
    return any(SequenceMatcher(None, word, candidate).ratio() >= 0.8 for candidate in candidates)


def found(expected, heard, around):
    """Share of the expected words heard within WINDOW_SECONDS of the given time."""
    expected = [normalize(word) for word in expected if normalize(word)]
    if not expected:
        return 1.0
    nearby = [text for text, start, end in heard if abs(start - around) <= WINDOW_SECONDS]
    return sum(1 for word in expected if word_heard(word, nearby)) / len(expected)


def check_joints(media_path, cuts, sentences):
    texts = {sentence["id"]: sentence["text"] for sentence in sentences}
    heard = heard_words(media_path)
    report = []
    for number, time in enumerate(joints(cuts)):
        before = spoken_words(texts[cuts[number]["last"]])[-EDGE_WORDS:]
        after = spoken_words(texts[cuts[number + 1]["first"]])[:EDGE_WORDS]
        ratio_before = found(before, heard, time - 1.0)
        ratio_after = found(after, heard, time + 1.0)
        ok = min(ratio_before, ratio_after) >= MIN_MATCH
        report.append({"joint": number + 1, "time": round(time, 2), "ok": ok,
                       "match": round(min(ratio_before, ratio_after), 2),
                       "end_of_previous": " ".join(before), "start_of_next": " ".join(after),
                       "heard": " ".join(text for text, start, end in heard if abs(start - time) <= 2.0)})
    return report
