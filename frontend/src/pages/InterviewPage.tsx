import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CornerUpRightIcon,
  EraserIcon,
  LoaderIcon,
  MessageCircleQuestionIcon,
  PencilIcon,
  QuoteIcon,
  RefreshCwIcon,
  Undo2Icon,
  UserRoundIcon,
} from "lucide-react";

import { LoadError } from "@/components/LoadError";
import { StatusDot } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, enc, type AskedQuestion, type EditKind, type InterviewDetail, type Link, type Speaker, type Turn, type Word } from "@/lib/api";
import { useStoredFlag } from "@/lib/compare";
import { useFeedback } from "@/lib/feedback";
import { clock, partAt, STATUS_LABEL, stamp, tagText } from "@/lib/format";
import { usePlayer, usePlayerState } from "@/lib/player";
import { useProject } from "@/lib/project";
import { ReviewProvider, useReview, type Span } from "@/lib/review";
import { href } from "@/lib/router";
import { cn } from "@/lib/utils";

export function InterviewPage({ id, focusTurn }: { id: string; focusTurn: number | null }) {
  const { detail, dataVersion } = useProject();
  const { fail } = useFeedback();
  const [d, setD] = useState<InterviewDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api<InterviewDetail>("GET", `/api/interviews/${enc(id)}`));
      setError(null);
    } catch (e) {
      fail(e);
      setError(e instanceof Error ? e.message : String(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  if (!d)
    return error ? <LoadError message={error} onRetry={() => void load()} /> : <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  return (
    <ReviewProvider guide={detail!.guide} onChanged={load}>
      <Transcript d={d} focusTurn={focusTurn} onChanged={load} />
    </ReviewProvider>
  );
}

const ROLE_LABEL: Record<string, string> = { interviewer: "Interviewer", interviewee: "Befragte:r", unknown: "unbekannt" };

/**
 * The words one edit dialog created: the word at `first`..`last`, widened to whole edit groups. A group is a
 * replacement word followed by the words it deleted, with the same kind and tag. Edits store no group id, so
 * the run is found from the words alone.
 */
function widenToEditGroups(words: Word[], first: number, last: number): [number, number] {
  let a = first;
  let b = last;
  for (let i = first; i <= last; i++) {
    const w = words[i];
    if (w.k === undefined) continue;
    const same = (x: Word | undefined) => x !== undefined && x.k === w.k && x.g === w.g;
    let s = i;
    while (words[s].t === "" && same(words[s - 1])) s--;
    let e = i;
    while (e + 1 < words.length && words[e + 1].t === "" && same(words[e + 1])) e++;
    a = Math.min(a, s);
    b = Math.max(b, e);
  }
  return [a, b];
}

type Mode = "read" | "correct" | "smooth";
const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "read", label: "Lesen", hint: "Auf ein Wort klicken → ab dort anhören." },
  {
    id: "correct",
    label: "Korrigieren",
    hint: "Falsch erkannte Wörter anklicken oder markieren und ersetzen. Falscher Sprecher: Wörter markieren oder auf den Sprechernamen klicken, dann den richtigen Sprecher wählen.",
  },
  { id: "smooth", label: "Glätten", hint: "Füllwörter, Wiederholungen und Abbrüche markieren, entfernen oder ersetzen – mit Grund." },
];

/** An edit being prepared in the dialog. Spans are word indices, which never move. */
interface EditDraft {
  span: Span;
  original: string;
  /** leading whitespace of the first word: words carry their own space, so a replacement keeps it */
  lead: string;
  action: "replace" | "delete";
  kind: EditKind;
  text: string;
  tag: string;
  hasEdits: boolean;
}

