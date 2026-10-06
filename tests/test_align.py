import numpy as np

from interis.pipeline.align import _clip_unaligned, ctc_viterbi
from interis.pipeline.types import Word

BLANK = 0


def _emissions(frame_tokens: list[int], vocab: int = 5) -> np.ndarray:
    """Log-probs where frame t strongly prefers frame_tokens[t]."""
    logp = np.full((len(frame_tokens), vocab), np.log(0.01))
    for t, tok in enumerate(frame_tokens):
        logp[t, tok] = np.log(0.96)
    return logp


def _token_frames(path: np.ndarray, j: int) -> list[int]:
    return np.flatnonzero(path == 2 * j + 1).tolist()


def test_viterbi_finds_token_positions():
    # frames: _ _ 1 1 _ 2 _ _ 3 3 _
    frames = [0, 0, 1, 1, 0, 2, 0, 0, 3, 3, 0]
    path = ctc_viterbi(_emissions(frames), [1, 2, 3], BLANK)
    assert path is not None
    assert _token_frames(path, 0) == [2, 3]
    assert _token_frames(path, 1) == [5]
    assert _token_frames(path, 2) == [8, 9]


def test_viterbi_repeated_tokens_need_blank_between():
    # "1 1" as two tokens requires a blank between them
    frames = [1, 0, 1]
    path = ctc_viterbi(_emissions(frames), [1, 1], BLANK)
    assert path is not None
    assert _token_frames(path, 0) == [0]
    assert _token_frames(path, 1) == [2]


def test_viterbi_impossible_when_too_few_frames():
    assert ctc_viterbi(_emissions([1, 2]), [1, 2, 3], BLANK) is None
    assert ctc_viterbi(_emissions([1, 1]), [1, 1], BLANK) is None


def test_viterbi_every_token_gets_frames_monotonically():
    rng = np.random.default_rng(0)
    # > 127 extended states, so int8 back-pointers must not overflow during backtracking
    logp = np.log(rng.dirichlet(np.ones(6), size=600))
    tokens = rng.integers(1, 6, size=150).tolist()
    path = ctc_viterbi(logp, tokens, BLANK)
    assert path is not None
    firsts = [_token_frames(path, j)[0] for j in range(len(tokens))]
    assert firsts == sorted(firsts)
    assert np.all(np.diff(path) >= 0)


def test_unaligned_words_are_clipped_between_neighbours():
    words = [
        Word(" Im", 1.0, 1.2, 0.9, aligned=True),
        Word(" 2024", 0.9, 2.5, 0.9, aligned=False),
        Word(" Jahr", 2.0, 2.4, 0.9, aligned=True),
    ]
    _clip_unaligned(words)
    assert (words[1].start, words[1].end) == (1.2, 2.0)
