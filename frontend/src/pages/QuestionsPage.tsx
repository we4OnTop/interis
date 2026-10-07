import { useEffect } from "react";
import { ChevronLeftIcon, ChevronRightIcon, FileTextIcon, LayoutGridIcon, LoaderIcon, MessageCircleQuestionIcon, PencilIcon } from "lucide-react";

import { InterviewFilter } from "@/components/InterviewFilter";
import { CellContent, PlayButton, StatusBadge, StatusDot, Time } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Cell, Compare, GuideQuestion } from "@/lib/api";
import { useCompare, useHidden, useStoredFlag } from "@/lib/compare";
import { STATUS_LABEL, stamp } from "@/lib/format";
import { useProject } from "@/lib/project";
import { ReviewProvider, useReview } from "@/lib/review";
import { href, navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

const UNASSIGNED = "_ohne";

export function QuestionsPage({ code }: { code: string | null }) {
  const { detail } = useProject();
  const pid = detail!.project.id;
  const { data, reload } = useCompare();
  const { hidden, toggle } = useHidden(pid);
  const [showSuggestions, setShowSuggestions] = useStoredFlag("interis.suggestions", true);

  const questions = data?.guide?.questions ?? [];
  const index = questions.findIndex((q) => q.code === code);

  // ← / → : previous / next question
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, [role=dialog]")) return;
      if (e.key === "ArrowRight" && index < questions.length - 1) navigate(href.questions(pid, questions[index + 1].code));
      if (e.key === "ArrowLeft" && index > 0) navigate(href.questions(pid, questions[index - 1].code));
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [index, questions, pid]);

  if (!data) return <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  if (!data.guide) return <Empty pid={pid} what="guide" />;
  if (!data.interviews.length) return <Empty pid={pid} what="interviews" />;

  const ids = data.interviews.filter((id) => !hidden.has(id));
  const selected = index >= 0 ? questions[index] : null;

  return (
    <ReviewProvider guide={data.guide} onChanged={reload}>
      <div className="flex h-[calc(100vh-3.5rem)]">
        <QuestionNav data={data} ids={ids} code={code} pid={pid} />
        <main className="min-w-0 flex-1 overflow-y-auto pb-24">
          <div className="bg-background/95 sticky top-0 z-10 border-b px-6 py-3 backdrop-blur">
            <InterviewFilter
              ids={data.interviews}
              hidden={hidden}
              toggle={toggle}
              showSuggestions={showSuggestions}
              setShowSuggestions={setShowSuggestions}
            />
          </div>
          <div className="space-y-5 px-6 py-5">
            {selected ? (
              <QuestionDetail
                q={selected}
                data={data}
                ids={ids}
                showSuggestions={showSuggestions}
                onChanged={reload}
                prev={index > 0 ? questions[index - 1].code : null}
                next={index < questions.length - 1 ? questions[index + 1].code : null}
              />
            ) : code === UNASSIGNED ? (
              <Unassigned data={data} ids={ids} />
            ) : (
              <Matrix data={data} ids={ids} pid={pid} />
            )}
          </div>
        </main>
      </div>
    </ReviewProvider>
  );
}

function Empty({ pid, what }: { pid: number; what: "guide" | "interviews" }) {
  return (
    <div className="mx-auto max-w-xl p-10 text-center">
      <MessageCircleQuestionIcon className="text-muted-foreground mx-auto mb-3 size-10" />
      <p className="text-muted-foreground mb-4">
        {what === "guide" ? "Für den Vergleich braucht das Projekt einen Leitfaden." : "Noch keine fertig transkribierten Gespräche."}
      </p>
      <Button asChild>
        <a href={href.setup(pid, what === "guide" ? "guide" : "interviews")}>{what === "guide" ? "Leitfaden eingeben" : "Gespräch hinzufügen"}</a>
      </Button>
    </div>
  );
}

