import json
from concurrent.futures import ThreadPoolExecutor

from .agent import ask
from .common import PROMPTS_DIR, format_time, log, read_json, write_json

MAX_ROUNDS = 3
MERGE_GAP_SECONDS = 1.5
TLDR_BOUNDS = (300, 900)
TTLDR_BOUNDS = (60, 120)
TARGET_TOLERANCE = 0.2

RANGE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"first": {"type": "string"}, "last": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["first", "last", "reason"],
    },
}

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "thesis": {"type": "string"},
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "summary": {"type": "string"},
            "first": {"type": "string"}, "last": {"type": "string"},
            "kind": {"type": "string"}, "importance": {"type": "integer"}},
            "required": ["title", "summary", "first", "last", "kind", "importance"]}},
        "extra_sponsor_ranges": {"type": "array", "items": {"type": "object", "properties": {
            "first": {"type": "string"}, "last": {"type": "string"}}, "required": ["first", "last"]}},
        "key_moments": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"}, "sentence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["description", "sentence_ids"]}},
        "density": {"type": "string", "enum": ["low", "medium", "high"]},
        "tldr_target_minutes": {"type": "number"},
    },
    "required": ["topic", "thesis", "sections", "extra_sponsor_ranges", "key_moments", "density",
                 "tldr_target_minutes"],
}

SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": RANGE_SCHEMA,
        "ttldr": RANGE_SCHEMA,
        "tldr_estimated_seconds": {"type": "number"},
        "ttldr_estimated_seconds": {"type": "number"},
    },
    "required": ["tldr", "ttldr", "tldr_estimated_seconds", "ttldr_estimated_seconds"],
}

ISSUE_PROPS = {"quote": {"type": "string"}, "segment": {"type": "integer"}, "type": {"type": "string"},
               "fix": {"type": "string"}, "blocking": {"type": "boolean"}}
BLIND_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "issues": {"type": "array", "items": {
        "type": "object", "properties": ISSUE_PROPS, "required": ["quote", "type", "fix", "blocking"]}}},
    "required": ["score", "issues"],
}
FIDELITY_SCHEMA = {
    "type": "object",
    "properties": {
        "fidelity_score": {"type": "number"},
        "coverage_score": {"type": "number"},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "version": {"type": "string", "enum": ["tldr", "ttldr"]},
            "sentence_ids": {"type": "array", "items": {"type": "string"}},
            "type": {"type": "string"}, "fix": {"type": "string"}, "blocking": {"type": "boolean"}},
            "required": ["version", "sentence_ids", "type", "fix", "blocking"]}},
    },
    "required": ["fidelity_score", "coverage_score", "issues"],
}


def prompt(name):
    return (PROMPTS_DIR / f"{name}.md").read_text()


class Video:
    """Phrases d'une vidéo et calculs de temps de coupe."""

    def __init__(self, sentences):
        self.sentences = sentences
        self.index = {sentence["id"]: position for position, sentence in enumerate(sentences)}

    def cut_before(self, position):
        if position == 0:
            return 0.0
        return self.sentences[position - 1]["cut_after"]

    def cut_after(self, position):
        return self.sentences[position]["cut_after"]

    def can_start(self, position):
        return self.cut_before(position) is not None

    def can_end(self, position):
        return self.cut_after(position) is not None

    def duration(self, position):
        start = self.cut_before(position)
        if start is None:
            start = self.sentences[position]["start"]
        end = self.cut_after(position)
        if end is None:
            end = self.sentences[position]["next_start"]
        return end - start

    def transcript_text(self, with_cut_marks=True):
        lines = []
        for position, sentence in enumerate(self.sentences):
            flag = "#SPONSOR " if sentence.get("sponsor") else ""
            mark = " ✂" if with_cut_marks and self.can_end(position) else ""
            lines.append(f"{sentence['id']}  {format_time(sentence['start'])}  "
                         f"{self.duration(position):.1f}s  {flag}{sentence['text']}{mark}")
        return "\n".join(lines)

    def range_text(self, first, last):
        return " ".join(sentence["text"] for sentence in self.sentences[first:last + 1])


def normalize(video, raw_ranges):
    """Valide des plages d'IDs, les cale sur des coupes propres, retire les sponsors, fusionne.

    Renvoie (liste de paires de positions, liste de remarques)."""
    notes = []
    pairs = []
    for item in raw_ranges:
        first = video.index.get(item["first"])
        last = video.index.get(item["last"])
        if first is None or last is None:
            notes.append(f"Unknown sentence ID in range {item['first']}-{item['last']}: ignored.")
            continue
        if first > last:
            first, last = last, first
        pairs.append([first, last])
    pairs.sort()

    clean = []
    for first, last in pairs:
        piece_start = None
        for position in range(first, last + 2):
            is_sponsor = position <= last and video.sentences[position].get("sponsor")
            if position <= last and not is_sponsor:
                if piece_start is None:
                    piece_start = position
                continue
            if is_sponsor:
                notes.append(f"{video.sentences[position]['id']} is a sponsor sentence: removed.")
            if piece_start is not None:
                clean.append([piece_start, position - 1])
                piece_start = None

    snapped = []
    for first, last in clean:
        original = (first, last)
        while not video.can_start(first):
            first -= 1
        while not video.can_end(last):
            last += 1
        if (first, last) != original:
            notes.append(f"Range {video.sentences[original[0]]['id']}-{video.sentences[original[1]]['id']} "
                         f"extended to {video.sentences[first]['id']}-{video.sentences[last]['id']} "
                         f"to land on clean cuts.")
        snapped.append([first, last])

    snapped.sort()
    merged = []
    for first, last in snapped:
        if merged:
            previous = merged[-1]
            gap = video.cut_before(first) - video.cut_after(previous[1])
            if first <= previous[1] + 1 or gap < MERGE_GAP_SECONDS:
                previous[1] = max(previous[1], last)
                continue
        merged.append([first, last])
    return merged, notes


