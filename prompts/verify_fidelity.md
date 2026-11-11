You check a shortened version of a YouTube video by Theo (t3.gg) against the full original transcript. The short version was made ONLY by cutting (no reordering, no added words).

You get the original transcript with sentence IDs, the list of kept ranges, and the kept text.

The length budget is fixed (the TLDR length given below, TTLDR 60-120 s). A point being absent is only a problem if it is more important than something that was kept: then name the swap (what to add AND what to remove).

Judge:
- `fidelity_score` 1-10: does the short version represent Theo's views and the facts faithfully? Any distortion (sarcasm taken literally, a setup kept without its punchline, someone else's quote presented as Theo's opinion, an opinion he later revises, a claim kept without a key caveat) is serious.
- `coverage_score` 1-10: does it contain what matters most: the topic, the key facts and test results, Theo's reasoning and his verdict? Is anything kept that is clearly less important than something cut?
- `issues`: each concrete problem with the sentence IDs involved, the type (distortion, missing_key_point, unimportant_kept, missing_caveat), a precise fix as sentence ranges to add or remove, and `blocking`: true only for a real distortion of Theo's view, or a missing thesis or verdict. List at most 5 issues per version, most important first.
