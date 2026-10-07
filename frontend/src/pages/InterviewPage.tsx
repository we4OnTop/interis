import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CornerUpRightIcon, LoaderIcon, MessageCircleQuestionIcon } from "lucide-react";

import { StatusDot } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, enc, type AskedQuestion, type InterviewDetail, type Link, type Speaker, type Turn } from "@/lib/api";
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

  const load = useCallback(async () => {
    try {
      setD(await api<InterviewDetail>("GET", `/api/interviews/${enc(id)}`));
    } catch (e) {
      fail(e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  if (!d) return <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  return (
    <ReviewProvider guide={detail!.guide} onChanged={load}>
      <Transcript d={d} focusTurn={focusTurn} onChanged={load} />
    </ReviewProvider>
  );
}

const ROLE_LABEL: Record<string, string> = { interviewer: "Interviewer", interviewee: "Befragte:r", unknown: "unbekannt" };

function Transcript({ d, focusTurn, onChanged }: { d: InterviewDetail; focusTurn: number | null; onChanged: () => void }) {
  const { detail, source } = useProject();
  const review = useReview();
  const { confirm, fail, notify } = useFeedback();
  const player = usePlayer();
  const ps = usePlayerState();
  const pid = detail!.project.id;
  const container = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<{ span: Span; x: number; y: number } | null>(null);
  const speakers = useMemo(() => Object.fromEntries(d.speakers.map((s) => [s.label, s])), [d.speakers]);

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
        const text = d.turns[turn].words.slice(first, last + 1).map((w) => w.t).join("").trim();
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

  const onWord = useCallback(
    (t: number) => {
      if (window.getSelection()?.isCollapsed === false) return;
      player.play(source(d.id), t + 0.15);
    },
    [player, source, d.id],
  );

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
    <div className="mx-auto flex max-w-7xl gap-6 p-6 pb-28">
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
                  onWord={onWord}
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
          <p>Text mit der Maus markieren → „Als Frage markieren“ oder „Antwort auf Frage …“.</p>
          <p>Auf ein Wort klicken → ab dort anhören.</p>
          <p>
            <span className="word-low">unterstrichen</span> = unsicher erkannt
          </p>
        </div>
      </aside>

      {sel && (
        <div
          data-selbar
          className="bg-popover animate-in fade-in-0 fixed z-40 flex gap-1 rounded-lg border p-1 shadow-lg"
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
        </div>
      )}
    </div>
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
  onWord,
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
  onWord: (t: number) => void;
  onDeleteLink: (lk: Link) => void;
}) {
  const review = useReview();
  const isInterviewer = speaker?.role === "interviewer";
  const qAt = (wi: number) => questions?.find((q) => q.first <= wi && wi <= q.last);
  return (
    <div id={`t-${ti}`} className={cn("flex gap-3 border-b px-4 py-2.5 transition-colors last:border-0", playing && "turn-playing")}>
      <span className="text-muted-foreground w-20 shrink-0 pt-0.5 font-mono text-xs tabular-nums">{time}</span>
      <div className="min-w-0 flex-1 leading-relaxed">
        <span className={cn("mr-1.5 text-sm font-semibold", isInterviewer ? "text-interviewer" : "text-foreground")}>
          {speaker?.display_name || turn.speaker || "?"}:
        </span>
        {turn.words.map((w, wi) => {
          const q = qAt(wi);
          const startQ = questions?.find((x) => x.first === wi);
          const startLinks = links?.filter((l) => l.first === wi) ?? [];
          const inLink = links?.some((l) => l.first <= wi && wi <= l.last);
          return (
            <span key={wi}>
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
                onClick={() => onWord(w.s)}
                title={w.p < 0.5 ? `unsicher (${Math.round(w.p * 100)} %)` : undefined}
                className={cn(
                  "cursor-pointer rounded-sm hover:bg-accent",
                  q && (q.guide_code && q.match !== "followup" ? "text-question font-medium" : "font-medium"),
                  inLink && "bg-linked-soft",
                  w.p < 0.5 && "word-low",
                )}
              >
                {w.t}
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
