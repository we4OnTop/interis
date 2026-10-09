"""Paragraphs typed in by hand: they take a place among the turns, everything stored for later
turns moves with them, and the analysis sees them."""

import json

from interis.pipeline.types import Transcript, Turn, Word
from interis.web.edits import (
    EMPTY_DIGEST,
    apply_edits,
    edits_digest,
    insert_words,
    with_inserts,
)
from interis.web.jobs import JobRunner
from interis.web.store import Store
from tests.test_web import H, client, data_dir  # noqa: F401 – fixtures


def _t():
    def turn(spk, start):
        words = [Word(f" w{i}", start + i, start + i + 1, 0.9, speaker=spk) for i in range(3)]
        return Turn(spk, start, start + 3, words)

    return Transcript({"interview_id": "T"}, [{"label": "A"}, {"label": "B"}],
                      [turn("A", 0), turn("B", 10), turn("A", 20)])


def test_words_share_the_time_in_proportion_to_their_length():
    words = insert_words("Ja genau zufrieden", 10.0, 14.0, "A")
    assert [w.text for w in words] == [" Ja", " genau", " zufrieden"]
    assert words[0].start == 10.0 and abs(words[-1].end - 14.0) < 1e-6
    assert all(a.end <= b.start + 1e-9 for a, b in zip(words, words[1:], strict=False))
    assert words[2].end - words[2].start > words[0].end - words[0].start
    assert all(w.speaker == "A" for w in words)


def test_inserted_paragraphs_take_their_position_and_the_original_is_untouched():
    t = _t()
    ins = [{"id": 1, "at": 1, "speaker": "B", "start": 5.0, "end": 6.0, "text": "Mhm"},
           {"id": 2, "at": 3, "speaker": "A", "start": 12.0, "end": 14.0, "text": "Ja klar"}]
    merged = with_inserts(t, ins)
    assert len(t.turns) == 3 and len(merged.turns) == 5
    assert [x.speaker for x in merged.turns] == ["A", "B", "B", "A", "A"]
    assert merged.turns[1].text == "Mhm" and merged.turns[3].text == "Ja klar"
    assert merged.turns[2].start == 10  # the recorded turn that followed moved to 2
    assert with_inserts(t, []) is t
    # corrections refer to the merged positions
    done = apply_edits(merged, [{"turn": 1, "word": 0, "action": "replace", "text": "Mmh"}])
    assert done.turns[1].words[0].text == " Mmh"


def test_the_digest_changes_with_inserts_only_when_there_are_some():
    assert edits_digest([], [], []) == EMPTY_DIGEST
    a = [{"id": 1, "at": 1, "speaker": "B", "start": 5.0, "end": 6.0, "text": "Mhm"}]
    assert edits_digest([], [], a) != EMPTY_DIGEST
    assert edits_digest([], [], a) != edits_digest([], [], [{**a[0], "text": "Mmh"}])


def test_everything_stored_for_later_turns_moves_with_an_insert(tmp_path):
    store = Store(tmp_path / "x.db")
    store.set_word_edits("I", [{"turn": n, "word": 0, "action": "replace", "kind": "correction",
                                "text": "x", "tag": ""} for n in range(4)])
    store.set_speakers("I", 2, {0: "B", 1: "B"})
    store.set_question("I", 2, 0, 3, "F1", "main", "confirmed", "manual")
    store.set_link("I", "F1", 3, 0, 2, "confirmed", "manual")
    store.add_extract("I", "F1", 3, 0, 1, "Kern")
    new = store.add_insert("I", 2, "A", 1.0, 2.0, "Mhm")
    assert sorted(e["turn"] for e in store.word_edits("I")) == [0, 1, 3, 4]
    assert {e["turn"] for e in store.speaker_edits("I")} == {3}
    assert [(q["turn"]) for q in store.question_marks("I")] == [3]
    assert store.links("I")[0]["turn"] == 4 and store.extracts(["I"])[0]["turn"] == 4
    assert store.inserts("I")[0]["at"] == 2
    second = store.add_insert("I", 0, "B", 0.0, 1.0, "Hallo")
    assert sorted(i["at"] for i in store.inserts("I")) == [0, 3]
    assert sorted(e["turn"] for e in store.word_edits("I")) == [1, 2, 4, 5]
    # taking one out removes what was marked inside it and moves the rest back
    store.delete_insert("I", new)
    assert sorted(e["turn"] for e in store.word_edits("I")) == [1, 2, 3, 4]
    assert {e["turn"] for e in store.speaker_edits("I")} == {3}
    assert [i["at"] for i in store.inserts("I")] == [0]
    store.delete_insert("I", second)
    assert sorted(e["turn"] for e in store.word_edits("I")) == [0, 1, 2, 3]  # as at the start
    assert {e["turn"] for e in store.speaker_edits("I")} == {2}
    assert store.question_marks("I")[0]["turn"] == 2 and store.links("I")[0]["turn"] == 3
    assert store.inserts("I") == []
    # what was marked inside a paragraph goes with it
    inner = store.add_insert("I", 1, "A", 1.0, 2.0, "Mhm")
    store.set_word_edits("I", [{"turn": 1, "word": 0, "action": "replace", "kind": "correction",
                                "text": "Mmh", "tag": ""}])
    assert store.turn_has_markings("I", 1)
    store.delete_insert("I", inner)
    assert sorted(e["turn"] for e in store.word_edits("I")) == [0, 1, 2, 3]  # its own is gone


