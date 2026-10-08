import { Fragment, useState, type DragEvent } from "react";
import { LoaderIcon, PencilIcon } from "lucide-react";

import { InterviewFilter } from "@/components/InterviewFilter";
import { LoadError } from "@/components/LoadError";
import { CellContent, PlayButton, StatusBadge, Time } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type AskedQuestion } from "@/lib/api";
import { useCompare, useHidden, useStoredFlag } from "@/lib/compare";
import { useFeedback } from "@/lib/feedback";
import { clock } from "@/lib/format";
import { useProject } from "@/lib/project";
import { DRAG_TYPE, readDrag, ReviewProvider, useReview } from "@/lib/review";
import { href } from "@/lib/router";
import { cn } from "@/lib/utils";

const SPONTANEOUS = "__spontaneous__";

/** Side by side: one row per guide question, one column per interview. */
export function ColumnsPage() {
  const { detail, interview } = useProject();
  const pid = detail!.project.id;
  const { data, reload, error } = useCompare();
  const { hidden, toggle } = useHidden(pid);
  const [showSuggestions, setShowSuggestions] = useStoredFlag("interis.suggestions", true);
  const { notify, fail } = useFeedback();
  const [drop, setDrop] = useState<string | null>(null);

  // Drop on a guide question row: a question becomes its main question, an answer is linked to it.
  // Drop on the spontaneous row: only questions, as follow-up questions without guide reference.
  const dropOn = async (e: DragEvent<HTMLElement>, code: string | null) => {
    e.preventDefault();
    setDrop(null);
    const p = readDrag(e);
    if (!p) return;
    if (code === null && p.kind !== "question") {
      fail("Nur Fragen können zu den spontanen Nachfragen gezogen werden.");
      return;
    }
    try {
      if (p.kind === "question") {
        await api("POST", "/api/questions", {
          interview: p.interview,
          turn: p.turn,
          first: p.first,
          last: p.last,
          guide_code: code,
          match: code ? "main" : "followup",
          status: "confirmed",
        });
        notify(code ? `Frage ${code} zugeordnet` : "Als spontane Nachfrage eingeordnet");
      } else {
        // only the fields the drop decides: an existing omitted flag and note stay as they are
        await api("POST", "/api/links", {
          interview: p.interview,
          turn: p.turn,
          first: p.first,
          last: p.last,
          guide_code: code,
          source: "manual",
          status: "confirmed",
        });
        notify(`Antwort auf ${code} verknüpft`);
      }
      await reload();
    } catch (err) {
      fail(err);
    }
  };
  const dropHandlers = (code: string | null) => {
    const key = code ?? SPONTANEOUS;
    return {
      onDragOver: (e: DragEvent<HTMLElement>) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
        // the spontaneous row takes questions only
        if (code === null && !e.dataTransfer.types.includes(`${DRAG_TYPE}-question`)) return;
        e.preventDefault();
        setDrop(key);
      },
      onDragLeave: () => setDrop((d) => (d === key ? null : d)),
      onDrop: (e: DragEvent<HTMLElement>) => void dropOn(e, code),
    };
  };
  const dropClass = (code: string | null) => cn((code ?? SPONTANEOUS) === drop && "bg-question-soft ring-question ring-2 ring-inset");

  if (!data)
    return error ? <LoadError message={error} onRetry={() => void reload()} /> : <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  if (!data.guide || !data.interviews.length)
    return (
      <p className="text-muted-foreground p-4 sm:p-6 text-sm">
        Noch nichts zu vergleichen. <a className="underline" href={href.setup(pid)}>Leitfaden & Gespräche einrichten</a>
      </p>
    );

  const ids = data.interviews.filter((id) => !hidden.has(id));
  let section: string | null = null;

  return (
    <ReviewProvider guide={data.guide} onChanged={reload}>
      <div className="flex h-[calc(100vh-3.5rem)] flex-col">
        <div className="border-b px-4 sm:px-6 py-3">
          <InterviewFilter ids={data.interviews} hidden={hidden} toggle={toggle} showSuggestions={showSuggestions} setShowSuggestions={setShowSuggestions} />
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-4 sm:px-6 pt-4 pb-24">
          <div
            className="bg-card grid w-max min-w-full rounded-lg border text-sm"
            style={{ gridTemplateColumns: `minmax(220px, 280px) repeat(${ids.length}, minmax(340px, 440px))` }}
          >
            <div className="bg-card sticky top-0 left-0 z-30 border-r border-b p-3 font-semibold">Leitfaden</div>
            {ids.map((id) => {
              const iv = interview(id);
              return (
                <div key={id} className="bg-card sticky top-0 z-20 border-r border-b p-3">
                  <a href={href.interview(pid, id)} className="font-mono font-semibold hover:underline">
                    {id}
                  </a>
                  <p className="text-muted-foreground text-xs">
                    {iv?.duration_s ? clock(iv.duration_s) : ""}
                    {iv && iv.parts.length > 1 ? ` · ${iv.parts.length} Teile` : ""}
                    {iv && !iv.has_roles ? " · Rollen unklar" : ""}
                  </p>
                  {iv?.guide_mismatch && <p className="text-suggest text-xs">mit älterem Leitfaden analysiert</p>}
                  {data.stale[id] && (
                    <Badge variant="suggest" className="mt-1">
                      Analyse veraltet
                    </Badge>
                  )}
                </div>
              );
            })}

            {data.guide.questions.map((q) => {
              const heading = q.section && q.section !== section ? q.section : null;
              section = q.section;
              return (
                <Fragment key={q.code}>
                  {heading && (
                    <div className="bg-muted sticky left-0 border-b px-3 py-1.5 text-xs font-semibold tracking-wide uppercase" style={{ gridColumn: "1 / -1" }}>
                      {heading}
                    </div>
                  )}
                  <div
                    {...dropHandlers(q.code)}
                    className={cn("bg-muted/40 sticky left-0 z-10 border-r border-b p-3", dropClass(q.code))}
                  >
                    <a href={href.questions(pid, q.code)} className="hover:underline">
                      <span className="text-question mr-1.5 font-semibold">{q.code}</span>
                      {q.text}
                    </a>
                    {q.variants.length > 0 && <p className="text-muted-foreground mt-1 text-xs">auch: {q.variants.join(" · ")}</p>}
                  </div>
                  {ids.map((id) => {
                    const cell = data.cells[id][q.code];
                    return (
                      <div key={id} className="min-w-0 space-y-2 border-r border-b p-3">
                        <div className="flex flex-wrap items-center gap-1">
                          <StatusBadge status={cell.status} />
                          {cell.exchanges.map((ex, i) => (
                            <Time key={i} id={id} t={ex.start} />
                          ))}
                        </div>
                        <div className="max-h-[28rem] overflow-y-auto">
                          <CellContent id={id} code={q.code} cell={cell} showSuggestions={showSuggestions} onChanged={reload} />
                        </div>
                      </div>
                    );
                  })}
                </Fragment>
              );
            })}

            <div className="bg-muted sticky left-0 border-b px-3 py-1.5 text-xs font-semibold tracking-wide uppercase" style={{ gridColumn: "1 / -1" }}>
              Fragen ohne Leitfaden-Zuordnung
            </div>
            <div
              {...dropHandlers(null)}
              className={cn("bg-muted/40 text-muted-foreground sticky left-0 z-10 border-r p-3 text-xs", dropClass(null))}
            >
              Spontane Nachfragen. Mit dem Stift einer Leitfadenfrage zuordnen, falls es eine war. Fragen hierher ziehen, wenn sie keine
              Leitfadenfrage sind.
            </div>
            {ids.map((id) => (
              <UnassignedCell key={id} id={id} list={data.unassigned[id] ?? []} />
            ))}
          </div>
        </div>
      </div>
    </ReviewProvider>
  );
}

function UnassignedCell({ id, list }: { id: string; list: AskedQuestion[] }) {
  const review = useReview();
  return (
    <div className="space-y-1 border-r p-3">
      {list.length === 0 && <span className="text-muted-foreground text-xs">–</span>}
      {list.map((q) => (
        <div key={q.id} className="group flex items-start gap-1 text-sm">
          <PlayButton id={id} start={q.start} end={q.end} />
          <span className="flex-1">{q.text}</span>
          <Button variant="ghost" size="icon-xs" className="opacity-50 group-hover:opacity-100" onClick={() => review.editQuestion(id, { ...q })}>
            <PencilIcon />
          </Button>
        </div>
      ))}
    </div>
  );
}
