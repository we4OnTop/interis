// Typed access to the local Interis backend. Every request carries the custom header the
// backend requires for state changes (CSRF protection) and the session cookie.

export type Role = "interviewer" | "interviewee" | "unknown";
export type Match = "main" | "probe" | "followup" | null;
export type CellStatus = "asked" | "answered_elsewhere" | "omitted" | "explained" | "skipped" | "missing";
export type DecisionReason = "not_asked" | "not_relevant" | "other";
export type EditKind = "correction" | "smoothing";
export type LinkType = "anticipated" | "later" | "unasked";

export interface Project {
  id: number;
  name: string;
  hotwords: string;
  smoothing_tags?: string;
  created_at: string;
}

export interface ProjectSummary extends Project {
  interviews: number;
  transcribed: number;
  questions: number;
  active_jobs: number;
}

export interface Job {
  id: number;
  kind: "transcribe" | "analyze";
  interview_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  options: Partial<TranscriptionSettings> & { preset?: string };
  stage: string;
  progress: number;
  message: string;
  started_at: string | null;
  queue_pos: number | null;
}

export interface TranscriptionSettings {
  model: string;
  compute_type: "int8" | "float32";
  beam_size: number;
  room_mic: boolean;
  /** null: automatic (0.5, with room_mic 0.35) */
  vad_threshold: number | null;
  /** 0: detect the number */
  speakers: number;
  /** seconds; null: the model's setting */
  min_duration_off: number | null;
  /** reduce reverberation (WPE) */
  dereverb: boolean;
  wpe_taps: number;
  wpe_delay: number;
  wpe_iterations: number;
}

export interface Preset {
  id: number;
  name: string;
  options: TranscriptionSettings;
  is_default: boolean;
}

export interface SettingsInfo {
  builtin: TranscriptionSettings;
  presets: Preset[];
  models: string[];
  default: TranscriptionSettings & { preset: string };
}

export interface Trial {
  id: number;
  status: Job["status"];
  stage: string;
  progress: number;
  message: string;
  options: TranscriptionSettings & { interview: string; start: number; duration: number; label: string };
  started_at: string | null;
  elapsed_s: number | null;
  has_result: boolean;
}

export interface TrialResult {
  clip: { start_s: number; duration_s: number } | null;
  duration_s: number;
  speakers: { label: string; role: string }[];
  turns: { speaker: string | null; start: number; end: number; words: { text: string; start: number; prob: number }[] }[];
}

export interface Part {
  idx: number;
  ext: string;
  exists: boolean;
  size: number | null;
  uploaded: boolean;
  offset_s: number | null;
  duration_s: number | null;
}

export interface InterviewRow {
  id: string;
  transcribed: boolean;
  duration_s: number | null;
  parts: Part[];
  parts_changed: boolean;
  has_audio: boolean;
  has_roles: boolean;
  guide_mismatch: boolean;
  job: Job | null;
}

export interface GuideQuestion {
  code: string;
  text: string;
  section: string | null;
  variants: string[];
  probes: string[];
  tags: string[];
  hint: string;
  /** optional, Nebenfrage or Impuls: may be left out without a reason */
  droppable: boolean;
}

export interface Guide {
  title: string | null;
  questions: GuideQuestion[];
}

export interface ProjectDetail {
  project: Project;
  /** effective smoothing tags (defaults when the project has none) */
  tags: string[];
  guide: Guide | null;
  guide_text: string;
  guide_error: string | null;
  interviews: InterviewRow[];
  next_id: string;
  models: string[];
}

export interface AskedQuestion {
  id: string;
  turn: number;
  first: number;
  last: number;
  start: number;
  end: number;
  text: string;
  speaker: string | null;
  match: Match;
  guide_code: string | null;
  status: string;
}

export interface Piece {
  text: string;
  question?: boolean;
  code?: string | null;
  match?: Match;
  turn?: number;
  first?: number;
  last?: number;
  status?: string;
}

export interface DialogueTurn {
  turn: number;
  start: number;
  end: number;
  n_words: number;
  speaker: string;
  role: Role;
  pieces: Piece[];
}

export interface Exchange {
  question: AskedQuestion;
  start: number;
  dialogue: DialogueTurn[];
}

export interface Passage {
  turn: number;
  first: number;
  last: number;
  start: number;
  end: number;
  text: string;
  type: LinkType;
  from_code: string | null;
}

export interface Link extends Passage {
  id: number;
  guide_code: string;
  status: "confirmed" | "rejected";
  omitted: boolean;
  note: string;
}

export interface Suggestion extends Passage {
  score: number | null;
}

export interface Decision {
  reason: DecisionReason;
  note: string;
}

export interface Cell {
  status: CellStatus;
  exchanges: Exchange[];
  links: Link[];
  suggestions: Suggestion[];
  decision: Decision | null;
}