function Transcript({ d, focusTurn, onChanged }: { d: InterviewDetail; focusTurn: number | null; onChanged: () => void }) {
  const { detail, source, dataVersion } = useProject();
  const review = useReview();
  const { confirm, fail, notify } = useFeedback();
  const player = usePlayer();
  const ps = usePlayerState();
  const pid = detail!.project.id;
  const container = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<{ span: Span; x: number; y: number } | null>(null);
  const [mode, setMode] = useState<Mode>("read");
  const [showEdits, setShowEdits] = useStoredFlag("interis.showEdits", false);
  const [edit, setEdit] = useState<EditDraft | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const speakers = useMemo(() => Object.fromEntries(d.speakers.map((s) => [s.label, s])), [d.speakers]);

  // the transcript changed under the open dialog (a job finished): its word positions may have moved
  useEffect(() => {
    setEdit(null);
  }, [dataVersion]);

  // questions and confirmed links per turn
  const qByTurn = useMemo(() => group(d.questions, (q) => q.turn), [d.questions]);
  const lByTurn = useMemo(() => group(d.links.filter((l) => l.status === "confirmed"), (l) => l.turn), [d.links]);

  const playingTurn = ps.id === d.id ? lastIndexWhere(d.turns, (t) => t.start <= ps.time + 0.05) : -1;

  useEffect(() => {
    if (focusTurn === null) return;
    const el = document.getElementById(`t-${focusTurn}`);
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.classList.add("turn-flash");
    }
  }, [focusTurn, d.id]);

  // text selection -> floating actions
  useEffect(() => {
    const onUp = () =>
      setTimeout(() => {
        const s = window.getSelection();
        if (!s || s.isCollapsed || !s.rangeCount || !container.current?.contains(s.anchorNode)) return;
        const wordOf = (n: Node | null) => (n?.nodeType === 3 ? n.parentElement : (n as HTMLElement | null))?.closest<HTMLElement>("[data-wi]");
        const a = wordOf(s.anchorNode);
        const b = wordOf(s.focusNode);
        if (!a || !b) return;
        if (a.dataset.ti !== b.dataset.ti) {
          fail("Bitte nur innerhalb eines Sprecherbeitrags markieren.");
          return;
        }
        const turn = Number(a.dataset.ti);
        let first = Number(a.dataset.wi);
        let last = Number(b.dataset.wi);
        if (first > last) [first, last] = [last, first];
        const text = d.turns[turn].words
          .slice(first, last + 1)
          .map((w) => w.t)
          .join("")
          .trim();
        // only deleted words selected: nothing visible to act on
        if (!text) {
          setSel(null);
          return;
        }
        const r = s.getRangeAt(0).getBoundingClientRect();
        setSel({ span: { turn, first, last, text }, x: r.left, y: r.top });
      }, 0);
    const onDown = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-selbar]")) setSel(null);
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("mousedown", onDown);
    };
  }, [d.turns, fail]);

  // The dialog always works on whole edit groups: a word that already has an edit opens the group it belongs to.
  const openEdit = useCallback(
    (span: Span, action: "replace" | "delete", kind: EditKind) => {
      const words = d.turns[span.turn].words;
      const [first, last] = widenToEditGroups(words, span.first, span.last);
      const group = words.slice(first, last + 1);
      const current = group
        .map((w) => w.t)
        .join("")
        .trim();
      setEditError(null);
      setEdit({
        span: { turn: span.turn, first, last, text: current },
        original: group
          .map((w) => w.o ?? w.t)
          .join("")
          .trim(),
        lead: (group[0]?.o ?? group[0]?.t ?? "").match(/^\s*/)?.[0] ?? "",
        action,
        kind,
        text: action === "replace" ? current : "",
        tag: "",
        hasEdits: group.some((w) => w.k !== undefined),
      });
    },
    [d],
  );

  const onWordClick = useCallback(
    (ti: number, wi: number) => {
      if (window.getSelection()?.isCollapsed === false) return;
      if (mode === "correct") openEdit({ turn: ti, first: wi, last: wi, text: "" }, "replace", "correction");
      else player.play(source(d.id), d.turns[ti].words[wi].s + 0.15);
    },
    [mode, d, openEdit, player, source],
  );

  const setSpeaker = async (span: Span, speaker: string | null) => {
    try {
      await api("POST", `/api/interviews/${enc(d.id)}/speakers`, { turn: span.turn, first: span.first, last: span.last, speaker });
      notify(speaker ? `Sprecher geändert – „Analyse aktualisieren“ übernimmt es in die Fragen-Erkennung` : "Sprecher zurückgesetzt");
      onChanged();
    } catch (e) {
      fail(e);
    }
  };

  const onSpeakerClick = useCallback(
    (ti: number, x: number, y: number) => {
      const words = d.turns[ti].words;
      const text = words
        .map((w) => w.t)
        .join("")
        .trim();
      setSel({ span: { turn: ti, first: 0, last: words.length - 1, text }, x, y });
    },
    [d],
  );

  const saveEdit = async () => {
    if (!edit || busy) return;
    const { span, action, kind, text, tag, lead } = edit;
    setBusy(true);
    setEditError(null);
    try {
      await api("POST", `/api/interviews/${enc(d.id)}/edits`, {
        turn: span.turn,
        first: span.first,
        last: span.last,
        action,
        kind,
        text: action === "replace" ? lead + text.trim() : "",
        tag: kind === "smoothing" ? tag : "",
      });
      setEdit(null);
      notify("Änderung gespeichert");
      onChanged();
    } catch (e) {
      // the backend's message (for example the 409 for a word that already has another kind of edit) stays in the dialog
      setEditError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const revertEdit = async () => {
    if (!edit || busy) return;
    setBusy(true);
    setEditError(null);
    try {
      await api("POST", `/api/interviews/${enc(d.id)}/edits/revert`, { turn: edit.span.turn, first: edit.span.first, last: edit.span.last });
      setEdit(null);
      notify("Änderung zurückgenommen");
      onChanged();
    } catch (e) {
      setEditError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const setReviewed = async (reviewed: boolean) => {
    try {
      await api("PUT", `/api/interviews/${enc(d.id)}/reviewed`, { reviewed });
      onChanged();
    } catch (e) {
      fail(e);
    }
  };

  const analyze = async () => {
    try {
      const r = await api<{ queued: number }>("POST", `/api/interviews/${enc(d.id)}/analyze`);
      notify(r.queued ? "Analyse eingeplant" : "Analyse läuft bereits");
      onChanged();
    } catch (e) {
      fail(e);
    }
  };

  const deleteLink = useCallback(
    async (lk: Link) => {
      const ok = await confirm({ title: `Verknüpfung mit ${lk.guide_code} löschen?`, confirm: "Löschen", destructive: true });
      if (!ok) return;
      try {
        await api("DELETE", `/api/links/${lk.id}`);
        notify("Gelöscht");
        onChanged();
      } catch (e) {
        fail(e);
      }
    },
    [confirm, fail, notify, onChanged],
  );

  const guide = detail!.guide?.questions ?? [];
  const multi = d.parts.length > 1;

  return (
    <div className="mx-auto flex max-w-7xl gap-6 p-4 sm:p-6 pb-28">
      <div className="min-w-0 flex-1 space-y-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="font-mono text-2xl font-semibold">{d.id}</h1>
          <span className="text-muted-foreground text-sm">
            {clock(d.parts.reduce((s, p) => Math.max(s, p.offset_s + p.duration_s), 0))}
            {multi && ` · ${d.parts.length} Teile`}
          </span>
          <div className="flex flex-wrap gap-2">
            {d.speakers.map((s: Speaker) => (
              <Badge key={s.label} variant={s.role === "interviewer" ? "question" : "secondary"}>
                {[s.display_name || s.label, ROLE_LABEL[s.role] ?? s.role]
                  .filter((x, i, all) => all.indexOf(x) === i)
                  .join(" · ")}{" "}
                · {clock(s.speaking_time_s)}
              </Badge>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="bg-muted inline-flex gap-0.5 rounded-lg p-0.5" role="group" aria-label="Bearbeitungsmodus">
              {MODES.map((m) => (
                <Button
                  key={m.id}
                  size="sm"
                  variant={mode === m.id ? "secondary" : "ghost"}
                  aria-pressed={mode === m.id}
                  onClick={() => setMode(m.id)}
                >
                  {m.label}
                </Button>
              ))}
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-sm">
              <Checkbox checked={showEdits} onCheckedChange={(c) => setShowEdits(c === true)} />
              Änderungen anzeigen
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-sm">
              <Checkbox checked={d.reviewed} onCheckedChange={(c) => void setReviewed(c === true)} />
              Korrektur abgeschlossen
            </label>
            {d.edits_stale && <Badge variant="suggest">Analyse veraltet</Badge>}
            {d.edits_stale && (
              <Button size="sm" variant="outline" onClick={() => void analyze()}>
                <RefreshCwIcon />
                Analyse aktualisieren
              </Button>
            )}
          </div>
          <p className="text-muted-foreground text-xs">{MODES.find((m) => m.id === mode)?.hint}</p>
        </div>

        <div ref={container} className="bg-card rounded-xl border">
          {d.turns.map((turn, ti) => {
            const part = multi ? partAt(d.parts, turn.start).part : 0;
            const prevPart = multi && ti > 0 ? partAt(d.parts, d.turns[ti - 1].start).part : 0;
            return (
              <div key={ti}>
                {multi && (ti === 0 || part !== prevPart) && (
                  <div className="bg-muted/60 text-muted-foreground border-b px-4 py-1.5 text-xs font-semibold tracking-wide uppercase">
                    Teil {part + 1}
                  </div>
                )}
                <TurnRow
                  ti={ti}
                  turn={turn}
                  speaker={turn.speaker ? speakers[turn.speaker] : undefined}
                  time={stamp(d.parts, turn.start)}
                  playing={ti === playingTurn}
                  questions={qByTurn.get(ti)}
                  links={lByTurn.get(ti)}
                  interview={d.id}
                  mode={mode}
                  showEdits={showEdits}
                  speakers={speakers}
                  onSpeakerClick={mode === "correct" ? onSpeakerClick : undefined}
                  onWordClick={onWordClick}
                  onDeleteLink={deleteLink}
                />
              </div>
            );
          })}
        </div>
      </div>

      <aside className="sticky top-20 hidden h-[calc(100vh-7rem)] w-72 shrink-0 overflow-y-auto lg:block">
        <Card className="gap-3 py-4">
          <CardHeader>
            <CardTitle className="text-sm">Leitfaden in diesem Gespräch</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {guide.map((gq) => {
              const c = d.cells[gq.code];
              if (!c) return null;
              const turn = c.exchanges[0]?.question.turn ?? c.links[0]?.turn;
              const start = c.exchanges[0]?.start ?? c.links[0]?.start;
              return (
                <a
                  key={gq.code}
                  href={turn !== undefined ? href.interview(pid, d.id, turn) : href.questions(pid, gq.code)}
                  className="hover:bg-accent flex items-center gap-2 rounded px-1.5 py-1 text-sm"
                  title={gq.text}
                >
                  <StatusDot status={c.status} />
                  <span className="text-question w-8 font-semibold">{gq.code}</span>
                  <span className="text-muted-foreground flex-1 truncate text-xs">{STATUS_LABEL[c.status]}</span>
                  {start !== undefined && <span className="text-muted-foreground font-mono text-[11px]">{stamp(d.parts, start)}</span>}
                </a>
              );
            })}
          </CardContent>
        </Card>
        <div className="text-muted-foreground mt-4 space-y-2 px-1 text-xs">
          <p>Text mit der Maus markieren → „Als Frage markieren“, „Antwort auf Frage …“ oder „Als Extrakt übernehmen …“.</p>
          <p>Auf ein Wort klicken → ab dort anhören (Modus „Lesen“).</p>
          <p>
            <span className="word-low">gepunktet unterstrichen</span> = unsicher erkannt
          </p>
          <p>
            <span className="underline decoration-question decoration-2 underline-offset-2">unterstrichen</span> = korrigiert,{" "}
            <span className="underline decoration-dashed decoration-muted-foreground decoration-2 underline-offset-2">gestrichelt unterstrichen</span>{" "}
            = geglättet ersetzt, <span className="line-through">durchgestrichen</span> = entfernt,{" "}
            <span className="outline-muted-foreground/50 rounded-sm outline-1 outline-dashed">gestrichelt umrandet</span> = Sprecher
            geändert (bei „Änderungen anzeigen“)
          </p>
          <p>Falscher Sprecher: im Modus „Korrigieren“ Wörter markieren oder auf den Sprechernamen klicken.</p>
        </div>
      </aside>

      {sel && (
        <div
          data-selbar
          className="bg-popover animate-in fade-in-0 fixed z-40 flex flex-wrap gap-1 rounded-lg border p-1 shadow-lg"
          style={{ left: Math.max(8, sel.x), top: Math.max(64, sel.y - 48) }}
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              review.editQuestion(d.id, { ...sel.span, guide_code: null, match: "main", status: "new" });
              setSel(null);
            }}
          >
            <MessageCircleQuestionIcon />
            Als Frage markieren
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              review.linkAnswer(d.id, sel.span);
              setSel(null);
            }}
          >
            <CornerUpRightIcon />
            Antwort auf Frage …
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              review.extract(d.id, sel.span);
              setSel(null);
            }}
          >
            <QuoteIcon />
            Als Extrakt übernehmen …
          </Button>
          {mode === "correct" && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  openEdit(sel.span, "replace", "correction");
                  setSel(null);
                }}
              >
                <PencilIcon />
                Ersetzen …
              </Button>
              {d.speakers.map((s) => (
                <Button
                  key={s.label}
                  size="sm"
                  variant="ghost"
                  title="Diese Wörter sagt …"
                  onClick={() => {
                    void setSpeaker(sel.span, s.label);
                    setSel(null);
                  }}
                >
                  <UserRoundIcon />
                  {s.display_name || s.label}
                </Button>
              ))}
              {d.turns[sel.span.turn].words.slice(sel.span.first, sel.span.last + 1).some((w) => w.so) && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void setSpeaker(sel.span, null);
                    setSel(null);
                  }}
                >
                  <Undo2Icon />
                  Sprecher zurücksetzen
                </Button>
              )}
            </>
          )}
          {mode === "smooth" && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  openEdit(sel.span, "delete", "smoothing");
                  setSel(null);
                }}
              >
                <EraserIcon />
                Entfernen
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  openEdit(sel.span, "replace", "smoothing");
                  setSel(null);
                }}
              >
                <PencilIcon />
                Ersetzen …
              </Button>
            </>
          )}
        </div>
      )}

      <EditDialog edit={edit} setEdit={setEdit} tags={detail!.tags} busy={busy} error={editError} onSave={saveEdit} onRevert={revertEdit} />
    </div>
  );
}

