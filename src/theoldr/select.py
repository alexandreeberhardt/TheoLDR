import hashlib
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
        "properties": {
            "first": {"type": "string"},
            "last": {"type": "string"},
            "reason": {"type": "string"},
            "start_check": {"type": "string", "description": (
                "Does the first sentence refer to anything cut (this, that, so, he, the second...)? "
                "Say what it refers to and confirm it is kept or not needed.")},
            "end_check": {"type": "string", "description": (
                "Quote the first sentence AFTER this range in the original and say why cutting it is safe "
                "(it must not be a punchline, a reversal like 'Not quite' or 'But', or a key caveat).")},
        },
        "required": ["first", "last", "reason", "start_check", "end_check"],
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
    "properties": {"ranges": RANGE_SCHEMA, "estimated_seconds": {"type": "number"}},
    "required": ["ranges", "estimated_seconds"],
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
            "sentence_ids": {"type": "array", "items": {"type": "string"}},
            "type": {"type": "string"}, "fix": {"type": "string"}, "blocking": {"type": "boolean"}},
            "required": ["sentence_ids", "type", "fix", "blocking"]}},
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
        bounds = snap(video, first, last)
        if bounds is None:
            notes.append(f"Range {video.sentences[first]['id']}-{video.sentences[last]['id']} has no clean cut "
                         "without touching a sponsor: dropped.")
            continue
        if bounds != (first, last):
            notes.append(f"Range {video.sentences[first]['id']}-{video.sentences[last]['id']} "
                         f"adjusted to {video.sentences[bounds[0]]['id']}-{video.sentences[bounds[1]]['id']} "
                         f"to land on clean cuts.")
        snapped.append(list(bounds))

    snapped.sort()
    merged = []
    for first, last in snapped:
        if merged:
            previous = merged[-1]
            gap = video.cut_before(first) - video.cut_after(previous[1])
            sponsor_between = any(video.sentences[position].get("sponsor")
                                  for position in range(previous[1] + 1, first))
            if first <= previous[1] + 1 or (gap < MERGE_GAP_SECONDS and not sponsor_between):
                previous[1] = max(previous[1], last)
                continue
        merged.append([first, last])
    return merged, notes


def snap(video, first, last):
    """Cale une plage sur des coupes propres : on l'élargit, sauf si cela fait entrer un sponsor,
    auquel cas on la rétrécit. Renvoie None si plus rien ne reste."""
    start = first
    while not video.can_start(start) and not video.sentences[start - 1].get("sponsor"):
        start -= 1
    if not video.can_start(start):
        start = first
        while start <= last and not video.can_start(start):
            start += 1
    end = last
    while not video.can_end(end) and not video.sentences[end + 1].get("sponsor"):
        end += 1
    if not video.can_end(end):
        end = last
        while end >= start and not video.can_end(end):
            end -= 1
    if start > end:
        return None
    return start, end


def total_seconds(video, pairs):
    return sum(video.cut_after(last) - video.cut_before(first) for first, last in pairs)


def kept_positions(pairs):
    return {position for first, last in pairs for position in range(first, last + 1)}


def length_problems(name, seconds, target_seconds=None):
    problems = []
    low, high = TLDR_BOUNDS if name == "tldr" else TTLDR_BOUNDS
    if not low <= seconds <= high:
        problems.append(f"The {name.upper()} is {seconds:.0f}s, outside the limits {low}-{high}s.")
    elif target_seconds and abs(seconds - target_seconds) > TARGET_TOLERANCE * target_seconds:
        problems.append(f"The {name.upper()} is {seconds:.0f}s but the target is {target_seconds:.0f}s.")
    return problems


def clip_to(pairs, allowed):
    """Garde seulement les parties des plages qui tombent dans les plages autorisées (TTLDR dans TLDR)."""
    clipped = []
    for first, last in pairs:
        for allowed_first, allowed_last in allowed:
            start = max(first, allowed_first)
            end = min(last, allowed_last)
            if start <= end:
                clipped.append([start, end])
    return clipped


def kept_text(video, pairs):
    parts = []
    for number, (first, last) in enumerate(pairs, start=1):
        parts.append(f"[{number}] {video.range_text(first, last)}")
    return "\n[CUT]\n".join(parts)


def ranges_as_ids(video, pairs):
    return [{"first": video.sentences[first]["id"], "last": video.sentences[last]["id"],
             "seconds": round(video.cut_after(last) - video.cut_before(first), 1)} for first, last in pairs]


def fingerprint(sentences):
    """Empreinte des phrases : si le transcript change, les identifiants S0123 ne désignent plus
    les mêmes phrases et le plan comme la sélection doivent être refaits."""
    content = json.dumps([[sentence["id"], sentence["text"]] for sentence in sentences])
    return hashlib.sha1(content.encode()).hexdigest()[:16]


def load_if_current(path, sentences):
    if not path.exists():
        return None
    data = read_json(path)
    if data.get("fingerprint") != fingerprint(sentences):
        return None
    return data


