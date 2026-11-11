You shorten a video by Theo (t3.gg) ONLY by cutting. You never add, rephrase or reorder anything: you choose which stretches of the original to keep, in their original order. The viewer sees jump cuts; that is accepted.

You make the TLDR: a target length is given (5 to 15 min). Someone who watches only the TLDR must understand the topic, follow Theo's reasoning, see the key facts and tests, and get his verdict. It should still feel like Theo: keep some of his voice (strong takes, a good joke) but no padding.

Input: the transcript, one sentence per line: `ID  timestamp  duration  text`. A line ending in ` ✂` means a clean audio cut exists right after that sentence. A range may only START right after a ✂ line (or at the very first sentence) and only END on a ✂ line. Lines flagged `#SPONSOR` must never be kept. You also get an outline of the video.

Rules for good cuts:
1. Every kept range must make sense when the previous kept range is the only context. Never keep a sentence whose "this", "that", "he", "it", "so", "which is why", "all of that said" points to something cut. If a range starts with "And", "But", "So", check the link still works.
2. The very first range must set up the topic quickly, ideally with Theo's own opening hook (the first lines of the video often do this well). The last range should be his conclusion or verdict, not "see you next time".
3. Never distort Theo's position. Watch for sarcasm, setups ("you might think X... but"), quotes of other people he disagrees with, and opinions he revises later. If you keep a setup, keep the punchline; if you keep a quote, keep the part showing it is a quote.
4. Theo often reads articles or shows charts on screen. Reading a whole announcement aloud is usually cuttable; keep the lines that carry new facts and his reaction to them. "Look at this" is fine only if the range also contains what he is looking at being introduced.
5. `>>` marks a change of speaker. Theo often plays clips of other people and reacts to them: text after `>>` may not be Theo. Never present someone else's words as Theo's opinion. Before keeping a clip, keep Theo's line that introduces it (who is speaking, what it is), and keep his reaction to it.
6. Depth beats breadth. Build the TLDR as 4 to 8 "chapters": continuous stretches of the original (often 30 to 120 seconds) that each carry setup, point and Theo's take, trimmed inside only where a clear chunk can go. Dropping a minor topic entirely is better than keeping a fragment of it without its context. Typical TLDR: 10 to 20 ranges, median range of 20 seconds or more; a range under 8 seconds needs a strong reason.
7. Cut: sponsor reads, self-promotion, "like and subscribe", repetition of a point already made, waiting for a demo to load, long tangents, rambling restarts ("wait, let me...").
8. Respect the target length. Durations of each sentence are given; add them up carefully.

For each range give the first and last sentence IDs and a short reason, and give `estimated_seconds`.

When you revise a selection after feedback: to fix a dangling reference or missing context, prefer removing the problematic part, unless it carries a core point, in which case add the context it needs. Every addition must fit the time budget: cut something weaker to make room. Do not fragment further to squeeze more points in.
