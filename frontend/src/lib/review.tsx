import { createContext, useContext, useState, type DragEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { api, enc, type Decision, type DecisionReason, type Guide, type Match } from "./api";
import { useFeedback } from "./feedback";
import { REASON_LABEL } from "./format";

// The two review decisions, available everywhere a passage or question is shown:
//  * "this passage (also) answers guide question X" (optionally: X was left out because of it)
//  * "this question is guide question X / a planned probe / no question at all"

export interface Span {
  turn: number;
  first: number;
  last: number;
  text: string;
}

// Drag and drop in the side-by-side view is an accelerator only: every drop has a dialog path.
// The payload carries the interview, so a drop can only ever touch the interview it came from.
export const DRAG_TYPE = "application/x-interis";

export type DragPayload = { kind: "question" | "answer"; interview: string; turn: number; first: number; last: number };

export function dragStart(e: DragEvent, payload: DragPayload) {
  e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(payload));
  // the kind also travels as a type of its own: during dragover the data cannot be read, only the types
  e.dataTransfer.setData(`${DRAG_TYPE}-${payload.kind}`, "1");
  e.dataTransfer.effectAllowed = "copy";
}

/** The payload of a drag, or null when the drag is not from this app (or malformed). */
export function readDrag(e: DragEvent): DragPayload | null {
  if (!e.dataTransfer.types.includes(DRAG_TYPE)) return null;
  try {
    const p = JSON.parse(e.dataTransfer.getData(DRAG_TYPE)) as DragPayload;
    const ok =
      (p.kind === "question" || p.kind === "answer") &&
      typeof p.interview === "string" &&
      [p.turn, p.first, p.last].every((n) => Number.isInteger(n) && n >= 0);
    return ok ? p : null;
  } catch {
    return null;
  }
}

export interface QuestionRef extends Span {
  guide_code: string | null;
  match: Match;
  status?: string;
}

interface ReviewCtx {
  linkAnswer: (interview: string, span: Span, opts?: { defaultCode?: string | null; excludeCode?: string | null }) => void;
  editQuestion: (interview: string, q: QuestionRef) => void;
  /** why guide question `code` was not asked */
  decide: (interview: string, code: string, decision: Decision | null) => void;
  /** new extract (Kernaussage) for a passage */
  extract: (interview: string, span: Span, defaultCode?: string | null) => void;
}

const Ctx = createContext<ReviewCtx | null>(null);

const NONE = "__none__";

type Open =
  | { kind: "link"; interview: string; span: Span; code: string; exclude: string | null; omitted: boolean; note: string }
  | { kind: "question"; interview: string; q: QuestionRef; code: string; probe: boolean }
  | { kind: "decision"; interview: string; code: string; text: string; reason: DecisionReason | null; note: string; had: boolean }
  | { kind: "extract"; interview: string; span: Span; code: string; paraphrase: string };

