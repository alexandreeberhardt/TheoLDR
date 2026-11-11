import re

from .common import read_json, write_json

SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")
MAX_SENTENCE_WORDS = 70
NOISE = re.compile(r"^\[.*\]$")


def load_words(subs_path):
    events = read_json(subs_path)["events"]
    words = []
    for event in events:
        segments = event.get("segs")
        if not segments:
            continue
        event_start = event["tStartMs"]
        for segment in segments:
            text = segment.get("utf8", "").strip()
            if not text or NOISE.match(text):
                continue
            start = (event_start + segment.get("tOffsetMs", 0)) / 1000
            words.append({"text": text, "start": start})
    words.sort(key=lambda word: word["start"])
    return words


def continues_sentence(word):
    """Un mot qui commence par une minuscule prolonge la phrase : le point était une erreur des sous-titres."""
    return word["text"][0].islower()


def group_sentences(words):
    sentences = []
    current = []
    for position, word in enumerate(words):
        current.append(word)
        next_word = words[position + 1] if position + 1 < len(words) else None
        ends_here = SENTENCE_END.search(word["text"]) and not (next_word and continues_sentence(next_word))
        if ends_here:
            sentences.append(current)
            current = []
        elif len(current) >= MAX_SENTENCE_WORDS:
            head, current = split_at_longest_pause(current, next_word)
            sentences.append(head)
    if current:
        sentences.append(current)
    return sentences


def split_at_longest_pause(words, next_word):
    """Phrase trop longue (sous-titres sans ponctuation) : on coupe là où l'écart entre deux mots
    est le plus grand, en gardant au moins 15 mots de chaque côté."""
    gaps = []
    for index in range(15, len(words) - 15):
        gaps.append((words[index]["start"] - words[index - 1]["start"], index))
    if next_word:
        gaps.append((next_word["start"] - words[-1]["start"], len(words)))
    _, split = max(gaps)
    return words[:split], words[split:]


def build_transcript(subs_path, out_path, duration):
    words = load_words(subs_path)
    groups = group_sentences(words)
    sentences = []
    for index, group in enumerate(groups):
        if index + 1 < len(groups):
            next_start = groups[index + 1][0]["start"]
        else:
            next_start = duration
        sentences.append({
            "id": f"S{index + 1:04d}",
            "start": round(group[0]["start"], 3),
            "last_word_start": round(group[-1]["start"], 3),
            "next_start": round(next_start, 3),
            "text": " ".join(word["text"] for word in group),
        })
    write_json(out_path, sentences)
    return sentences