def test_a_new_transcription_drops_the_inserts_because_their_places_are_gone(tmp_path):
    store = Store(tmp_path / "x.db")
    store.add_insert("I", 1, "A", 1.0, 2.0, "Mhm")
    store.delete_decisions("I")
    assert store.inserts("I") == []


# ------------------------------------------------------------------ website

def _body(**over):
    return {"at": 1, "speaker": "S0", "start": 2.0, "end": 3.5, "text": "Mhm genau", **over}


def test_insert_flow_over_the_api(client, data_dir):  # noqa: F811
    store = Store(data_dir.root / "interis.db")
    before = client.get("/api/interviews/T1").json()
    n = len(before["turns"])
    client.post("/api/interviews/T1/edits", headers=H, json={
        "turn": 2, "first": 0, "last": 0, "kind": "correction", "action": "replace",
        "text": "Anders"})
    r = client.post("/api/interviews/T1/inserts", json=_body(), headers=H)
    assert r.status_code == 200 and r.json()["at"] == 1
    d = client.get("/api/interviews/T1").json()
    assert len(d["turns"]) == n + 1 and d["turns"][1]["ins"] == r.json()["id"]
    assert [w["t"] for w in d["turns"][1]["words"]] == [" Mhm", " genau"]
    assert d["edits_stale"] is True
    assert d["turns"][3]["words"][0]["t"].strip() == "Anders"  # the correction moved along
    assert {(e["turn"], e["word"]) for e in d["edits"]} == {(3, 0)}
    assert "ins" not in d["turns"][0]

    # change speaker and time without touching the markings; a new text needs a confirmation
    iid = r.json()["id"]
    assert client.put(f"/api/interviews/T1/inserts/{iid}", headers=H,
                      json={"start": 2.5, "end": 4.0}).status_code == 200
    client.post("/api/interviews/T1/edits", headers=H, json={
        "turn": 1, "first": 0, "last": 0, "kind": "correction", "action": "replace",
        "text": "Mmh"})
    new_text = {"text": "Ja sicher"}
    assert client.put(f"/api/interviews/T1/inserts/{iid}", headers=H,
                      json=new_text).status_code == 409
    assert client.put(f"/api/interviews/T1/inserts/{iid}", headers=H,
                      json={**new_text, "force": True}).status_code == 200
    assert not any(e["turn"] == 1 for e in store.word_edits("T1"))
    assert client.delete(f"/api/interviews/T1/inserts/{iid}", headers=H).status_code == 200
    d = client.get("/api/interviews/T1").json()
    assert len(d["turns"]) == n and {(e["turn"], e["word"]) for e in d["edits"]} == {(2, 0)}


def test_inserts_are_validated(client):  # noqa: F811
    post = lambda **o: client.post("/api/interviews/T1/inserts", json=_body(**o), headers=H)  # noqa: E731
    assert post(speaker="NOBODY").status_code == 422
    assert post(start=3.0, end=2.0).status_code == 422
    assert post(start=0.0, end=5000.0).status_code == 422
    assert post(text="   ").status_code == 422
    assert post(text="x " * 401).status_code == 422
    assert post(at=99).status_code == 422
    assert client.put("/api/interviews/T1/inserts/99", json={}, headers=H).status_code == 404
    assert client.post("/api/interviews/T1/inserts", json=_body()).status_code == 403  # no header


def test_the_analysis_job_gets_the_inserts(client, data_dir):  # noqa: F811
    store = Store(data_dir.root / "interis.db")
    client.post("/api/interviews/T1/inserts", json=_body(), headers=H)
    job = {"id": 7, "interview_id": "T1"}
    runner = JobRunner(data_dir, store, lambda _i: None, lambda _i: "")
    out = data_dir.tmp / "edits.json"
    assert runner._write_edits(job, out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["inserts"][0]["text"] == "Mhm genau" and written["words"] == []
    from interis.cli import _load_edits

    assert _load_edits(str(out))[2][0]["speaker"] == "S0"


def test_a_new_transcription_asks_first_when_there_are_inserted_paragraphs(client, data_dir):  # noqa: F811
    client.post("/api/interviews/T1/inserts", json=_body(), headers=H)
    client.post("/api/interviews/T1/parts?ext=wav", content=b"RIFF0000", headers=H)
    r = client.post("/api/interviews/T1/transcribe", json={}, headers=H)
    assert r.status_code == 409 and "Markierungen" in r.json()["detail"]