def total_seconds(video, pairs):
    return sum(video.cut_after(last) - video.cut_before(first) for first, last in pairs)


def kept_positions(pairs):
    return {position for first, last in pairs for position in range(first, last + 1)}


def check_lengths(video, tldr, ttldr, target_seconds):
    problems = []
    tldr_seconds = total_seconds(video, tldr)
    ttldr_seconds = total_seconds(video, ttldr)
    low, high = TLDR_BOUNDS
    if not low <= tldr_seconds <= high:
        problems.append(f"TLDR is {tldr_seconds:.0f}s, outside the hard limits {low}-{high}s.")
    elif abs(tldr_seconds - target_seconds) > TARGET_TOLERANCE * target_seconds:
        problems.append(f"TLDR is {tldr_seconds:.0f}s but the target is {target_seconds:.0f}s.")
    low, high = TTLDR_BOUNDS
    if not low <= ttldr_seconds <= high:
        problems.append(f"TTLDR is {ttldr_seconds:.0f}s, outside the limits {low}-{high}s.")
    return problems


def kept_text(video, pairs):
    parts = []
    for number, (first, last) in enumerate(pairs, start=1):
        parts.append(f"[{number}] {video.range_text(first, last)}")
    return "\n[CUT]\n".join(parts)


def ranges_as_ids(video, pairs):
    return [{"first": video.sentences[first]["id"], "last": video.sentences[last]["id"],
             "seconds": round(video.cut_after(last) - video.cut_before(first), 1)} for first, last in pairs]


def make_outline(video, meta, folder):
    path = folder / "outline.json"
    if path.exists():
        return read_json(path)
    text = (f"Title: {meta['title']}\nDuration: {format_time(meta['duration'])}\n\n"
            f"Transcript:\n{video.transcript_text(with_cut_marks=False)}")
    outline = ask(prompt("outline"), text, OUTLINE_SCHEMA)
    write_json(path, outline)
    return outline


def apply_extra_sponsors(video, outline):
    for item in outline["extra_sponsor_ranges"]:
        first = video.index.get(item["first"])
        last = video.index.get(item["last"])
        if first is None or last is None:
            continue
        for position in range(min(first, last), max(first, last) + 1):
            video.sentences[position]["sponsor"] = True


def selection_request(video, meta, outline, target_seconds, previous=None, feedback=None):
    text = (f"Title: {meta['title']}\nOriginal duration: {format_time(meta['duration'])}\n"
            f"TLDR target: {target_seconds / 60:.1f} min ({target_seconds:.0f}s). "
            f"TTLDR: 60-120s.\n\nOutline:\n{json.dumps(outline, indent=1)}\n\n"
            f"Transcript:\n{video.transcript_text()}")
    if previous:
        text += ("\n\nYOUR PREVIOUS SELECTION (after automatic snapping to clean cuts, with real "
                 f"durations):\n{json.dumps(previous, indent=1)}\n\nFEEDBACK TO ADDRESS:\n{feedback}\n\n"
                 "Produce a corrected, complete selection. Fix ONLY the problems listed, by changing only "
                 "the ranges involved; keep every other range exactly as it was.")
    return ask(prompt("select"), text, SELECTION_SCHEMA)


def review(video, tldr, ttldr, target_seconds):
    def blind(pairs):
        return ask(prompt("verify_blind"), kept_text(video, pairs), BLIND_SCHEMA)

    def fidelity():
        text = (f"TLDR length budget: {target_seconds:.0f}s. TTLDR: 60-120s.\n\n"
                f"ORIGINAL TRANSCRIPT:\n{video.transcript_text(with_cut_marks=False)}\n\n"
                f"TLDR RANGES:\n{json.dumps(ranges_as_ids(video, tldr))}\n\n"
                f"TLDR TEXT:\n{kept_text(video, tldr)}\n\n"
                f"TTLDR RANGES:\n{json.dumps(ranges_as_ids(video, ttldr))}\n\n"
                f"TTLDR TEXT:\n{kept_text(video, ttldr)}")
        return ask(prompt("verify_fidelity"), text, FIDELITY_SCHEMA)

    with ThreadPoolExecutor(max_workers=3) as pool:
        tldr_future = pool.submit(blind, tldr)
        ttldr_future = pool.submit(blind, ttldr)
        fidelity_future = pool.submit(fidelity)
        return {"tldr_blind": tldr_future.result(), "ttldr_blind": ttldr_future.result(),
                "fidelity": fidelity_future.result()}