function QuestionNav({ data, ids, code, pid }: { data: Compare; ids: string[]; code: string | null; pid: number }) {
  let section: string | null = null;
  const unassigned = ids.reduce((n, id) => n + (data.unassigned[id]?.length ?? 0), 0);
  return (
    <nav className="bg-muted/30 w-80 shrink-0 overflow-y-auto border-r p-3 pb-24">
      <a
        href={href.questions(pid)}
        className={cn(
          "hover:bg-accent mb-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium",
          code === null && "bg-accent",
        )}
      >
        <LayoutGridIcon className="size-4" />
        Übersicht aller Fragen
      </a>
      {data.guide!.questions.map((q) => {
        const heading = q.section && q.section !== section ? q.section : null;
        section = q.section;
        return (
          <div key={q.code}>
            {heading && <p className="text-muted-foreground mt-3 mb-1 px-2 text-[11px] font-semibold tracking-wide uppercase">{heading}</p>}
            <a
              href={href.questions(pid, q.code)}
              className={cn("hover:bg-accent block rounded-md px-2 py-1.5", code === q.code && "bg-accent ring-border ring-1")}
            >
              <div className="flex gap-2 text-sm">
                <span className="text-question w-8 shrink-0 font-semibold">{q.code}</span>
                <span className="line-clamp-2 leading-snug">{q.text}</span>
              </div>
              <div className="mt-1 flex gap-1 pl-10">
                {ids.map((id) => (
                  <StatusDot key={id} status={data.cells[id][q.code].status} />
                ))}
              </div>
            </a>
          </div>
        );
      })}
      <a
        href={href.questions(pid, UNASSIGNED)}
        className={cn("hover:bg-accent mt-3 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm", code === UNASSIGNED && "bg-accent")}
      >
        <span className="text-muted-foreground w-8 shrink-0 font-semibold">?</span>
        Ohne Leitfaden-Zuordnung
        <Badge variant="secondary" className="ml-auto">
          {unassigned}
        </Badge>
      </a>
    </nav>
  );
}

function Legend() {
  return (
    <div className="text-muted-foreground flex flex-wrap gap-4 text-xs">
      {(["asked", "answered_elsewhere", "omitted", "missing"] as const).map((s) => (
        <span key={s} className="flex items-center gap-1.5">
          <StatusDot status={s} />
          {STATUS_LABEL[s]}
        </span>
      ))}
    </div>
  );
}

function firstTime(c: Cell): number | null {
  return c.exchanges[0]?.start ?? c.links[0]?.start ?? null;
}

