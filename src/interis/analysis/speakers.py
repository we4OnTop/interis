"""Speakers by reference: you mark who speaks in the first minute(s), the rest of the
interview is assigned by voice.

Diarization alone groups the recording into speakers without knowing anyone's voice; with
one room microphone it often groups by distance or background instead. Here every
speaker's voice is learned from the reference stretch you checked (an embedding per
sentence, averaged per speaker, with community-1's own embedding model), and every later
sentence goes to the speaker whose voice it is most similar to, but only when that is
clearly so (``margin``). Short sentences ("Ja.", "Mhm.") carry too little voice and keep
their speaker.

Pure logic: the embedding function is passed in, so this is testable without models.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from interis.analysis.sentences import Sentence

Embed = Callable[[float, float], np.ndarray]


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def reassign(sentences: list[Sentence], words_of: Callable[[Sentence], list], embed: Embed,
             until: float, margin: float = 0.1, min_s: float = 1.0,
             progress: Callable[[float], None] | None = None,
             ) -> tuple[list[dict], dict[str, int]]:
    """``sentences``: of the effective transcript (speaker corrections applied).
    ``words_of(sentence)``: its ``(turn, word index, word)`` triples.
    Returns the speaker changes ``{turn, word, speaker}`` and counts for the report."""
    reference: dict[str, list[np.ndarray]] = {}
    for s in sentences:
        if s.end <= until and s.speaker and s.end - s.start >= min_s:
            reference.setdefault(s.speaker, []).append(_unit(embed(s.start, s.end)))
    if len(reference) < 2:
        raise ValueError("the reference needs sentences of at least two speakers "
                         f"(found: {sorted(reference) or 'none'}); choose a longer reference")
    voices = {spk: _unit(np.mean(v, axis=0)) for spk, v in reference.items()}

    later = [s for s in sentences if s.start >= until]
    changes: list[dict] = []
    stats = {"reference": sum(map(len, reference.values())), "checked": 0, "changed": 0,
             "unsure": 0, "short": 0}
    for i, s in enumerate(later):
        if progress:
            progress((i + 1) / len(later))
        if s.end - s.start < min_s:
            stats["short"] += 1
            continue
        stats["checked"] += 1
        e = _unit(embed(s.start, s.end))
        ranked = sorted(((float(e @ v), spk) for spk, v in voices.items()), reverse=True)
        (best, who), (second, _) = ranked[0], ranked[1]
        if best - second < margin:
            stats["unsure"] += 1
            continue
        moved = [(t, w) for t, w, word in words_of(s)
                 if word.text.strip() and (word.speaker or s.speaker) != who]
        if moved:
            stats["changed"] += 1
            changes += [{"turn": t, "word": w, "speaker": who} for t, w in moved]
    return changes, stats