def evaluate(reviews, length_problems):
    """Réussi = aucun problème bloquant, fidélité >= 8, durées respectées.

    Les notes de fluidité ne servent qu'à départager les tours : calibrées sur des extraits
    continus non coupés de l'original, elles plafonnent autour de 4 à 6."""
    blocking = [issue for key in ("tldr_blind", "ttldr_blind", "fidelity")
                for issue in reviews[key]["issues"] if issue.get("blocking")]
    scores = {
        "tldr_flow": reviews["tldr_blind"]["score"],
        "ttldr_flow": reviews["ttldr_blind"]["score"],
        "fidelity": reviews["fidelity"]["fidelity_score"],
        "coverage": reviews["fidelity"]["coverage_score"],
    }
    passed = scores["fidelity"] >= 8 and not blocking and not length_problems
    total = sum(scores.values()) - 3 * len(blocking) - 3 * len(length_problems)
    return scores, blocking, passed, total


def feedback_text(notes, length_problems, reviews):
    """Ne renvoie à l'agent que ce qui doit être corrigé : durées et problèmes bloquants."""
    lines = []
    if length_problems:
        lines.append("LENGTH: " + " ".join(length_problems))
    if notes:
        lines.append("AUTOMATIC ADJUSTMENTS: " + " ".join(notes))
    for version in ("tldr", "ttldr"):
        for issue in reviews[f"{version}_blind"]["issues"]:
            if issue["blocking"]:
                lines.append(f"- {version.upper()} segment {issue.get('segment')}: \"{issue['quote']}\" -> "
                             f"{issue['type']} (first-time viewer): {issue['fix']}")
    for issue in reviews["fidelity"]["issues"]:
        if issue["blocking"]:
            lines.append(f"- {issue['version'].upper()} {', '.join(issue['sentence_ids'])}: {issue['type']} "
                         f"(reviewer who knows the full video): {issue['fix']}")
    return "\n".join(lines)


def select(sentences, meta, folder):
    path = folder / "selection.json"
    if path.exists():
        return read_json(path)
    video = Video(sentences)
    outline = make_outline(video, meta, folder)
    apply_extra_sponsors(video, outline)
    target_minutes = min(max(outline["tldr_target_minutes"], 5), 15, 0.4 * meta["duration"] / 60)
    target_seconds = max(target_minutes, 5) * 60
    log(folder, f"Plan fait, densité {outline['density']}, cible TLDR {target_seconds / 60:.1f} min")

    attempts_dir = folder / "attempts"
    attempts_dir.mkdir(exist_ok=True)
    best = None
    previous = None
    feedback = None
    for round_number in range(1, MAX_ROUNDS + 1):
        raw = selection_request(video, meta, outline, target_seconds, previous, feedback)
        tldr, notes = normalize(video, raw["tldr"])
        ttldr, ttldr_notes = normalize(video, raw["ttldr"])
        notes += ttldr_notes
        missing = kept_positions(ttldr) - kept_positions(tldr)
        if missing:
            extra = [{"first": video.sentences[p]["id"], "last": video.sentences[p]["id"]} for p in missing]
            tldr, _ = normalize(video, [{"first": video.sentences[a]["id"], "last": video.sentences[b]["id"]}
                                        for a, b in tldr] + extra)
            notes.append(f"{len(missing)} TTLDR sentences were not in the TLDR: added to the TLDR.")
        length_problems = check_lengths(video, tldr, ttldr, target_seconds)
        reviews = review(video, tldr, ttldr, target_seconds)
        scores, blocking, passed, total = evaluate(reviews, length_problems)
        attempt = {
            "round": round_number, "raw": raw, "notes": notes, "length_problems": length_problems,
            "tldr": ranges_as_ids(video, tldr), "ttldr": ranges_as_ids(video, ttldr),
            "tldr_seconds": round(total_seconds(video, tldr), 1),
            "ttldr_seconds": round(total_seconds(video, ttldr), 1),
            "reviews": reviews, "scores": scores, "blocking": len(blocking), "passed": passed, "total": total,
        }
        write_json(attempts_dir / f"round{round_number}.json", attempt)
        log(folder, f"Tour {round_number} : TLDR {attempt['tldr_seconds'] / 60:.1f} min, "
                    f"TTLDR {attempt['ttldr_seconds']:.0f} s, scores {scores}, bloquants {len(blocking)}")
        if best is None or total > best["total"]:
            best = attempt
        if passed:
            break
        previous = {"tldr": attempt["tldr"], "ttldr": attempt["ttldr"],
                    "tldr_seconds": attempt["tldr_seconds"], "ttldr_seconds": attempt["ttldr_seconds"]}
        feedback = feedback_text(notes, length_problems, reviews)

    best["target_seconds"] = target_seconds
    write_json(path, best)
    if not best["passed"]:
        log(folder, f"Aucun tour n'a passé tous les critères, meilleur tour gardé : {best['round']}")
    return best