function Matrix({ data, ids, pid }: { data: Compare; ids: string[]; pid: number }) {
  const { interview } = useProject();
  const questions = data.guide!.questions;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Übersicht: welche Frage wo beantwortet wurde</h1>
        <p className="text-muted-foreground text-sm">Klick auf eine Zeile oder Zelle zeigt alle Antworten zu dieser Frage.</p>
      </div>
      <Legend />
      <Card className="overflow-hidden py-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="w-[45%] px-3 py-2 text-left font-medium">Leitfadenfrage</th>
                {ids.map((id) => (
                  <th key={id} className="px-3 py-2 text-left font-mono font-medium">
                    <a href={href.interview(pid, id)} className="hover:underline">
                      {id}
                    </a>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {questions.map((q) => (
                <tr key={q.code} className="hover:bg-muted/40 cursor-pointer border-t" onClick={() => navigate(href.questions(pid, q.code))}>
                  <td className="px-3 py-2">
                    <span className="text-question mr-2 font-semibold">{q.code}</span>
                    {q.text}
                  </td>
                  {ids.map((id) => {
                    const c = data.cells[id][q.code];
                    const t = firstTime(c);
                    return (
                      <td key={id} className="px-3 py-2 whitespace-nowrap">
                        <span className="flex items-center gap-2">
                          <StatusDot status={c.status} />
                          <span className="text-muted-foreground font-mono text-xs">{t !== null ? stamp(interview(id)?.parts, t) : "–"}</span>
                          {c.links.length + c.exchanges.length > 1 && (
                            <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                              {c.links.length + c.exchanges.length}×
                            </Badge>
                          )}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="bg-muted/30 border-t">
                <td className="text-muted-foreground px-3 py-2 text-xs">Gestellt / anderswo beantwortet</td>
                {ids.map((id) => {
                  const cells = Object.values(data.cells[id]);
                  return (
                    <td key={id} className="text-muted-foreground px-3 py-2 text-xs">
                      {cells.filter((c) => c.status === "asked").length} /{" "}
                      {cells.filter((c) => c.status === "answered_elsewhere" || c.status === "omitted").length} von {cells.length}
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function QuestionDetail({
  q,
  data,
  ids,
  showSuggestions,
  onChanged,
  prev,
  next,
}: {
  q: GuideQuestion;
  data: Compare;
  ids: string[];
  showSuggestions: boolean;
  onChanged: () => void;
  prev: string | null;
  next: string | null;
}) {
  const { detail } = useProject();
  const pid = detail!.project.id;
  return (
    <>
      <div className="flex items-start gap-3">
        <Badge variant="question" className="mt-1 text-sm">
          {q.code}
        </Badge>
        <div className="min-w-0 flex-1">
          {q.section && <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{q.section}</p>}
          <h1 className="text-xl leading-snug font-semibold">{q.text}</h1>
          {q.variants.length > 0 && <p className="text-muted-foreground mt-1 text-sm">auch: {q.variants.join(" · ")}</p>}
          {q.probes.length > 0 && <p className="text-muted-foreground text-sm">Nachfragen: {q.probes.join(" · ")}</p>}
        </div>
        <div className="flex shrink-0 gap-1">
          <Button variant="outline" size="icon-sm" disabled={!prev} onClick={() => prev && navigate(href.questions(pid, prev))} title="vorige Frage (←)">
            <ChevronLeftIcon />
          </Button>
          <Button variant="outline" size="icon-sm" disabled={!next} onClick={() => next && navigate(href.questions(pid, next))} title="nächste Frage (→)">
            <ChevronRightIcon />
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {ids.map((id) => (
          <a key={id} href={`#iv-${id}`} className="hover:bg-accent flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
            <StatusDot status={data.cells[id][q.code].status} />
            <span className="font-mono font-medium">{id}</span>
            <span className="text-muted-foreground">{STATUS_LABEL[data.cells[id][q.code].status]}</span>
          </a>
        ))}
      </div>

      {ids.map((id) => {
        const cell = data.cells[id][q.code];
        return (
          <Card key={id} id={`iv-${id}`} className={cn("scroll-mt-20 gap-3 py-4", cell.status === "missing" && "bg-muted/20")}>
            <CardHeader className="flex flex-row flex-wrap items-center gap-2">
              <CardTitle className="font-mono">{id}</CardTitle>
              <StatusBadge status={cell.status} />
              {cell.exchanges.map((ex, i) => (
                <span key={i} className="flex items-center">
                  <PlayButton id={id} start={ex.start} />
                  <Time id={id} t={ex.start} />
                </span>
              ))}
              <Button asChild variant="ghost" size="xs" className="text-muted-foreground ml-auto">
                <a href={href.interview(pid, id, cell.exchanges[0]?.question.turn ?? cell.links[0]?.turn)}>
                  <FileTextIcon />
                  Transkript
                </a>
              </Button>
            </CardHeader>
            <CardContent>
              <CellContent id={id} code={q.code} cell={cell} showSuggestions={showSuggestions} onChanged={onChanged} />
            </CardContent>
          </Card>
        );
      })}
    </>
  );
}

function Unassigned({ data, ids }: { data: Compare; ids: string[] }) {
  const review = useReview();
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold">Fragen ohne Leitfaden-Zuordnung</h1>
        <p className="text-muted-foreground text-sm">
          Meist spontane Nachfragen. War eine davon eigentlich eine Leitfadenfrage (anders formuliert), ordne sie mit dem Stift zu.
        </p>
      </div>
      {ids.map((id) => (
        <Card key={id} className="gap-2 py-4">
          <CardHeader>
            <CardTitle className="font-mono">{id}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {(data.unassigned[id] ?? []).length === 0 && <p className="text-muted-foreground text-sm">keine</p>}
            {(data.unassigned[id] ?? []).map((q) => (
              <div key={q.id} className="group flex items-center gap-1.5 text-sm">
                <PlayButton id={id} start={q.start} end={q.end} />
                <Time id={id} t={q.start} />
                <span className="flex-1">{q.text}</span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="opacity-60 group-hover:opacity-100"
                  title="einer Leitfadenfrage zuordnen"
                  onClick={() => review.editQuestion(id, { ...q })}
                >
                  <PencilIcon />
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </>
  );
}
