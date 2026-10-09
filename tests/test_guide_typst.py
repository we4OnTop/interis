from interis.analysis.guide import Guide, parse_guide, typst_to_guide_text

TYPST = r'''
#let frage(inhalt, nachfragen: (), hinweis: none, optional: false, kuerzbar: false) = {
  frage-nr.step()
  context strong[#frage-nr.display().]
}
#show: interview.with(titel: [Experteninterview], ziel: [x])

= Aktueller Ablauf

#frage(
  hinweis: [zielt auf „Kontext" (Rolle)],
  nachfragen: ([In der Initialen Phase?], [(Bspw. Miro, Figma, ...)],),
)[Welche *Rolle* spielst du?]

#impuls[Wie würdest du den Weg beschreiben?]
#impuls[In den nächsten Fragen geht es um Timing.]

#frage(optional: true, kuerzbar: true)[#underline[Was passiert?]/ Wie verändert es sich?]
'''


def test_typst_guide_keeps_numbering_probes_tags_and_wordings():
    g = parse_guide(typst_to_guide_text(TYPST))
    assert g.title == "Experteninterview"
    f1, i1, f2 = g.questions
    assert (f1.code, f1.text, f1.section) == ("F1", "Welche Rolle spielst du?", "Aktueller Ablauf")
    assert f1.probes == ["In der Initialen Phase?", "(Bspw. Miro, Figma, ...)"]
    assert f1.hint == "zielt auf „Kontext\" (Rolle)" and not f1.droppable
    assert (i1.code, i1.tags, i1.droppable) == ("I1", ["Impuls"], True)
    assert (f2.code, f2.text, f2.variants) == ("F2", "Was passiert?", ["Wie verändert es sich?"])
    assert f2.tags == ["optional", "Nebenfrage"] and f2.droppable


def test_tags_and_hint_survive_markdown_and_dict_roundtrips():
    g = parse_guide("- F1: Wie geht es? [optional]\n  ! nur bei Zeit\n- F2: Warum [sic] so?")
    assert g.questions[0].tags == ["optional"] and g.questions[0].hint == "nur bei Zeit"
    assert g.questions[1].text == "Warum [sic] so?" and g.questions[1].tags == []
    assert parse_guide(g.to_markdown()).to_dict() == g.to_dict()
    assert Guide.from_dict(g.to_dict()).to_dict() == g.to_dict()


def test_a_missing_optional_question_is_skipped_not_missing():
    from interis.pipeline.types import Transcript, Turn, Word
    from interis.web.review import interview_state

    t = Transcript(meta={}, speakers=[], turns=[Turn("A", 0.0, 1.0, [Word(" a", 0.0, 1.0, 0.9)])],
                   analysis={})
    guide = parse_guide("- F1: Wie geht es?\n- F2: Und sonst? [Nebenfrage]")
    cells = interview_state(t, [], [], guide)["cells"]
    assert (cells["F1"]["status"], cells["F2"]["status"]) == ("missing", "skipped")


def test_room_mic_levelling_raises_the_quiet_speaker_but_not_the_pauses():
    import numpy as np

    from interis.pipeline.asr import SAMPLE_RATE, AsrOptions, level

    rng = np.random.default_rng(0)
    t = np.arange(4 * SAMPLE_RATE) / SAMPLE_RATE
    loud = 0.3 * np.sin(2 * np.pi * 200 * t)
    quiet = 0.01 * np.sin(2 * np.pi * 200 * t)
    pause = 0.0005 * rng.standard_normal(4 * SAMPLE_RATE)
    x = np.concatenate([loud, pause, quiet]).astype(np.float32)
    y = level(x)

    def rms(a):
        return float(np.sqrt(np.mean(a ** 2)))

    s = 4 * SAMPLE_RATE
    mid = slice(SAMPLE_RATE, 3 * SAMPLE_RATE)  # away from the transitions
    before = rms(x[2 * s:][mid]) / rms(x[:s][mid])
    after = rms(y[2 * s:][mid]) / rms(y[:s][mid])
    assert after > 5 * before  # the quiet speaker is much closer to the loud one
    assert rms(y[s:2 * s][mid]) < rms(y[2 * s:][mid]) / 3  # the pause stays below speech
    assert y.dtype == np.float32 and np.abs(y).max() <= 1.0
    assert "room_mic" not in AsrOptions().as_params()  # old cache keys stay valid
    assert AsrOptions(room_mic=True).as_params()["room_mic"] is True


def test_word_error_rate_counts_wrong_missing_and_extra_words():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "wer", Path(__file__).parents[1] / "bench" / "wer.py")
    wer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wer)
    ref = wer.words("Wir nutzen Miro, und Figma!")
    assert wer.errors(ref, wer.words("wir nutzen miro und figma")) == (0, 0, 0)
    assert wer.errors(ref, wer.words("wir nutzen mirror figma ja")) == (1, 1, 1)