function EditDialog({
  edit,
  setEdit,
  tags,
  busy,
  error,
  onSave,
  onRevert,
}: {
  edit: EditDraft | null;
  setEdit: (e: EditDraft | null) => void;
  tags: string[];
  busy: boolean;
  error: string | null;
  onSave: () => void;
  onRevert: () => void;
}) {
  const title = !edit
    ? ""
    : edit.kind === "correction"
      ? "Wort korrigieren"
      : edit.action === "delete"
        ? "Text entfernen (Glättung)"
        : "Text ersetzen (Glättung)";
  const valid = !!edit && (edit.action === "delete" || edit.text.trim() !== "") && (edit.kind === "correction" || edit.tag !== "");
  return (
    <Dialog open={edit !== null} onOpenChange={(o) => !o && setEdit(null)}>
      <DialogContent className="sm:max-w-xl">
        {edit && (
          <>
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
              <DialogDescription>Das Originaltranskript bleibt unverändert. Die Änderung wird separat gespeichert.</DialogDescription>
            </DialogHeader>
            <blockquote className="bg-muted max-h-32 overflow-auto rounded-md border-l-4 px-3 py-2 text-sm">{edit.original || "–"}</blockquote>
            {edit.action === "replace" && (
              <div className="grid gap-2">
                <Label htmlFor="edit-text">{edit.kind === "correction" ? "Richtiger Text" : "Neuer Text"}</Label>
                <Input
                  id="edit-text"
                  autoFocus
                  maxLength={200}
                  value={edit.text}
                  onChange={(e) => setEdit({ ...edit, text: e.target.value })}
                />
                {edit.kind === "correction" && edit.span.last > edit.span.first && (
                  <p className="text-muted-foreground text-xs">Mehrere Wörter: Die übrigen Wörter der Markierung werden leer.</p>
                )}
              </div>
            )}
            {edit.kind === "smoothing" && (
              <div className="grid gap-2">
                <Label>Grund</Label>
                <Select value={edit.tag} onValueChange={(tag) => setEdit({ ...edit, tag })}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Grund wählen" />
                  </SelectTrigger>
                  <SelectContent>
                    {tags.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {error && <p className="text-destructive text-sm whitespace-pre-line">{error}</p>}
            <DialogFooter className="sm:justify-between">
              <div>
                {edit.hasEdits && (
                  <Button variant="ghost" disabled={busy} onClick={onRevert}>
                    <Undo2Icon />
                    Änderung zurücknehmen
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setEdit(null)}>
                  Abbrechen
                </Button>
                <Button disabled={!valid || busy} onClick={onSave}>
                  Speichern
                </Button>
              </div>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

const TurnRow = memo(function TurnRow({
  ti,
  turn,
  speaker,
  time,
  playing,
  questions,
  links,
  interview,
  mode,
  showEdits,
  speakers,
  onSpeakerClick,
  onWordClick,
  onDeleteLink,
}: {
  ti: number;
  turn: Turn;
  speaker: Speaker | undefined;
  time: string;
  playing: boolean;
  questions: AskedQuestion[] | undefined;
  links: Link[] | undefined;
  interview: string;
  mode: Mode;
  showEdits: boolean;
  speakers: Record<string, Speaker>;
  /** only while correcting: select the whole turn to give it another speaker */
  onSpeakerClick?: (ti: number, x: number, y: number) => void;
  onWordClick: (ti: number, wi: number) => void;
  onDeleteLink: (lk: Link) => void;
}) {
  const review = useReview();
  const isInterviewer = speaker?.role === "interviewer";
  const qAt = (wi: number) => questions?.find((q) => q.first <= wi && wi <= q.last);
  return (
    <div id={`t-${ti}`} className={cn("flex gap-3 border-b px-4 py-2.5 transition-colors last:border-0", playing && "turn-playing")}>
      <span className="text-muted-foreground w-20 shrink-0 pt-0.5 font-mono text-xs tabular-nums">{time}</span>
      <div className="min-w-0 flex-1 leading-relaxed">
        {onSpeakerClick ? (
          <button
            data-selbar
            className={cn(
              "hover:bg-accent mr-1.5 cursor-pointer rounded text-sm font-semibold",
              isInterviewer ? "text-interviewer" : "text-foreground",
            )}
            title="Sprecher dieses ganzen Abschnitts ändern"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              onSpeakerClick(ti, r.left, r.top);
            }}
          >
            {speaker?.display_name || turn.speaker || "?"}:
          </button>
        ) : (
          <span className={cn("mr-1.5 text-sm font-semibold", isInterviewer ? "text-interviewer" : "text-foreground")}>
            {speaker?.display_name || turn.speaker || "?"}:
          </span>
        )}
        {turn.words.map((w, wi) => {
          // a word another speaker says (corrected by hand): name the speaker where it changes
          const who = w.sp ?? turn.speaker;
          const before = wi === 0 ? turn.speaker : (turn.words[wi - 1].sp ?? turn.speaker);
          const switched = who !== before && w.t !== "";
          const q = qAt(wi);
          const startQ = questions?.find((x) => x.first === wi);
          const startLinks = links?.filter((l) => l.first === wi) ?? [];
          const inLink = links?.some((l) => l.first <= wi && wi <= l.last);
          // edited words: a deletion (either kind) shows the original struck through; a replacement shows the new
          // text underlined, in the correction colour or, for smoothing, dashed
          const edited = w.k !== undefined;
          const struck = showEdits && edited && w.t === "";
          const corrected = showEdits && edited && w.t !== "" && w.k === "correction";
          const smoothed = showEdits && edited && w.t !== "" && w.k === "smoothing";
          const title = edited
            ? `${w.k === "smoothing" ? `Glättung (${w.g ?? ""})` : "Korrektur"} – Original: „${w.o ?? ""}“`
            : w.p < 0.5
              ? `unsicher (${Math.round(w.p * 100)} %)`
              : undefined;
          return (
            <span key={wi}>
              {switched && (
                <span
                  className={cn(
                    "mx-1 rounded px-1 py-px align-baseline text-[11px] font-semibold",
                    who && speakers[who]?.role === "interviewer" ? "bg-question-soft text-interviewer" : "bg-muted",
                  )}
                >
                  {(who && speakers[who]?.display_name) || who || "?"}:
                </span>
              )}
              {startQ && (
                <button
                  className={cn(
                    "mx-0.5 cursor-pointer rounded px-1 py-px align-baseline text-[11px] font-semibold",
                    startQ.guide_code && startQ.match !== "followup" ? "bg-question text-white" : "bg-muted text-muted-foreground",
                  )}
                  title="Zuordnung ändern"
                  onClick={() => review.editQuestion(interview, { ...startQ })}
                >
                  {startQ.guide_code ? tagText(startQ.guide_code, startQ.match) : startQ.match === "followup" ? "Nachfrage" : "Frage?"}
                </button>
              )}
              {startLinks.map((lk) => (
                <button
                  key={lk.id}
                  className="bg-linked mx-0.5 cursor-pointer rounded px-1 py-px align-baseline text-[11px] font-semibold text-white"
                  title={`beantwortet ${lk.guide_code} – klicken zum Löschen`}
                  onClick={() => onDeleteLink(lk)}
                >
                  ↗{lk.guide_code}
                </button>
              ))}
              <span
                data-ti={ti}
                data-wi={wi}
                onClick={() => onWordClick(ti, wi)}
                title={title}
                className={cn(
                  "rounded-sm hover:bg-accent",
                  mode === "read" ? "cursor-pointer" : "cursor-text",
                  q && (q.guide_code && q.match !== "followup" ? "text-question font-medium" : "font-medium"),
                  inLink && "bg-linked-soft",
                  w.p < 0.5 && !edited && "word-low",
                  corrected && "decoration-question underline decoration-2 underline-offset-2",
                  smoothed && "underline decoration-dashed decoration-muted-foreground decoration-2 underline-offset-2",
                  struck && "text-muted-foreground",
                  showEdits && w.so && "outline-muted-foreground/50 outline-1 outline-dashed",
                )}
              >
                {struck ? <s>{w.o}</s> : w.t}
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
});

function group<T>(items: T[], key: (x: T) => number): Map<number, T[]> {
  const m = new Map<number, T[]>();
  for (const x of items) m.set(key(x), [...(m.get(key(x)) ?? []), x]);
  return m;
}

function lastIndexWhere<T>(arr: T[], pred: (x: T) => boolean): number {
  let lo = 0;
  let hi = arr.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (pred(arr[mid])) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}
