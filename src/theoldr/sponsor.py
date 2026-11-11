import json
import urllib.error
import urllib.parse
import urllib.request

from .common import read_json, write_json

API = "https://sponsor.ajay.app/api/skipSegments"
CATEGORIES = ["sponsor", "selfpromo"]


def fetch_sponsors(video_id, out_path):
    """SponsorBlock segments. If the service is down, carry on without them (the agent also spots
    sponsors) and cache nothing, so the next run tries again."""
    if out_path.exists():
        return read_json(out_path)
    query = urllib.parse.urlencode({"videoID": video_id, "categories": json.dumps(CATEGORIES)})
    try:
        with urllib.request.urlopen(f"{API}?{query}", timeout=20) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code != 404:
            return []
        data = []
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    segments = [{"category": item["category"], "start": item["segment"][0], "end": item["segment"][1]}
                for item in data]
    write_json(out_path, segments)
    return segments


def mark_sponsors(sentences, segments):
    """Flags sentences that fall more than halfway inside a SponsorBlock segment."""
    for sentence in sentences:
        length = max(sentence["next_start"] - sentence["start"], 0.01)
        covered = 0
        for segment in segments:
            overlap = min(sentence["next_start"], segment["end"]) - max(sentence["start"], segment["start"])
            covered += max(overlap, 0)
        sentence["sponsor"] = covered / length > 0.5
    return sentences
