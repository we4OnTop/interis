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

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "speakers": self.speakers,
            "turns": [{**asdict(t), "text": t.text} for t in self.turns],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Transcript:
        turns = [
            Turn(t["speaker"], t["start"], t["end"], [Word(**w) for w in t["words"]])
            for t in d["turns"]
        ]
        return Transcript(meta=d["meta"], speakers=d["speakers"], turns=turns)


def to_dict(obj: Any) -> Any:
    return asdict(obj)
