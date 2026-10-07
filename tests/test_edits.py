import sqlite3

from interis.pipeline.types import Transcript, Turn, Word
from interis.web.edits import (
    DEFAULT_TAGS,
    EMPTY_DIGEST,
    apply_edits,
    edits_digest,
    parse_tags,
    project_tags,
)
from interis.web.store import Store


def _transcript() -> Transcript:
    words = [Word(" Ich", 0.0, 0.2, 0.9), Word(" äh", 0.2, 0.4, 0.3),
             Word(" arbeite", 0.4, 0.8, 0.95), Word(" bei", 0.8, 0.9, 0.95)]
    return Transcript(meta={"interview_id": "T1"}, speakers=[],
                      turns=[Turn("SPEAKER_00", 0.0, 0.9, words)], analysis={"x": 1})


def test_replace_keeps_the_whisper_leading_space_and_timing():
    t = apply_edits(_transcript(), [{"turn": 0, "word": 2, "action": "replace",
                                     "text": "  arbeiten "}])
    w = t.turns[0].words[2]
    assert w.text == " arbeiten"
    assert (w.start, w.end, w.prob) == (0.4, 0.8, 0.95)


def test_delete_keeps_the_word_so_positions_stay_valid():
    t = apply_edits(_transcript(), [{"turn": 0, "word": 1, "action": "delete", "text": ""}])
    assert [w.text for w in t.turns[0].words] == [" Ich", "", " arbeite", " bei"]
    assert t.turns[0].text == "Ich arbeite bei"


def test_input_transcript_is_not_modified():
    original = _transcript()
    apply_edits(original, [{"turn": 0, "word": 1, "action": "delete", "text": ""}])
    assert original.turns[0].words[1].text == " äh"
    assert original.analysis == {"x": 1}


def test_edits_outside_the_transcript_are_ignored():
    t = apply_edits(_transcript(), [{"turn": 5, "word": 0, "action": "delete", "text": ""},
                                    {"turn": 0, "word": 99, "action": "delete", "text": ""}])
    assert t.turns[0].text == "Ich äh arbeite bei"


def test_digest_is_order_independent_and_empty_has_a_constant_value():
    a = {"turn": 0, "word": 1, "action": "delete", "text": "", "kind": "smoothing", "tag": "x"}
    b = {"turn": 0, "word": 2, "action": "replace", "text": "y", "kind": "correction"}
    assert edits_digest([a, b]) == edits_digest([b, a])
    assert edits_digest([]) == EMPTY_DIGEST
    assert edits_digest([a]) != edits_digest([b])


def test_tags_are_trimmed_deduplicated_and_default_when_empty():
    assert parse_tags(" Füllwort \n\nGrammatik\nFüllwort\n  ") == ["Füllwort", "Grammatik"]
    assert project_tags("") == list(DEFAULT_TAGS)
    assert project_tags("A\nB") == ["A", "B"]


def test_store_roundtrip_and_interview_delete_removes_everything(tmp_path):
    store = Store(tmp_path / "interis.db")
    pid = store.create_project("P")
    store.add_interview("T1", pid)
    store.set_word_edits("T1", [{"turn": 0, "word": 1, "action": "delete", "kind": "smoothing",
                                 "text": "", "tag": "Füllwort"}])
    store.add_extract("T1", "F1", 0, 0, 2, "Arbeitet viel.")
    store.set_decision("T1", "F2", "not_asked", "Zeitmangel")
    store.set_reviewed("T1", True)
    assert store.reviewed("T1")
    assert store.word_edits("T1")[0]["tag"] == "Füllwort"
    assert store.extracts(["T1"])[0]["paraphrase"] == "Arbeitet viel."
    assert store.decisions("T1")[0]["note"] == "Zeitmangel"

    store.delete_decisions("T1")
    assert store.word_edits("T1") == [] and store.extracts(["T1"]) == []
    assert store.decisions("T1") == [] and not store.reviewed("T1")

    store.set_word_edits("T1", [{"turn": 0, "word": 0, "action": "delete", "kind": "correction",
                                 "text": "", "tag": ""}])
    store.delete_interview("T1")
    assert store.word_edits("T1") == [] and store.interview_ids() == set()


def test_old_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "interis.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            hotwords TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE interviews (id TEXT PRIMARY KEY, audio_path TEXT, added_at TEXT NOT NULL,
            project_id INTEGER REFERENCES projects(id));
        INSERT INTO projects (name, created_at) VALUES ('alt', '2026-01-01');
    """)
    con.commit()
    con.close()
    store = Store(path)  # must not fail on the older layout
    assert store.project(1)["smoothing_tags"] == ""
    store.update_project(1, None, None, smoothing_tags="A\nB")
    assert store.project(1)["smoothing_tags"] == "A\nB"
