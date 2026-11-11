You check a shortened version of a YouTube video by Theo (t3.gg) against the full original transcript. The short version was made ONLY by cutting (no reordering, no added words).

You get the original transcript with sentence IDs, the list of kept ranges, and the kept text, for ONE version: a TLDR (5 to 15 min) or a TTLDR (60 to 120 s).

The length budget is fixed (given below). A point being absent is only a problem if it is more important than something that was kept: then name the swap (what to add AND what to remove).

Judge:
- `fidelity_score` 1-10: does the short version represent Theo's views and the facts faithfully? Any distortion (sarcasm taken literally, a setup kept without its punchline, someone else's quote presented as Theo's opinion, an opinion he later revises, a claim kept without a key caveat) is serious.
- `coverage_score` 1-10: does it contain what matters most for its length? For a TLDR: the topic, the key facts and test results, Theo's reasoning and his verdict. For a TTLDR: the topic, the single most important point and Theo's verdict; a TTLDR is not expected to cover everything. Is anything kept that is clearly less important than something cut?
- `issues`: each concrete problem with the sentence IDs involved, the type (distortion, missing_key_point, unimportant_kept, missing_caveat), a precise fix as sentence ranges to add or remove, and `blocking`: true only for a real distortion of Theo's view, or a missing thesis or verdict. List at most 5 issues, most important first.

`>>` in the transcript marks a change of speaker. Theo often plays clips of other people (videos, interviews) and reacts to them: text after `>>` may not be Theo. Never present someone else's words as Theo's opinion.
