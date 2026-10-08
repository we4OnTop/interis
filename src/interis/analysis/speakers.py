"""Speakers by voice: the rest of the interview is assigned by how each sentence sounds.

Diarization alone groups the recording into speakers without knowing anyone's voice; with
one room microphone it often groups by distance or background instead. Here the voices
are known in advance, from

* a **reference**: the start of this interview, checked by you (``until``), and/or
* a **voice profile** of the interviewer, learned from another interview you corrected
  completely (same person in every interview). The interviewee's voice is then learned
  from this interview itself: from the sentences that sound least like the interviewer
  (the interviewee usually speaks most of the time).

Every sentence gets an embedding with community-1's own speaker embedding model and goes
to the voice it is most similar to, but only when that is clearly so (``margin``). Short
sentences ("Ja.", "Mhm.") carry too little voice and keep their speaker.

Pure logic: the embedding function is passed in, so this is testable without models.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import numpy as np

from interis.analysis.sentences import Sentence

Embed = Callable[[float, float], np.ndarray]
LEAST_LIKE_SHARE = 0.3  # with a profile: this share of sentences teaches the other voice


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def reassign(sentences: list[Sentence], words_of: Callable[[Sentence], list], embed: Embed,
             until: float, margin: float = 0.1, min_s: float = 1.0,
             progress: Callable[[float], None] | None = None,
             voice: np.ndarray | None = None, labels: list[str] | None = None,
             interviewer: str | None = None) -> tuple[list[dict], dict[str, int]]:
    """``sentences``: of the effective transcript (speaker corrections applied).
    ``words_of(sentence)``: its ``(turn, word index, word)`` triples.
    ``voice``: the interviewer's voice profile; ``labels``: the transcript's speakers;
    ``interviewer``: the interviewer's label, if known (else: whose sentences sound most
    like the profile). Returns the speaker changes ``{turn, word, speaker}`` and counts."""
    long = [i for i, s in enumerate(sentences) if s.end - s.start >= min_s]
    emb: dict[int, np.ndarray] = {}
    for n, i in enumerate(long):
        s = sentences[i]
        emb[i] = unit(embed(s.start, s.end))
        if progress:
            progress((n + 1) / len(long))

    reference: dict[str, list[np.ndarray]] = {}
    for i in long:
        s = sentences[i]
        if s.end <= until and s.speaker:
            reference.setdefault(s.speaker, []).append(emb[i])
    voices = {spk: unit(np.mean(v, axis=0)) for spk, v in reference.items()}

    if voice is not None:
        profile = unit(np.asarray(voice, dtype=float))
        if interviewer is None:
            sims: dict[str, list[float]] = {}
            for i in long:
                if sentences[i].speaker:
                    sims.setdefault(sentences[i].speaker, []).append(float(emb[i] @ profile))
            interviewer = max(sims, key=lambda k: np.mean(sims[k])) if sims else None
        others = [lab for lab in labels or [] if lab != interviewer]
        if interviewer is None or not others:
            raise ValueError("a voice profile needs a transcript with two speakers")
        voices[interviewer] = profile
        if not any(spk != interviewer for spk in voices):
            spoken = Counter(s.speaker for s in sentences if s.speaker in others)
            other = spoken.most_common(1)[0][0] if spoken else others[0]
            unlike = sorted(long, key=lambda i: float(emb[i] @ profile))
            unlike = unlike[:max(3, int(LEAST_LIKE_SHARE * len(long)))]
            if len(unlike) < 3:
                raise ValueError("too few sentences to learn the interviewee's voice")
            voices[other] = unit(np.mean([emb[i] for i in unlike], axis=0))
    if len(voices) < 2:
        raise ValueError("the reference needs sentences of at least two speakers "
                         f"(found: {sorted(voices) or 'none'}); choose a longer reference")

    changes: list[dict] = []
    stats = {"reference": sum(map(len, reference.values())), "checked": 0, "changed": 0,
             "unsure": 0, "short": 0}
    for i, s in enumerate(sentences):
        if s.start < until:
            continue
        if i not in emb:
            stats["short"] += 1
            continue
        stats["checked"] += 1
        ranked = sorted(((float(emb[i] @ v), spk) for spk, v in voices.items()), reverse=True)
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


def voice_of(sentences: list[Sentence], embed: Embed, speaker: str, min_s: float = 1.0,
             progress: Callable[[float], None] | None = None) -> np.ndarray:
    """A voice profile: the mean embedding of all of ``speaker``'s sentences (of a
    transcript whose speakers you checked)."""
    own = [s for s in sentences if s.speaker == speaker and s.end - s.start >= min_s]
    if len(own) < 5:
        raise ValueError(f"too few sentences of {speaker} to learn the voice (at least 5 of "
                         f"{min_s:g} s or longer)")
    vecs = []
    for n, s in enumerate(own):
        vecs.append(unit(embed(s.start, s.end)))
        if progress:
            progress((n + 1) / len(own))
    return unit(np.mean(vecs, axis=0))
