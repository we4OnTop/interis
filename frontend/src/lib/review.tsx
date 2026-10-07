import { createContext, useContext, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { api, type Guide, type Match } from "./api";
import { useFeedback } from "./feedback";

// The two review decisions, available everywhere a passage or question is shown:
//  * "this passage (also) answers guide question X" (optionally: X was left out because of it)
//  * "this question is guide question X / a planned probe / no question at all"

export interface Span {
  turn: number;
  first: number;
  last: number;
  text: string;
}

export interface QuestionRef extends Span {
  guide_code: string | null;
  match: Match;
  status?: string;
}

interface ReviewCtx {
  linkAnswer: (interview: string, span: Span, opts?: { defaultCode?: string | null; excludeCode?: string | null }) => void;
  editQuestion: (interview: string, q: QuestionRef) => void;
}

const Ctx = createContext<ReviewCtx | null>(null);

const NONE = "__none__";

type Open =
  | { kind: "link"; interview: string; span: Span; code: string; exclude: string | null; omitted: boolean; note: string }
  | { kind: "question"; interview: string; q: QuestionRef; code: string; probe: boolean };

export function ReviewProvider({ guide, onChanged, children }: { guide: Guide | null; onChanged: () => void; children: ReactNode }) {
  const { notify, fail } = useFeedback();
  const [open, setOpen] = useState<Open | null>(null);
  const questions = guide?.questions ?? [];

  const save = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      setOpen(null);
      notify(msg);
      onChanged();
    } catch (e) {
      fail(e);
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
                  disabled={!open.code}
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
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  );
}

export const useReview = () => useContext(Ctx)!;
