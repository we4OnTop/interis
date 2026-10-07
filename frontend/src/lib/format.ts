import type { CellStatus, DecisionReason, LinkType, Match } from "./api";

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export interface TimelinePart {
  offset_s: number | null;
  duration_s?: number | null;
}

/** Which recording a time on the joint timeline belongs to, and the time within it. */
export function partAt(parts: TimelinePart[] | undefined, t: number): { part: number; local: number } {
  let part = 0;
  (parts || []).forEach((p, i) => {
    if (p.offset_s !== null && p.offset_s <= t + 1e-6) part = i;
  });
  const offset = parts?.[part]?.offset_s ?? 0;
  return { part, local: Math.max(0, t - offset) };
}

/** "03:15" – or "T2 · 03:15" when the interview consists of several recordings. */
export function stamp(parts: TimelinePart[] | undefined, t: number): string {
  if (!parts || parts.length < 2) return clock(t);
  const { part, local } = partAt(parts, t);
  return `T${part + 1} · ${clock(local)}`;
}

export function bytes(n: number | null): string {
  if (n === null) return "–";
  if (n < 1024 ** 2) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export const STATUS_LABEL: Record<CellStatus, string> = {
  asked: "gestellt",
  answered_elsewhere: "anderswo beantwortet",
  omitted: "weggelassen – schon beantwortet",
  explained: "nicht gestellt – begründet",
  missing: "fehlt – begründen",
};

export const STATUS_SHORT: Record<CellStatus, string> = {
  asked: "gestellt",
  answered_elsewhere: "anderswo",
  omitted: "weggelassen",
  explained: "begründet",
  missing: "fehlt",
};

export const REASON_LABEL: Record<DecisionReason, string> = {
  not_asked: "Nicht gestellt",
  not_relevant: "Nicht relevant für diese Person",
  other: "Sonstiges",
};

export const LINK_LABEL: Record<LinkType, string> = {
  anticipated: "vorweg beantwortet",
  later: "später nochmal",
  unasked: "ohne Frage beantwortet",
};

export function tagText(code: string | null | undefined, match: Match | undefined): string {
  if (match === "main" && code) return code;
  if (match === "probe" && code) return `${code} Nachfrage`;
  return "Nachfrage";
}

export const STAGES = ["hash", "decode", "transcribe", "align", "diarize", "analyze"] as const;
export const STAGE_LABEL: Record<string, string> = {
  start: "Start, Modelle laden",
  hash: "Dateien prüfen",
  decode: "Audio lesen",
  transcribe: "Spracherkennung",
  align: "Wörter ausrichten",
  diarize: "Sprechertrennung",
  analyze: "Fragen erkennen",
};

export const MODEL_LABEL: Record<string, string> = {
  "whisper-large-v3": "Genau (large-v3, empfohlen)",
  "whisper-large-v3-turbo": "Schneller Entwurf (large-v3-turbo)",
};
