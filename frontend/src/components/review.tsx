import { CheckIcon, CornerUpRightIcon, FileTextIcon, PauseIcon, PlayIcon, Trash2Icon, XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type Cell, type CellStatus, type DialogueTurn, type Link, type Suggestion } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { LINK_LABEL, STATUS_LABEL, STATUS_SHORT, stamp, tagText } from "@/lib/format";
import { usePlayer, usePlayerState } from "@/lib/player";
import { useProject } from "@/lib/project";
import { useReview } from "@/lib/review";
import { href } from "@/lib/router";
import { cn } from "@/lib/utils";

export function Hint({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

export function PlayButton({ id, start, end }: { id: string; start: number; end?: number }) {
  const player = usePlayer();
  const ps = usePlayerState();
  const { source, interview } = useProject();
  const hasAudio = interview(id)?.has_audio;
  const playingHere = ps.playing && ps.id === id && ps.time >= start - 0.3 && ps.time <= (end ?? start + 600);
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      className="text-muted-foreground hover:text-foreground shrink-0"
      disabled={!hasAudio}
      title={hasAudio ? "Anhören" : "Keine Audiodatei"}
      onClick={(e) => {
        e.stopPropagation();
        if (playingHere) player.toggle();
        else player.play(source(id), start, end);
      }}
    >
      {playingHere ? <PauseIcon /> : <PlayIcon />}
    </Button>
  );
}

export function Time({ id, t }: { id: string; t: number }) {
  const { interview } = useProject();
  return <span className="text-muted-foreground font-mono text-xs tabular-nums">{stamp(interview(id)?.parts, t)}</span>;
}

const STATUS_STYLE: Record<CellStatus, string> = {
  asked: "bg-question-soft text-question",
  answered_elsewhere: "bg-linked-soft text-linked",
  omitted: "bg-linked-soft text-linked",
  missing: "bg-muted text-muted-foreground",
};

export function StatusBadge({ status, short = false }: { status: CellStatus; short?: boolean }) {
  return <Badge className={cn("border-transparent", STATUS_STYLE[status])}>{short ? STATUS_SHORT[status] : STATUS_LABEL[status]}</Badge>;
}

/** Small coloured square for the question × interview overview. */
export function StatusDot({ status, className }: { status: CellStatus; className?: string }) {
  const style: Record<CellStatus, string> = {
    asked: "bg-question",
    answered_elsewhere: "bg-linked",
    omitted: "bg-linked ring-2 ring-linked/30",
    missing: "bg-transparent border border-dashed border-muted-foreground/50",
  };
  return <span className={cn("inline-block size-2.5 shrink-0 rounded-[3px]", style[status], className)} />;
}

function OpenInTranscript({ id, turn }: { id: string; turn: number }) {
  const { detail } = useProject();
  return (
    <Hint text="Im Transkript öffnen">
      <Button asChild variant="ghost" size="icon-xs" className="text-muted-foreground hover:text-foreground shrink-0">
        <a href={href.interview(detail!.project.id, id, turn)}>
          <FileTextIcon />
        </a>
      </Button>
    </Hint>
  );
}

export function Dialogue({ id, code, turns }: { id: string; code: string | null; turns: DialogueTurn[] }) {
  const review = useReview();
  return (
    <div className="space-y-1.5">
      {turns.map((t) => {
        const isInterviewer = t.role === "interviewer";
        return (
          <div key={t.turn} className="group flex gap-1.5 text-sm leading-relaxed">
            <PlayButton id={id} start={t.start} end={t.end} />
            <div className="min-w-0 flex-1">
              <span className={cn("mr-1 text-xs font-semibold", isInterviewer ? "text-interviewer" : "text-muted-foreground")}>
                {isInterviewer ? "I" : t.role === "interviewee" ? "B" : t.speaker}:
              </span>
              {t.pieces.map((p, i) =>
                p.question ? (
                  <span key={i}>
                    <button
                      className={cn(
                        "mr-1 cursor-pointer rounded px-1 py-px align-baseline text-[11px] font-semibold",
                        p.match === "followup" || !p.code ? "bg-muted text-muted-foreground" : "bg-question text-white",
                      )}
                      title="Zuordnung ändern"
                      onClick={() =>
                        review.editQuestion(id, {
                          turn: p.turn!,
                          first: p.first!,
                          last: p.last!,
                          text: p.text,
                          guide_code: p.code ?? null,
                          match: p.match ?? null,
                          status: p.status,
                        })
                      }
                    >
                      {tagText(p.code, p.match)}
                    </button>
                    <span className={cn("font-medium", p.match === "followup" || !p.code ? "" : "text-question")}>{p.text}</span>{" "}
                  </span>
                ) : (
                  <span key={i}>{p.text} </span>
                ),
              )}
            </div>
            <div className="flex shrink-0 items-start opacity-0 transition-opacity group-hover:opacity-100">
              {!isInterviewer && (
                <Hint text="Diese Antwort beantwortet auch eine andere Frage …">
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="text-muted-foreground hover:text-linked"
                    onClick={() =>
                      review.linkAnswer(
                        id,
                        { turn: t.turn, first: 0, last: t.n_words - 1, text: t.pieces.map((p) => p.text).join(" ") },
                        { excludeCode: code },
                      )
                    }
                  >
                    <CornerUpRightIcon />
                  </Button>
                </Hint>
              )}
              <OpenInTranscript id={id} turn={t.turn} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function LinkItem({ id, link, onChanged }: { id: string; link: Link; onChanged: () => void }) {
  const { fail } = useFeedback();
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      onChanged();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <div className="border-l-linked bg-linked-soft/40 rounded-md border-l-[3px] px-2 py-1.5 text-sm">
      <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
        <PlayButton id={id} start={link.start} end={link.end} />
        <Time id={id} t={link.start} />
        <Badge variant="linked">{LINK_LABEL[link.type]}</Badge>
        {link.from_code && <span className="text-muted-foreground text-xs">aus der Antwort auf {link.from_code}</span>}
        <span className="flex-1" />
        {link.type === "unasked" && (
          <label className="flex cursor-pointer items-center gap-1.5 text-xs">
            <Checkbox
              checked={link.omitted}
              onCheckedChange={(c) => act(() => api("PATCH", `/api/links/${link.id}`, { omitted: c === true }))}
            />
            deshalb weggelassen
          </label>
        )}
        <Hint text="Verknüpfung löschen">
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => act(() => api("DELETE", `/api/links/${link.id}`))}
          >
            <Trash2Icon />
          </Button>
        </Hint>
        <OpenInTranscript id={id} turn={link.turn} />
      </div>
      <p className="pl-7">{link.text}</p>
      {link.note && <p className="text-muted-foreground pl-7 text-xs">Notiz: {link.note}</p>}
    </div>
  );
}

export function SuggestionItem({ id, code, s, onChanged }: { id: string; code: string; s: Suggestion; onChanged: () => void }) {
  const { notify, fail } = useFeedback();
  const decide = async (status: "confirmed" | "rejected") => {
    try {
      await api("POST", "/api/links", {
        interview: id,
        turn: s.turn,
        first: s.first,
        last: s.last,
        guide_code: code,
        status,
        source: "suggestion",
        omitted: false,
      });
      notify(status === "confirmed" ? "Vorschlag übernommen" : "Vorschlag verworfen");
      onChanged();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <div className="border-suggest/60 rounded-md border border-dashed px-2 py-1.5 text-sm">
      <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
        <PlayButton id={id} start={s.start} end={s.end} />
        <Time id={id} t={s.start} />
        <Badge variant="suggest">evtl. {LINK_LABEL[s.type]}</Badge>
        {s.from_code && <span className="text-muted-foreground text-xs">aus der Antwort auf {s.from_code}</span>}
        <span className="flex-1" />
        <Hint text="Übernehmen">
          <Button variant="ghost" size="icon-xs" className="hover:text-linked" onClick={() => decide("confirmed")}>
            <CheckIcon />
          </Button>
        </Hint>
        <Hint text="Verwerfen">
          <Button variant="ghost" size="icon-xs" className="hover:text-destructive" onClick={() => decide("rejected")}>
            <XIcon />
          </Button>
        </Hint>
        <OpenInTranscript id={id} turn={s.turn} />
      </div>
      <p className="text-muted-foreground pl-7">{s.text}</p>
    </div>
  );
}

/** Everything one interview says about one guide question. */
export function CellContent({
  id,
  code,
  cell,
  showSuggestions,
  onChanged,
}: {
  id: string;
  code: string;
  cell: Cell;
  showSuggestions: boolean;
  onChanged: () => void;
}) {
  return (
    <div className="space-y-3">
      {cell.exchanges.map((ex, i) => (
        <div key={i} className="border-question/30 border-l-2 pl-2">
          <Dialogue id={id} code={code} turns={ex.dialogue} />
        </div>
      ))}
      {cell.links.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-muted-foreground text-xs font-medium">
            {cell.exchanges.length ? "Auch beantwortet an anderer Stelle" : "Beantwortet an anderer Stelle"}
          </p>
          {cell.links.map((lk) => (
            <LinkItem key={lk.id} id={id} link={lk} onChanged={onChanged} />
          ))}
        </div>
      )}
      {showSuggestions && cell.suggestions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-muted-foreground text-xs font-medium">Vorschläge – bitte prüfen</p>
          {cell.suggestions.map((s, i) => (
            <SuggestionItem key={i} id={id} code={code} s={s} onChanged={onChanged} />
          ))}
        </div>
      )}
      {!cell.exchanges.length && !cell.links.length && (
        <p className="text-muted-foreground text-xs">
          Nicht gestellt. Falls die Antwort woanders steckt: im Transkript markieren → „Antwort auf Frage …“.
        </p>
      )}
    </div>
  );
}
