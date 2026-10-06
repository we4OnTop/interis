from interis.pipeline.merge import build_turns
from interis.pipeline.types import Diarization, Segment, SpeakerSpan, Word


def _seg(words):
    return Segment(0, words[0].start, words[-1].end, "", words, -0.1, 0.0, 1.0, 0.0)


def _w(text, start, end):
    return Word(text, start, end, 0.9)


def test_words_are_assigned_and_grouped_into_turns():
    words = [_w(" Wie", 0.0, 0.3), _w(" geht's?", 0.3, 0.8),
             _w(" Gut,", 1.2, 1.5), _w(" danke.", 1.5, 1.9)]
    diar = Diarization(
        regular=[SpeakerSpan(0.0, 0.9, "SPEAKER_00"), SpeakerSpan(1.1, 2.0, "SPEAKER_01")],
        exclusive=[SpeakerSpan(0.0, 0.9, "SPEAKER_00"), SpeakerSpan(1.1, 2.0, "SPEAKER_01")],
    )
    turns = build_turns([_seg(words)], diar)
    assert [(t.speaker, t.text) for t in turns] == [
        ("SPEAKER_00", "Wie geht's?"),
        ("SPEAKER_01", "Gut, danke."),
    ]


def test_word_takes_speaker_with_largest_overlap_and_overlap_is_flagged():
    words = [_w(" ja", 1.0, 2.0)]
    diar = Diarization(
        regular=[SpeakerSpan(0.0, 1.3, "A"), SpeakerSpan(1.2, 3.0, "B")],
        exclusive=[SpeakerSpan(0.0, 1.3, "A"), SpeakerSpan(1.3, 3.0, "B")],
    )
    build_turns([_seg(words)], diar)
    assert words[0].speaker == "B"
    assert words[0].overlap is True


def test_word_in_gap_takes_nearest_speaker_within_one_second():
    words = [_w(" a", 0.0, 0.5), _w(" b", 2.2, 2.4)]
    diar = Diarization(regular=[SpeakerSpan(0.0, 0.6, "A"), SpeakerSpan(2.5, 3.0, "B")],
                       exclusive=[SpeakerSpan(0.0, 0.6, "A"), SpeakerSpan(2.5, 3.0, "B")])
    build_turns([_seg(words)], diar)
    assert [w.speaker for w in words] == ["A", "B"]


def test_word_far_from_any_speech_inherits_previous_speaker():
    words = [_w(" a", 0.0, 0.5), _w(" b", 10.0, 10.4)]
    diar = Diarization(regular=[SpeakerSpan(0.0, 0.6, "A")],
                       exclusive=[SpeakerSpan(0.0, 0.6, "A")])
    turns = build_turns([_seg(words)], diar)
    assert [w.speaker for w in words] == ["A", "A"]
    assert len(turns) == 1


def test_without_diarization_each_segment_is_a_turn():
    s1, s2 = _seg([_w(" Hallo", 0, 1)]), _seg([_w(" Welt", 2, 3)])
    turns = build_turns([s1, s2], None)
    assert [(t.speaker, t.text) for t in turns] == [(None, "Hallo"), (None, "Welt")]
