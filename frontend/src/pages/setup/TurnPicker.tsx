import { useEffect, useMemo, useRef, useState } from "react";
import { LoaderIcon, SparklesIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, enc } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { clock } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Block {
  i: number;
  speaker: string | null;
  start: number;
  end: number;
  words: number;
  corrected: boolean;
  text: string;
}

interface Blocks {
  speakers: { label: string; name: string; role: string }[];
  turns: Block[];
  reviewed: boolean;
}

interface Suggestion {
  start: number;
  end: number;
}

const MIN_S = 60;
const MAX_S = 900;

/**
 * Pick the stretch to measure against in the corrected transcript, block by block (a block is
 * what one person says until the other speaks). Click the first block, then the last one.
 */
export function TurnPicker({
  open,
  interview,
  current,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  interview: string;
  current: Suggestion | null;
  onOpenChange: (open: boolean) => void;
  onPick: (start: number, end: number) => void;
}) {
  const { fail } = useFeedback();
  const [data, setData] = useState<Blocks | null>(null);
  const [from, setFrom] = useState<number | null>(null); // positions in data.turns
  const [to, setTo] = useState<number | null>(null);
  const [waiting, setWaiting] = useState(false); // the first block is set, the last is next
  const first = useRef<HTMLLIElement | null>(null);

  const select = (a: number, b: number) => {
    setFrom(Math.min(a, b));
    setTo(Math.max(a, b));
    setWaiting(false);
  };

  const fromTimes = (turns: Block[], s: Suggestion) => {
    const a = turns.findIndex((t) => t.end > s.start);
    let b = -1;
    turns.forEach((t, n) => {
      if (t.start < s.end) b = n;
    });
    if (a >= 0 && b >= a) select(a, b);
  };

  useEffect(() => {
    if (!open || !interview) return;
    setData(null);
    setFrom(null);
    setTo(null);
    setWaiting(false);
    api<Blocks>("GET", `/api/tuning/turns?interview=${enc(interview)}`)
      .then((d) => {
        setData(d);
        if (current) fromTimes(d.turns, current);
      })
      .catch((e) => {
        fail(e);
        onOpenChange(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, interview]);

  useEffect(() => {
    if (data && from !== null) first.current?.scrollIntoView({ block: "center" });
    // only when a selection appears, not on every click
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, from === null]);

  const names = useMemo(() => new Map((data?.speakers ?? []).map((s) => [s.label, s])), [data]);
  const picked = data && from !== null && to !== null ? data.turns.slice(from, to + 1) : [];
  const seconds = picked.length ? picked[picked.length - 1].end - picked[0].start : 0;
  const words = picked.reduce((n, t) => n + t.words, 0);
  const corrected = picked.filter((t) => t.corrected).length;

  const click = (n: number) => {
    if (!data) return;
    if (waiting && from !== null) select(from, n);
    else {
      setFrom(n);
      setTo(n);
      setWaiting(true);
    }
  };

  const suggest = async () => {
    try {
      const s = await api<Suggestion>("GET", `/api/tuning/suggest?interview=${enc(interview)}`);
      if (data) fromTimes(data.turns, s);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Ausschnitt wählen – {interview}</DialogTitle>
          <DialogDescription>
            Das Transkript so, wie du es korrigiert hast. Ein Block ist das, was eine Person sagt, bis die andere spricht. Klicke den{" "}
            <b>ersten</b> Block, dann den <b>letzten</b>. Die Aufnahme beginnt und endet immer an einer Blockgrenze, nie mitten im Satz.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Button variant="outline" size="sm" onClick={() => void suggest()} disabled={!data} title="Vom ersten bis zum letzten korrigierten Block">
            <SparklesIcon />
            Aus Korrekturen vorschlagen
          </Button>
          <span className="text-muted-foreground text-xs">
            {waiting
              ? "Jetzt den letzten Block anklicken …"
              : picked.length
                ? `${picked.length} Blöcke · ${clock(picked[0].start)} – ${clock(picked[picked.length - 1].end)} (${Math.round(seconds / 60 * 10) / 10} min) · ${words} Wörter · ${corrected} Blöcke mit Korrekturen`
                : "Noch nichts gewählt."}
          </span>
        </div>
        {!waiting && picked.length > 0 && seconds < MIN_S && (
          <p className="text-xs text-amber-600">Kürzer als 1 Minute: es werden die nächsten Blöcke dazugenommen.</p>
        )}
        {!waiting && seconds > MAX_S && <p className="text-xs text-amber-600">Länger als 15 Minuten: am Ende werden Blöcke weggelassen.</p>}
        {!waiting && picked.length > 0 && corrected === 0 && !data?.reviewed && (
          <p className="text-destructive text-xs">In diesem Ausschnitt ist nichts korrigiert – er zählt nur als Maßstab, wenn du ihn durchgesehen hast.</p>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
          {!data ? (
            <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />
          ) : (
            <ol className="divide-y">
              {data.turns.map((t, n) => {
                const inside = from !== null && to !== null && n >= from && n <= to;
                const sp = t.speaker ? names.get(t.speaker) : undefined;
                return (
                  <li
                    key={t.i}
                    ref={n === from ? first : undefined}
                    onClick={() => click(n)}
                    className={cn(
                      "hover:bg-accent/60 flex cursor-pointer gap-3 border-l-4 px-3 py-2 text-sm",
                      inside ? "border-l-primary bg-primary/5" : "border-l-transparent",
                      (n === from || n === to) && "bg-primary/10",
                    )}
                  >
                    <span className="text-muted-foreground w-14 shrink-0 pt-0.5 text-xs tabular-nums">{clock(t.start)}</span>
                    <span className="w-28 shrink-0">
                      <Badge variant={sp?.role === "interviewer" ? "question" : "secondary"} className="max-w-full truncate">
                        {sp?.name ?? t.speaker ?? "?"}
                      </Badge>
                    </span>
                    <span className="min-w-0 flex-1 break-words">
                      {t.text}
                      {t.corrected && (
                        <Badge variant="linked" className="ml-2 align-middle">
                          korrigiert
                        </Badge>
                      )}
                    </span>
                    {n === from && <span className="text-primary shrink-0 text-xs font-medium">Anfang</span>}
                    {n === to && to !== from && <span className="text-primary shrink-0 text-xs font-medium">Ende</span>}
                  </li>
                );
              })}
            </ol>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button
            disabled={!picked.length || waiting}
            onClick={() => {
              onPick(picked[0].start, picked[picked.length - 1].end);
              onOpenChange(false);
            }}
          >
            Diesen Ausschnitt übernehmen
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
