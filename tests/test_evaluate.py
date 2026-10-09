import pytest

from interis.pipeline.evaluate import (
    align,
    glossary,
    hyp_tokens,
    pool,
    reference_from_transcript,
    score,
    tokenize,
)
from interis.pipeline.types import Transcript, Turn, Word


def _t(*turns, start=0.0):
    """turns: (speaker label, text); one word per token, 0.5 s each."""
    out, clock = [], start
    for spk, text in turns:
        words = []
        for tok in text.split():
            words.append(Word(f" {tok}", clock, clock + 0.5, 0.9, speaker=spk))
            clock += 0.5
        out.append(Turn(spk, words[0].start, words[-1].end, words))
    return Transcript({"interview_id": "x"}, [{"label": "A"}, {"label": "B"}], out)


def test_tokenize_drops_punctuation_and_annotations():
    assert [n for n, _ in tokenize("Wie geht's, [lacht] Müller-Lüdenscheidt?")] == [
        "wie", "geht's", "müller", "lüdenscheidt"]


def test_align_counts_edits_exactly():
    assert align("a b c d".split(), "a x c d e".split()) == [
        (0, 0), (1, 1), (2, 2), (3, 3), (None, 4)]


def test_align_handles_a_shifted_start():
    ref = [f"w{i}" for i in range(300)]
    pairs = align(ref, ["extra"] * 5 + ref[:-3])
    assert sum(i is None for i, _ in pairs) == 5 and sum(j is None for _, j in pairs) == 3


def test_reference_takes_only_the_window_with_effective_speakers():
    t = _t(("A", "eins zwei drei"), ("B", "vier fünf sechs"), ("A", "sieben acht"))
    ref = reference_from_transcript(t, 1.5, 3.0)
    assert ref.norm == ["vier", "fünf", "sechs"] and ref.speakers == ["B", "B", "B"]
    t.turns[1].words[0].speaker = "A"  # a speaker correction
    assert reference_from_transcript(t, 1.5, 3.0).speakers == ["A", "B", "B"]


def test_scores_count_words_and_speakers_independent_of_label_names():
    ref = reference_from_transcript(_t(("A", "wie geht es dir"), ("B", "gut danke sehr")))
    # the machine called the speakers X/Y and put one word on the wrong person
    hyp = hyp_tokens(_t(("X", "wie geht das dir"), ("Y", "gut danke sehr")))
    hyp.speakers[0] = "Y"
    s = score(ref, hyp)
    assert s.substitutions == 1 and s.deletions == s.insertions == 0
    assert s.wer == pytest.approx(1 / 7, abs=1e-3)
    assert s.speaker_errors == 1 and s.speaker_error == pytest.approx(1 / 7, abs=1e-3)


def test_swapped_labels_are_no_error_but_a_wrong_split_is():
    ref = reference_from_transcript(_t(("A", "a b c d"), ("B", "e f g h")))
    swapped = hyp_tokens(_t(("B", "a b c d"), ("A", "e f g h")))
    assert score(ref, swapped).speaker_error == 0
    one_speaker = hyp_tokens(_t(("A", "a b c d e f g h")))
    assert score(ref, one_speaker).speaker_errors == 4


def test_perfect_transcript_scores_zero_and_pool_weights_by_length():
    t = _t(("A", "wie geht es dir"), ("B", "gut danke"))
    assert score(reference_from_transcript(t), hyp_tokens(t)).loss == 0
    a = score(reference_from_transcript(_t(("A", "a b c d"))), hyp_tokens(_t(("A", "a b c x"))))
    b = score(reference_from_transcript(_t(("A", "a b"))), hyp_tokens(_t(("A", "a b"))))
    assert pool([a, b]).wer == pytest.approx(1 / 6, abs=1e-3)


def test_glossary_collects_what_you_corrected():
    ref = reference_from_transcript(_t(("A", "wir nutzen Kubernetes bei Müller")))
    hyp = hyp_tokens(_t(("A", "wir nutzen Kuber netes bei Müller")))
    assert glossary(ref, hyp) == ["Kubernetes"]