export interface Compare {
  guide: Guide | null;
  interviews: string[];
  cells: Record<string, Record<string, Cell>>;
  unassigned: Record<string, AskedQuestion[]>;
  /** per interview: the analysis predates its current edits */
  stale: Record<string, boolean>;
}

export interface Word {
  /** effective text (empty when deleted) */
  t: string;
  s: number;
  e: number;
  p: number;
  /** original text, only for edited words */
  o?: string;
  k?: EditKind;
  /** smoothing tag, only for smoothing edits */
  g?: string;
}

export interface Edit {
  turn: number;
  word: number;
  action: "replace" | "delete";
  kind: EditKind;
  text: string;
  tag: string;
}

export interface Turn {
  speaker: string | null;
  start: number;
  end: number;
  words: Word[];
}

export interface Speaker {
  label: string;
  role: Role;
  display_name: string;
  speaking_time_s: number;
}

export interface InterviewDetail {
  id: string;
  project: number;
  parts: { offset_s: number; duration_s: number }[];
  speakers: Speaker[];
  turns: Turn[];
  questions: AskedQuestion[];
  links: Link[];
  cells: Record<string, Cell>;
  reviewed: boolean;
  edits_stale: boolean;
  decisions: { guide_code: string; reason: DecisionReason; note: string }[];
  edits: Edit[];
}

export interface Extract {
  id: number;
  interview: string;
  guide_code: string;
  /** false when the guide no longer has this question code */
  in_guide: boolean;
  turn: number;
  first: number;
  last: number;
  start: number;
  end: number;
  /** effective passage text */
  text: string;
  paraphrase: string;
  updated_at: string;
}

export interface WorkflowStep {
  id: string;
  title: string;
  text: string;
}

export interface WorkflowInterview {
  id: string;
  transcribed: boolean;
  reviewed: boolean;
  corrections: number;
  smoothing: number;
  edits_stale: boolean;
  asked: number;
  answered_elsewhere: number;
  omitted: number;
  explained: number;
  missing: string[];
  unassigned: number;
  extracts: number;
  /** server rules for "done" per step; `assign` is informational only (no tick) */
  done: { transcribe: boolean; correct: boolean; smooth: boolean; assign: boolean; explain: boolean; extract: boolean };
}

export interface Workflow {
  guide_questions: number;
  steps: WorkflowStep[];
  interviews: WorkflowInterview[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

/** Error text from a response body: the backend's `detail` string, or FastAPI's validation list in German. */
function message(text: string, fallback: string): string {
  try {
    const d = JSON.parse(text).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d))
      return d
        .map((e: { loc?: unknown[]; type?: string; ctx?: { max_length?: number } }) => {
          const field = (e.loc ?? []).filter((p) => p !== "body").join(".");
          const why =
            e.type === "string_too_long"
              ? `zu lang (höchstens ${e.ctx?.max_length} Zeichen)`
              : e.type?.startsWith("missing")
                ? "fehlt"
                : "ungültig";
          return field ? `${field}: ${why}` : why;
        })
        .join("\n");
  } catch {
    /* not JSON: show the text itself */
  }
  return text || fallback;
}

async function detail(res: Response): Promise<string> {
  return message(await res.text(), res.statusText);
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Interis": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, "Nicht angemeldet");
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return (await res.json()) as T;
}

/** Raw file upload with progress (fetch cannot report upload progress). */
export function uploadFile(
  path: string,
  file: Blob,
  onProgress: (fraction: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Interis", "1");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(JSON.parse(xhr.responseText));
      reject(new ApiError(xhr.status, message(xhr.responseText, xhr.statusText)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Verbindung unterbrochen"));
    xhr.send(file);
  });
}

export async function postFile<T>(path: string, file: Blob): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Interis": "1", "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return (await res.json()) as T;
}

export const enc = encodeURIComponent;

export interface ModelState {
  key: string;
  label: string;
  size: string;
  repo: string;
  license: string;
  status: "ready" | "missing" | "outdated" | "incomplete";
}

export interface AppInfo {
  mode: "main" | "setup";
  portable: boolean;
  desktop: boolean;
  settings_file: string;
  data_dir: string | null;
  models_dir: string | null;
  models_linked: boolean;
  models: ModelState[] | null;
  models_job: Job | null;
  suggested_models_dir?: string | null;
}

export interface FolderCheck {
  path: string;
  exists: boolean;
  warning: string | null;
  has_interis?: boolean;
  models?: ModelState[];
  ready?: number;
}

declare global {
  interface Window {
    pywebview?: { api: { pick_folder: (start?: string) => Promise<string | null> } };
  }
}

/** Native folder dialog in the desktop app (null in a normal browser). */
export async function pickFolder(start?: string): Promise<string | null | undefined> {
  if (!window.pywebview?.api) return undefined;
  return window.pywebview.api.pick_folder(start ?? "");
}