export function ReviewProvider({ guide, onChanged, children }: { guide: Guide | null; onChanged: () => void; children: ReactNode }) {
  const { notify, fail } = useFeedback();
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const questions = guide?.questions ?? [];

  // one request at a time: the buttons are disabled while busy, the guard covers a fast second click
  const save = async (fn: () => Promise<unknown>, msg: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      setOpen(null);
      notify(msg);
      onChanged();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const value: ReviewCtx = {
    linkAnswer: (interview, span, opts) =>
      setOpen({
        kind: "link",
        interview,
        span,
        code: opts?.defaultCode ?? questions.find((q) => q.code !== opts?.excludeCode)?.code ?? "",
        exclude: opts?.excludeCode ?? null,
        omitted: false,
        note: "",
      }),
    editQuestion: (interview, q) =>
      setOpen({ kind: "question", interview, q, code: q.guide_code ?? NONE, probe: q.match === "probe" }),
    decide: (interview, code, decision) =>
      setOpen({
        kind: "decision",
        interview,
        code,
        text: questions.find((q) => q.code === code)?.text ?? "",
        reason: decision?.reason ?? null,
        note: decision?.note ?? "",
        had: decision !== null,
      }),
    extract: (interview, span, defaultCode) => setOpen({ kind: "extract", interview, span, code: defaultCode ?? "", paraphrase: "" }),
  };

  const guideSelect = (valueCode: string, onChange: (v: string) => void, opts: { allowNone?: boolean; exclude?: string | null }) => (
    <Select value={valueCode} onValueChange={onChange}>
      <SelectTrigger className="w-full">
        <SelectValue placeholder="Leitfadenfrage wählen" />
      </SelectTrigger>
      <SelectContent className="max-w-[min(42rem,calc(100vw-4rem))]">
        {opts.allowNone && <SelectItem value={NONE}>— keine Leitfadenfrage (spontane Nachfrage) —</SelectItem>}
        {questions
          .filter((q) => q.code !== opts.exclude)
          .map((q) => (
            <SelectItem key={q.code} value={q.code}>
              <span className="text-question font-semibold">{q.code}</span>
              <span className="truncate">{q.text}</span>
            </SelectItem>
          ))}
      </SelectContent>
    </Select>
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="sm:max-w-2xl">
          {open?.kind === "link" && (
            <>
              <DialogHeader>
                <DialogTitle>Diese Stelle beantwortet (auch) …</DialogTitle>
                <DialogDescription>Die Verknüpfung erscheint in der Übersicht bei der gewählten Frage.</DialogDescription>
              </DialogHeader>
              <blockquote className="bg-muted max-h-40 overflow-auto rounded-md border-l-4 px-3 py-2 text-sm">{open.span.text}</blockquote>
              {guideSelect(open.code, (code) => setOpen({ ...open, code }), { exclude: open.exclude })}
              <div className="flex items-start gap-2">
                <Checkbox id="omitted" checked={open.omitted} onCheckedChange={(c) => setOpen({ ...open, omitted: c === true })} />
                <div className="grid gap-1">
                  <Label htmlFor="omitted">Diese Frage habe ich deshalb weggelassen</Label>
                  <p className="text-muted-foreground text-xs">Nur ankreuzen, wenn die Frage in diesem Interview nicht gestellt wurde.</p>
                </div>
              </div>
              <Textarea placeholder="Notiz (optional)" value={open.note} onChange={(e) => setOpen({ ...open, note: e.target.value })} />
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(null)}>
                  Abbrechen
                </Button>
                <Button
                  disabled={!open.code || busy}
                  onClick={() =>
                    save(
                      () =>
                        api("POST", "/api/links", {
                          interview: open.interview,
                          turn: open.span.turn,
                          first: open.span.first,
                          last: open.span.last,
                          guide_code: open.code,
                          omitted: open.omitted,
                          note: open.note,
                        }),
                      "Verknüpfung gespeichert",
                    )
                  }
                >
                  Speichern
                </Button>
              </DialogFooter>
            </>
          )}
          {open?.kind === "question" && (
            <>
              <DialogHeader>
                <DialogTitle>Frage zuordnen</DialogTitle>
                <DialogDescription>Welche Leitfadenfrage ist das – auch wenn du sie anders formuliert hast?</DialogDescription>
              </DialogHeader>
              <blockquote className="bg-question-soft max-h-40 overflow-auto rounded-md border-l-4 border-l-question px-3 py-2 text-sm">
                {open.q.text}
              </blockquote>
              {guideSelect(open.code, (code) => setOpen({ ...open, code }), { allowNone: true })}
              {open.code !== NONE && (
                <div className="flex gap-6 text-sm">
                  <label className="flex cursor-pointer items-center gap-2">
                    <input type="radio" checked={!open.probe} onChange={() => setOpen({ ...open, probe: false })} /> Leitfadenfrage
                  </label>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input type="radio" checked={open.probe} onChange={() => setOpen({ ...open, probe: true })} /> geplante Nachfrage dazu
                  </label>
                </div>
              )}
              <DialogFooter className="sm:justify-between">
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      save(
                        () =>
                          api("POST", "/api/questions", {
                            interview: open.interview,
                            turn: open.q.turn,
                            first: open.q.first,
                            last: open.q.last,
                            guide_code: null,
                            match: "followup",
                            status: "rejected",
                          }),
                        "Als „keine Frage“ markiert",
                      )
                    }
                  >
                    Ist keine Frage
                  </Button>
                  {open.q.status === "confirmed" && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() =>
                        save(
                          () => api("POST", "/api/questions/reset", { interview: open.interview, turn: open.q.turn, first: open.q.first }),
                          "Automatische Erkennung wiederhergestellt",
                        )
                      }
                    >
                      Zurücksetzen
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setOpen(null)}>
                    Abbrechen
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() => {
                      const code = open.code === NONE ? null : open.code;
                      void save(
                        () =>
                          api("POST", "/api/questions", {
                            interview: open.interview,
                            turn: open.q.turn,
                            first: open.q.first,
                            last: open.q.last,
                            guide_code: code,
                            match: code ? (open.probe ? "probe" : "main") : "followup",
                            status: "confirmed",
                          }),
                        "Frage gespeichert",
                      );
                    }}
                  >
                    Speichern
                  </Button>
                </div>
              </DialogFooter>
            </>
          )}
          {open?.kind === "decision" && (
            <>
              <DialogHeader>
                <DialogTitle>Warum wurde diese Frage nicht gestellt?</DialogTitle>
                <DialogDescription>
                  <span className="text-question font-semibold">{open.code}</span> {open.text}
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-2 text-sm">
                {(Object.keys(REASON_LABEL) as DecisionReason[]).map((r) => (
                  <label key={r} className="flex cursor-pointer items-center gap-2">
                    <input type="radio" name="reason" checked={open.reason === r} onChange={() => setOpen({ ...open, reason: r })} />
                    {REASON_LABEL[r]}
                  </label>
                ))}
              </div>
              <Textarea placeholder="Notiz (optional)" maxLength={2000} value={open.note} onChange={(e) => setOpen({ ...open, note: e.target.value })} />
              <DialogFooter className="sm:justify-between">
                <div>
                  {open.had && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() =>
                        save(
                          () => api("PUT", `/api/interviews/${enc(open.interview)}/questions/${enc(open.code)}/decision`, { reason: null, note: "" }),
                          "Begründung entfernt",
                        )
                      }
                    >
                      Begründung entfernen
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setOpen(null)}>
                    Abbrechen
                  </Button>
                  <Button
                    disabled={!open.reason || busy}
                    onClick={() =>
                      save(
                        () =>
                          api("PUT", `/api/interviews/${enc(open.interview)}/questions/${enc(open.code)}/decision`, {
                            reason: open.reason,
                            note: open.note,
                          }),
                        "Begründung gespeichert",
                      )
                    }
                  >
                    Speichern
                  </Button>
                </div>
              </DialogFooter>
            </>
          )}
          {open?.kind === "extract" && (
            <>
              <DialogHeader>
                <DialogTitle>Extrakt anlegen</DialogTitle>
                <DialogDescription>Die Kernaussage in eigenen Worten. Das Zitat bleibt unverändert im Transkript.</DialogDescription>
              </DialogHeader>
              <blockquote className="bg-muted max-h-40 overflow-auto rounded-md border-l-4 px-3 py-2 text-sm">{open.span.text}</blockquote>
              {guideSelect(open.code, (code) => setOpen({ ...open, code }), {})}
              <div className="grid gap-2">
                <Label htmlFor="paraphrase">Kernaussage (in eigenen Worten)</Label>
                <Textarea id="paraphrase" maxLength={2000} value={open.paraphrase} onChange={(e) => setOpen({ ...open, paraphrase: e.target.value })} />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(null)}>
                  Abbrechen
                </Button>
                <Button
                  disabled={!open.code || !open.paraphrase.trim() || busy}
                  onClick={() =>
                    save(
                      () =>
                        api("POST", "/api/extracts", {
                          interview: open.interview,
                          turn: open.span.turn,
                          first: open.span.first,
                          last: open.span.last,
                          guide_code: open.code,
                          paraphrase: open.paraphrase,
                        }),
                      "Extrakt gespeichert",
                    )
                  }
                >
                  Speichern
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  );
}

export const useReview = () => useContext(Ctx)!;