def make_outline(video, meta, folder):
    path = folder / "outline.json"
    outline = load_if_current(path, video.sentences)
    if outline:
        return outline
    text = (f"Title: {meta['title']}\nDuration: {format_time(meta['duration'])}\n\n"
            f"Transcript:\n{video.transcript_text(with_cut_marks=False)}")
    outline = ask(prompt("outline"), text, OUTLINE_SCHEMA)
    outline["fingerprint"] = fingerprint(video.sentences)
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


def tldr_sentences_text(video, tldr):
    """Phrases du TLDR, groupées par segment, pour choisir le TTLDR."""
    blocks = []
    for number, (first, last) in enumerate(tldr, start=1):
        lines = [f"--- TLDR segment {number} ---"]
        for position in range(first, last + 1):
            sentence = video.sentences[position]
            mark = " ✂" if video.can_end(position) else ""
            lines.append(f"{sentence['id']}  {video.duration(position):.1f}s  {sentence['text']}{mark}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def request_selection(name, context, previous, feedback):
    text = context
    if previous:
        text += ("\n\nYOUR PREVIOUS SELECTION (after automatic snapping to clean cuts, with real "
                 f"durations):\n{json.dumps(previous, indent=1)}\n\nFEEDBACK TO ADDRESS:\n{feedback}\n\n"
                 "Produce a corrected, complete selection. Fix ONLY the problems listed, by changing only "
                 "the ranges involved; keep every other range exactly as it was.")
    return ask(prompt(f"select_{name}"), text, SELECTION_SCHEMA)


def review(video, name, pairs, budget):
    def blind():
        return ask(prompt("verify_blind"), kept_text(video, pairs), BLIND_SCHEMA)

    def fidelity():
        text = (f"VERSION: {name.upper()}, length budget {budget}.\n\n"
                f"ORIGINAL TRANSCRIPT:\n{video.transcript_text(with_cut_marks=False)}\n\n"
                f"KEPT RANGES:\n{json.dumps(ranges_as_ids(video, pairs))}\n\n"
                f"KEPT TEXT:\n{kept_text(video, pairs)}")
        return ask(prompt("verify_fidelity"), text, FIDELITY_SCHEMA)

    with ThreadPoolExecutor(max_workers=2) as pool:
        blind_future = pool.submit(blind)
        fidelity_future = pool.submit(fidelity)
        return {"blind": blind_future.result(), "fidelity": fidelity_future.result()}


def evaluate(reviews, problems):
    """Réussi = aucun problème bloquant, fidélité >= 8, durée respectée.

    La note de fluidité ne sert qu'à départager les tours : un extrait continu non coupé
    de l'original n'obtient que 4 à 6."""
    blocking = [issue for key in ("blind", "fidelity") for issue in reviews[key]["issues"] if issue.get("blocking")]
    scores = {"flow": reviews["blind"]["score"], "fidelity": reviews["fidelity"]["fidelity_score"],
              "coverage": reviews["fidelity"]["coverage_score"]}
    passed = scores["fidelity"] >= 8 and not blocking and not problems
    total = sum(scores.values()) - 3 * len(blocking) - 3 * len(problems)
    return scores, blocking, passed, total


def feedback_text(notes, problems, reviews):
    """Ne renvoie à l'agent que ce qui doit être corrigé : durée, problèmes bloquants,
    et déformations si la fidélité est insuffisante."""
    issues = []
    for issue in reviews["blind"]["issues"]:
        if issue["blocking"]:
            issues.append(f"- segment {issue.get('segment')}: \"{issue['quote']}\" -> {issue['type']} "
                          f"(first-time viewer): {issue['fix']}")
    low_fidelity = reviews["fidelity"]["fidelity_score"] < 8
    for issue in reviews["fidelity"]["issues"]:
        if issue["blocking"] or (low_fidelity and issue["type"] in ("distortion", "missing_caveat")):
            issues.append(f"- {', '.join(issue['sentence_ids'])}: {issue['type']} "
                          f"(reviewer who knows the full video): {issue['fix']}")
    if low_fidelity and not issues:
        for issue in reviews["fidelity"]["issues"][:3]:
            issues.append(f"- {', '.join(issue['sentence_ids'])}: {issue['type']}: {issue['fix']}")
    lines = []
    if problems:
        lines.append("LENGTH: " + " ".join(problems))
    if notes:
        lines.append("AUTOMATIC ADJUSTMENTS: " + " ".join(notes))
    return "\n".join(lines + issues)


def selection_loop(video, folder, name, context, budget, target_seconds=None, allowed=None):
    """Choisit une version (tldr ou ttldr), la fait juger, et la révise jusqu'à MAX_ROUNDS fois."""
    best = None
    previous = None
    feedback = None
    for round_number in range(1, MAX_ROUNDS + 1):
        raw = request_selection(name, context, previous, feedback)
        pairs, notes = normalize(video, raw["ranges"])
        if allowed is not None:
            clipped = clip_to(pairs, allowed)
            if kept_positions(clipped) != kept_positions(pairs):
                notes.append("Parts outside the TLDR were removed.")
            pairs = clipped
        seconds = total_seconds(video, pairs)
        problems = length_problems(name, seconds, target_seconds)
        if pairs:
            reviews = review(video, name, pairs, budget)
            scores, blocking, passed, total = evaluate(reviews, problems)
        else:
            reviews = {"blind": {"score": 0, "issues": []}, "fidelity": {"fidelity_score": 0, "coverage_score": 0,
                                                                          "issues": []}}
            scores, blocking, passed, total = {"flow": 0, "fidelity": 0, "coverage": 0}, [], False, -100
            problems.append("The selection is empty after removing sponsors and parts outside the allowed text.")
        in_bounds = not any("outside the limits" in problem for problem in problems)
        attempt = {"round": round_number, "raw": raw, "notes": notes, "length_problems": problems,
                   "ranges": ranges_as_ids(video, pairs), "seconds": round(seconds, 1), "reviews": reviews,
                   "scores": scores, "blocking": len(blocking), "passed": passed, "total": total,
                   "rank": (passed, bool(pairs), in_bounds, total)}
        write_json(folder / "attempts" / f"{name}_round{round_number}.json", attempt)
        log(folder, f"{name.upper()} tour {round_number} : {seconds:.0f} s, {len(pairs)} segments, "
                    f"scores {scores}, bloquants {len(blocking)}")
        if best is None or attempt["rank"] > best["rank"]:
            best = attempt
        if passed:
            break
        previous = {"ranges": attempt["ranges"], "seconds": attempt["seconds"]}
        feedback = feedback_text(notes, problems, reviews)
    if not best["passed"]:
        log(folder, f"{name.upper()} : aucun tour n'a passé tous les critères, meilleur tour gardé : {best['round']}")
    return best


def select(sentences, meta, folder):
    path = folder / "selection.json"
    selection = load_if_current(path, sentences)
    if selection:
        return selection
    video = Video(sentences)
    outline = make_outline(video, meta, folder)
    apply_extra_sponsors(video, outline)
    target_minutes = min(max(outline["tldr_target_minutes"], 5), 15, 0.4 * meta["duration"] / 60)
    target_seconds = max(target_minutes, 5) * 60
    log(folder, f"Plan fait, densité {outline['density']}, cible TLDR {target_seconds / 60:.1f} min")
    (folder / "attempts").mkdir(exist_ok=True)

    tldr_context = (f"Title: {meta['title']}\nOriginal duration: {format_time(meta['duration'])}\n"
                    f"TLDR target: {target_seconds / 60:.1f} min ({target_seconds:.0f}s).\n\n"
                    f"Outline:\n{json.dumps(outline, indent=1)}\n\nTranscript:\n{video.transcript_text()}")
    tldr = selection_loop(video, folder, "tldr", tldr_context, f"{target_seconds:.0f}s", target_seconds)
    tldr_pairs = [[video.index[item["first"]], video.index[item["last"]]] for item in tldr["ranges"]]

    ttldr_context = (f"Title: {meta['title']}\nTTLDR length: 60-120s.\n\n"
                     f"Topic: {outline['topic']}\nTheo's thesis: {outline['thesis']}\n\n"
                     f"TLDR sentences:\n{tldr_sentences_text(video, tldr_pairs)}")
    ttldr = selection_loop(video, folder, "ttldr", ttldr_context, "60-120s", allowed=tldr_pairs)

    selection = {
        "tldr": tldr["ranges"], "ttldr": ttldr["ranges"],
        "tldr_seconds": tldr["seconds"], "ttldr_seconds": ttldr["seconds"], "target_seconds": target_seconds,
        "rounds": {"tldr": tldr["round"], "ttldr": ttldr["round"]},
        "scores": {"tldr_flow": tldr["scores"]["flow"], "ttldr_flow": ttldr["scores"]["flow"],
                   "tldr_fidelity": tldr["scores"]["fidelity"], "ttldr_fidelity": ttldr["scores"]["fidelity"],
                   "tldr_coverage": tldr["scores"]["coverage"], "ttldr_coverage": ttldr["scores"]["coverage"]},
        "passed": tldr["passed"] and ttldr["passed"],
        "fingerprint": fingerprint(sentences),
    }
    write_json(path, selection)
    return selection


def final_ranges(sentences, selection, folder):
    """Revalide les plages avant le rendu (utile après une retouche à la main de selection.json) :
    coupes propres, pas de sponsor, ordre, et TTLDR inclus dans le TLDR."""
    video = Video(sentences)
    outline_path = folder / "outline.json"
    if outline_path.exists():
        apply_extra_sponsors(video, read_json(outline_path))
    tldr, _ = normalize(video, selection["tldr"])
    ttldr, _ = normalize(video, selection["ttldr"])
    ttldr = clip_to(ttldr, tldr)
    if not tldr or not ttldr:
        raise RuntimeError("Sélection vide après validation : impossible de rendre la vidéo")
    return {"tldr": ranges_as_ids(video, tldr), "ttldr": ranges_as_ids(video, ttldr)}
