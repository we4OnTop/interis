"""Word-level forced alignment with a German wav2vec2 CTC model.

Same method as WhisperX (Bain et al., Interspeech 2023): for each Whisper segment the
wav2vec2 model produces per-frame character log-probabilities (~20 ms frames) and a CTC
Viterbi pass finds the most likely position of the known transcript characters. This gives
much more precise word boundaries than Whisper's own timestamps, which matters for cutting
speaker turns exactly.

Words without alignable characters (e.g. numbers "2024", "%") keep Whisper's timestamps,
clipped between their aligned neighbours. ``Word.aligned`` records which case applies.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from interis._bootstrap import require_offline
from interis.pipeline.types import Segment, Word

SAMPLE_RATE = 16000
PAD_S = 0.3  # context added around each segment window
Progress = Callable[[str, float], None]


def ctc_viterbi(logp: np.ndarray, tokens: list[int], blank: int) -> np.ndarray | None:
    """Best CTC path. Returns the extended-state index per frame, or None if impossible.

    ``logp`` has shape (frames, vocab). Extended states interleave blanks with tokens:
    ``[blank, t0, blank, t1, …, t_{n-1}, blank]``; token ``j`` is state ``2*j + 1``.
    """
    n_frames = logp.shape[0]
    n_states = 2 * len(tokens) + 1
    ext = np.full(n_states, blank, dtype=np.int64)
    ext[1::2] = tokens
    # A state may be entered from two states back when it is a token that differs from
    # the token two states earlier (CTC's skip-over-blank transition).
    skip = np.zeros(n_states, dtype=bool)
    skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])

    em = logp[:, ext].astype(np.float64)
    neg = -np.inf
    alpha = np.full(n_states, neg)
    alpha[0] = em[0, 0]
    if n_states > 1:
        alpha[1] = em[0, 1]
    back = np.zeros((n_frames, n_states), dtype=np.int8)
    cand = np.empty((3, n_states))
    for t in range(1, n_frames):
        cand[0] = alpha
        cand[1, 0] = neg
        cand[1, 1:] = alpha[:-1]
        cand[2, :2] = neg
        cand[2, 2:] = alpha[:-2]
        cand[2, ~skip] = neg
        choice = cand.argmax(axis=0)
        back[t] = choice
        alpha = cand[choice, np.arange(n_states)] + em[t]

    last = n_states - 1
    end = last if n_states == 1 or alpha[last] >= alpha[last - 1] else last - 1
    if not np.isfinite(alpha[end]):
        return None
    path = np.empty(n_frames, dtype=np.int64)
    state = end
    for t in range(n_frames - 1, -1, -1):
        path[t] = state
        state -= int(back[t, state])  # int(): avoid int8 arithmetic overflow (NumPy 2)
    if path[0] > 1:
        return None
    return path


class Aligner:
    def __init__(self, model_dir: Path, threads: int | None = None) -> None:
        require_offline()
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        if threads:
            torch.set_num_threads(threads)
        self._torch = torch
        self.processor = Wav2Vec2Processor.from_pretrained(model_dir, local_files_only=True)
        self.model = Wav2Vec2ForCTC.from_pretrained(
            model_dir, local_files_only=True, use_safetensors=True
        ).eval()
        vocab = self.processor.tokenizer.get_vocab()
        self.char_to_id = {k.lower(): v for k, v in vocab.items() if len(k) == 1}
        self.delimiter = vocab.get("|")
        self.blank = self.processor.tokenizer.pad_token_id

    def _log_probs(self, audio: np.ndarray) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.inference_mode():
            logits = self.model(inputs.input_values).logits[0]
        return torch.log_softmax(logits, dim=-1).numpy()

    def _chars(self, word: Word) -> list[int]:
        return [self.char_to_id[c] for c in word.text.strip().lower()
                if c in self.char_to_id and c != "|"]

    def align_segment(self, audio: np.ndarray, seg: Segment) -> None:
        if not seg.words:
            return
        win_start = max(0.0, min(seg.start, seg.words[0].start) - PAD_S)
        win_end = min(len(audio) / SAMPLE_RATE, max(seg.end, seg.words[-1].end) + PAD_S)
        chunk = audio[int(win_start * SAMPLE_RATE):int(win_end * SAMPLE_RATE)]
        if len(chunk) < SAMPLE_RATE // 10:
            return

        tokens: list[int] = []
        spans: dict[int, tuple[int, int]] = {}  # word index -> (first token, last token)
        for i, word in enumerate(seg.words):
            chars = self._chars(word)
            if not chars:
                continue
            if tokens and self.delimiter is not None:
                tokens.append(self.delimiter)
            spans[i] = (len(tokens), len(tokens) + len(chars) - 1)
            tokens.extend(chars)
        if not tokens:
            return

        logp = self._log_probs(chunk)
        path = ctc_viterbi(logp, tokens, self.blank)
        if path is None:
            return  # not enough frames; keep Whisper timestamps
        frame_s = (len(chunk) / SAMPLE_RATE) / logp.shape[0]

        for i, (first, last) in spans.items():
            first_frames = np.flatnonzero(path == 2 * first + 1)
            last_frames = np.flatnonzero(path == 2 * last + 1)
            if first_frames.size == 0 or last_frames.size == 0:
                continue
            w = seg.words[i]
            w.start = round(win_start + first_frames[0] * frame_s, 3)
            w.end = round(win_start + (last_frames[-1] + 1) * frame_s, 3)
            w.aligned = True
        _clip_unaligned(seg.words)


def _clip_unaligned(words: list[Word]) -> None:
    """Keep Whisper times for unaligned words, but inside their aligned neighbours."""
    for i, w in enumerate(words):
        if w.aligned:
            continue
        prev_end = next((words[j].end for j in range(i - 1, -1, -1) if words[j].aligned), None)
        next_start = next((words[j].start for j in range(i + 1, len(words))
                           if words[j].aligned), None)
        if prev_end is not None:
            w.start = max(w.start, prev_end)
        if next_start is not None:
            w.end = min(w.end, next_start)
        if w.end < w.start:
            w.end = w.start


def align(audio: np.ndarray, segments: list[Segment], model_dir: Path,
          threads: int | None = None, progress: Progress | None = None) -> list[Segment]:
    aligner = Aligner(model_dir, threads)
    for n, seg in enumerate(segments, 1):
        aligner.align_segment(audio, seg)
        if progress:
            progress("align", n / max(len(segments), 1))
    return segments
