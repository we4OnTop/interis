"""Plain data types shared by the pipeline steps. All are JSON-serialisable via
``to_dict`` / ``from_dict`` so every step result can be cached and exported losslessly."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Word:
    text: str  # raw Whisper token text, including its leading space
    start: float
    end: float
    prob: float
    # Whisper's own timestamps are kept when alignment refines start/end.
    asr_start: float | None = None
    asr_end: float | None = None
    aligned: bool = False
    speaker: str | None = None
    overlap: bool = False  # another speaker talks at the same time


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word]
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    temperature: float

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Segment:
        return Segment(**{**d, "words": [Word(**w) for w in d["words"]]})


@dataclass
class SpeakerSpan:
    start: float
    end: float
    speaker: str


@dataclass
class Diarization:
    regular: list[SpeakerSpan]
    exclusive: list[SpeakerSpan]
    embeddings: dict[str, list[float]] = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Diarization:
        return Diarization(
            regular=[SpeakerSpan(**s) for s in d["regular"]],
            exclusive=[SpeakerSpan(**s) for s in d["exclusive"]],
            embeddings=d.get("embeddings", {}),
        )


@dataclass
class Turn:
    speaker: str | None
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words).strip()


@dataclass
class Transcript:
    meta: dict[str, Any]
    speakers: list[dict[str, Any]]
    turns: list[Turn]
    # Phase 2 results: roles, questions, guide matches, answers, suggestions.
    analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "speakers": self.speakers,
            "turns": [{**asdict(t), "text": t.text} for t in self.turns],
            "analysis": self.analysis,
        }

    @property
    def parts(self) -> list[dict[str, Any]]:
        """Recording parts with their offset on the joint timeline (one for most)."""
        return self.meta.get("audio", {}).get("parts") or [
            {"offset_s": 0.0, "duration_s": self.meta.get("audio", {}).get("duration_s", 0)}]

    def part_at(self, t: float) -> tuple[int, float]:
        """(part index, time within that recording) for a time on the joint timeline."""
        index = 0
        for i, p in enumerate(self.parts):
            if p["offset_s"] <= t + 1e-6:
                index = i
        return index, max(0.0, t - self.parts[index]["offset_s"])

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Transcript:
        turns = [
            Turn(t["speaker"], t["start"], t["end"], [Word(**w) for w in t["words"]])
            for t in d["turns"]
        ]
        return Transcript(meta=d["meta"], speakers=d["speakers"], turns=turns,
                          analysis=d.get("analysis", {}))


def to_dict(obj: Any) -> Any:
    return asdict(obj)
