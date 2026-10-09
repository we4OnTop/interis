import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDownIcon, ChevronUpIcon, LoaderIcon, PauseIcon, PlayIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, enc, type InterviewDetail } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { type Draft } from "@/components/InsertEditor";
import { clock } from "@/lib/format";
import { usePlayer, usePlayerState } from "@/lib/player";
import { cn } from "@/lib/utils";

// A vertical time track next to the transcript while correcting. Time runs downwards. Every
// block (what one person says until the other speaks) is a bar in the lane of its speaker,
// on top of the recording's waveform, so you see where speech really starts and stops. Blocks
// that overlap in time share their lane side by side. Pick a block, then drag the border
// between it and its neighbour (or nudge it word by word): the words in between change
// speaker, and every move can be listened to.

const GUTTER = 44; // px, time labels
const LANE = 108; // px per speaker lane
const GAP = 8;
export const RAIL_WIDTH = GUTTER + 2 * LANE + GAP + 4;
const MIN_PPS = 3;
const MAX_PPS = 60;
const LISTEN_S = 1.6;

interface W {
  ti: number;
  wi: number;
  s: number;
  e: number;
}

interface Block {
  key: string;
  who: string;
  role: string;
  name: string;
  /** id of the paragraph you typed in, if this block is one */
  ins?: number;
  start: number;
  end: number;
  words: W[];
  lane: 0 | 1;
  col: number;
  cols: number;
}

interface Peaks {
  rate: number;
  values: Uint8Array;
}

function usePps(): [number, (n: number) => void] {
  const [pps, set] = useState(() => {
    try {
      const n = Number(localStorage.getItem("interis.rail.pps"));
      return n >= MIN_PPS && n <= MAX_PPS ? n : 8;
    } catch {
      return 8;
    }
  });
  return [
    pps,
    (n) => {
      set(n);
      try {
        localStorage.setItem("interis.rail.pps", String(n));
      } catch {
        /* private window: not remembered */
      }
    },
  ];
}

/** Blocks of the transcript as corrected so far (a word given to another speaker counts for that speaker). */
export function buildBlocks(d: InterviewDetail): Block[] {
  const names = new Map(d.speakers.map((s) => [s.label, s]));
  const blocks: Block[] = [];
  for (let ti = 0; ti < d.turns.length; ti++) {
    const turn = d.turns[ti];
    for (let wi = 0; wi < turn.words.length; wi++) {
      const w = turn.words[wi];
      if (w.t.trim() === "") continue; // deleted word
      const who = w.sp ?? turn.speaker ?? "?";
      const last = blocks[blocks.length - 1];
      const word = { ti, wi, s: w.s, e: w.e };
      // a paragraph you inserted is a block of its own: it neither joins the words before it nor takes the ones after
      if (last && last.who === who && last.ins === turn.ins) {
        last.words.push(word);
        last.end = Math.max(last.end, w.e);
      } else {
        const sp = names.get(who);
        blocks.push({
          key: `${ti}:${wi}`,
          ins: turn.ins,
          who,
          role: sp?.role ?? "unknown",
          name: sp?.display_name || who,
          start: w.s,
          end: w.e,
          words: [word],
          lane: sp?.role === "interviewer" ? 0 : 1,
          col: 0,
          cols: 1,
        });
      }
    }
  }
  // blocks that overlap in time within a lane stand side by side
  for (const lane of [0, 1]) {
    const inLane = blocks.filter((b) => b.lane === lane).sort((a, b) => a.start - b.start);
    let group: Block[] = [];
    let groupEnd = -1;
    const flush = () => {
      const cols = Math.max(1, ...group.map((b) => b.col + 1));
      group.forEach((b) => (b.cols = cols));
      group = [];
    };
    const colEnds: number[] = [];
    for (const b of inLane) {
      if (b.start >= groupEnd) {
        flush();
        colEnds.length = 0;
      }
      let c = colEnds.findIndex((end) => end <= b.start);
      if (c < 0) c = colEnds.length;
      colEnds[c] = b.end;
      b.col = c;
      group.push(b);
      groupEnd = Math.max(groupEnd, b.end);
    }
    flush();
  }
  return blocks;
}

/** How many of the words of two neighbouring blocks stay with the upper one when the border is at time t. */
function splitAt(words: W[], t: number): number {
  let k = 0;
  for (const w of words) if ((w.s + w.e) / 2 < t) k++;
  return Math.min(Math.max(k, 1), words.length - 1);
}

export function TimeRail({
  d,
  onChanged,
  play,
  scrollText,
  draft,
  onDraft,
  onEditInsert,
}: {
  d: InterviewDetail;
  onChanged: () => void;
  play: (start: number, end?: number) => void;
  scrollText: (turn: number) => void;
  /** the paragraph being typed in: shown as a dashed bar whose edges can be dragged */
  draft: Draft | null;
  onDraft: (patch: Partial<Draft>) => void;
  onEditInsert: (turn: number) => void;
}) {
  const { fail, notify } = useFeedback();
  const player = usePlayer();
  const ps = usePlayerState();
  const [pps, setPps] = usePps();
  const [peaks, setPeaks] = useState<Peaks | "missing" | "running" | null>(null);
  const [anchor, setAnchor] = useState<{ ti: number; wi: number } | null>(null);
  const [follow, setFollow] = useState(true);
  const [drag, setDrag] = useState<{ t: number; moved: number } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [viewH, setViewH] = useState(600);
  const hovering = useRef(false);
  const dragging = useRef<{ x: number; y: number; k0: number; words: W[]; side: "top" | "bottom"; k: number } | null>(null);

  const blocks = useMemo(() => buildBlocks(d), [d]);
  const draftEdge = useRef<"start" | "end" | null>(null);
  const draftLane = draft && d.speakers.find((x) => x.label === draft.speaker)?.role === "interviewer" ? 0 : 1;
  const duration = useMemo(() => d.parts.reduce((m, p) => Math.max(m, p.offset_s + p.duration_s), 0) || (blocks.at(-1)?.end ?? 0), [d.parts, blocks]);
  const height = Math.ceil((duration + 4) * pps);
  const playing = ps.id === d.id;

  const selIndex = anchor ? blocks.findIndex((b) => b.words.some((w) => w.ti === anchor.ti && w.wi === anchor.wi)) : -1;
  const sel = selIndex >= 0 ? blocks[selIndex] : null;
  const above = selIndex > 0 ? blocks[selIndex - 1] : null;
  const below = selIndex >= 0 && selIndex < blocks.length - 1 ? blocks[selIndex + 1] : null;
  // the border between two recorded blocks moves by giving words to the other speaker; a paragraph
  // you typed in has its own times (edit it)
  const canMoveTop = !!(sel && above && sel.ins === undefined && above.ins === undefined);
  const canMoveBottom = !!(sel && below && sel.ins === undefined && below.ins === undefined);

  // ---- waveform: made once per recording by a background job, then loaded
  const loadPeaks = useCallback(async () => {
    try {
      const r = await api<{ status: string; rate?: number; peaks?: string }>("GET", `/api/interviews/${enc(d.id)}/peaks`);
      if (r.status === "ready" && r.peaks && r.rate) {
        const bin = atob(r.peaks);
        const values = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) values[i] = bin.charCodeAt(i);
        setPeaks({ rate: r.rate, values });
      } else if (r.status === "running") setPeaks("running");
      else {
        setPeaks("running");
        await api("POST", `/api/interviews/${enc(d.id)}/peaks`);
      }
    } catch {
      setPeaks("missing"); // the timeline works without it
    }
  }, [d.id]);

  useEffect(() => {
    void loadPeaks();
  }, [loadPeaks]);
  useEffect(() => {
    if (peaks !== "running") return;
    const t = setInterval(loadPeaks, 3000);
    return () => clearInterval(t);
  }, [peaks, loadPeaks]);

  // ---- drawing the waveform and the time scale for the visible part only
  const draw = useCallback(() => {
    const c = canvas.current;
    const sc = scroller.current;
    if (!c || !sc) return;
    const dpr = window.devicePixelRatio || 1;
    const w = RAIL_WIDTH;
    if (c.width !== w * dpr || c.height !== viewH * dpr) {
      c.width = w * dpr;
      c.height = viewH * dpr;
    }
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, viewH);
    const color = getComputedStyle(c).color;
    const top = sc.scrollTop;
    if (peaks && typeof peaks === "object") {
      const cx = GUTTER + (w - GUTTER) / 2;
      const half = (w - GUTTER) / 2 - 4;
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.4;
      for (let y = 0; y < viewH; y++) {
        const a = Math.floor(((top + y) / pps) * peaks.rate);
        const b = Math.max(a + 1, Math.floor(((top + y + 1) / pps) * peaks.rate));
        let m = 0;
        for (let i = a; i < b && i < peaks.values.length; i++) if (peaks.values[i] > m) m = peaks.values[i];
        if (m) ctx.fillRect(cx - (m / 255) * half, y, (m / 255) * half * 2, 1);
      }
    }
    // time scale
    const step = pps >= 30 ? 5 : pps >= 12 ? 10 : pps >= 6 ? 30 : 60;
    ctx.globalAlpha = 0.5;
    ctx.font = "10px ui-monospace, monospace";
    ctx.textBaseline = "top";
    for (let t = Math.floor(top / pps / step) * step; t * pps < top + viewH; t += step) {
      const y = t * pps - top;
      ctx.fillRect(GUTTER - 4, y, 4, 1);
      ctx.fillText(clock(t), 2, y + 1);
    }
    ctx.globalAlpha = 1;
  }, [peaks, pps, viewH]);

  useEffect(() => {
    const sc = scroller.current;
    if (!sc) return;
    setViewH(sc.clientHeight);
    const ro = new ResizeObserver(() => setViewH(sc.clientHeight));
    ro.observe(sc);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    draw();
  }, [draw, height]);

  const scrollTo = useCallback(
    (t: number, where = 0.3) => {
      const sc = scroller.current;
      if (sc) sc.scrollTop = Math.max(0, t * pps - viewH * where);
    },
    [pps, viewH],
  );

  const draftKey = draft ? `${draft.id ?? "new"}:${draft.at}` : null;
  useEffect(() => {
    if (draft) scrollTo(draft.start, 0.35);
    // only when a draft is opened, not while its edges move
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  // ---- the track follows the playhead, and follows the text when it is scrolled
  useEffect(() => {
    if (!playing || !ps.playing || !follow || dragging.current || hovering.current) return;
    const sc = scroller.current;
    if (!sc) return;
    const y = ps.time * pps;
    if (y < sc.scrollTop + viewH * 0.1 || y > sc.scrollTop + viewH * 0.7) scrollTo(ps.time);
  }, [ps.time, ps.playing, playing, follow, pps, viewH, scrollTo]);

  useEffect(() => {
    let timer = 0;
    const on = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (hovering.current || dragging.current || (playing && ps.playing)) return;
        const rows = document.querySelectorAll<HTMLElement>('[id^="t-"]');
        for (const el of rows) {
          if (el.getBoundingClientRect().bottom > 140) {
            const ti = Number(el.id.slice(2));
            if (d.turns[ti]) scrollTo(d.turns[ti].start, 0.2);
            break;
          }
        }
      }, 120);
    };
    window.addEventListener("scroll", on, { passive: true });
    return () => {
      window.removeEventListener("scroll", on);
      window.clearTimeout(timer);
    };
  }, [d.turns, scrollTo, playing, ps.playing]);

  // ---- moving the border between two blocks
  const commit = useCallback(
    async (upper: Block, lower: Block, k: number) => {
      const all = [...upper.words, ...lower.words];
      const k0 = upper.words.length;
      if (k === k0) return;
      const moved = k < k0 ? all.slice(k, k0) : all.slice(k0, k);
      const to = k < k0 ? lower.who : upper.who;
      const changes: { turn: number; first: number; last: number; speaker: string }[] = [];
      for (const w of moved) {
        const c = changes[changes.length - 1];
        if (c && c.turn === w.ti && c.last + 1 === w.wi) c.last = w.wi;
        else changes.push({ turn: w.ti, first: w.wi, last: w.wi, speaker: to });
      }
      try {
        await api("POST", `/api/interviews/${enc(d.id)}/speakers/batch`, { changes });
        onChanged();
      } catch (e) {
        fail(e);
      }
    },
    [d.id, onChanged, fail],
  );

  const markMoving = (words: W[], on: boolean) => {
    for (const w of words) document.querySelector(`[data-ti="${w.ti}"][data-wi="${w.wi}"]`)?.classList.toggle("drag-moved", on);
  };

  const timeAt = (clientY: number) => {
    const sc = scroller.current!;
    return (clientY - sc.getBoundingClientRect().top + sc.scrollTop) / pps;
  };

  const startDrag = (e: React.PointerEvent, side: "top" | "bottom") => {
    if (!sel) return;
    const upper = side === "top" ? above : sel;
    const lower = side === "top" ? sel : below;
    if (!upper || !lower) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const words = [...upper.words, ...lower.words];
    dragging.current = { x: e.clientX, y: e.clientY, k0: upper.words.length, words, side, k: upper.words.length };
    setDrag({ t: (upper.end + lower.start) / 2, moved: 0 });
  };

  const moveDrag = (e: React.PointerEvent) => {
    const g = dragging.current;
    if (!g) return;
    const sc = scroller.current!;
    const r = sc.getBoundingClientRect();
    if (e.clientY < r.top + 24) sc.scrollTop -= 10;
    else if (e.clientY > r.bottom - 24) sc.scrollTop += 10;
    const t = timeAt(e.clientY);
    const k = splitAt(g.words, t);
    if (k !== g.k) {
      markMoving(g.words, false);
      markMoving(k < g.k0 ? g.words.slice(k, g.k0) : g.words.slice(g.k0, k), true);
      g.k = k;
    }
    setDrag({ t, moved: Math.abs(k - g.k0) });
  };

  const endDrag = (upper: Block | null, lower: Block | null) => {
    const g = dragging.current;
    dragging.current = null;
    setDrag(null);
    if (!g) return;
    markMoving(g.words, false);
    // keep the selection on a word that does not change hands
    if (upper && lower) setAnchor(g.side === "top" ? { ti: lower.words.at(-1)!.ti, wi: lower.words.at(-1)!.wi } : { ti: upper.words[0].ti, wi: upper.words[0].wi });
    if (upper && lower && g.k !== g.k0) {
      void commit(upper, lower, g.k);
      const after = g.words[g.k]; // first word of the lower block now
      if (after) play(after.s - LISTEN_S, after.s + LISTEN_S);
    }
  };

  const nudge = async (side: "top" | "bottom", words: number) => {
    const upper = side === "top" ? above : sel;
    const lower = side === "top" ? sel : below;
    if (!upper || !lower) return;
    const all = [...upper.words, ...lower.words];
    const k = Math.min(Math.max(upper.words.length + words, 1), all.length - 1);
    if (k === upper.words.length) {
      notify("Weiter geht es nicht: jeder Block behält mindestens ein Wort");
      return;
    }
    // keep the selection on a word that does not change hands
    setAnchor(side === "top" ? { ti: lower.words.at(-1)!.ti, wi: lower.words.at(-1)!.wi } : { ti: upper.words[0].ti, wi: upper.words[0].wi });
    await commit(upper, lower, k);
    const at = all[k].s;
    play(at - LISTEN_S, at + LISTEN_S);
  };

  const moveDraftEdge = (e: React.PointerEvent) => {
    const edge = draftEdge.current;
    if (!edge || !draft) return;
    const t = Math.round(Math.max(0, timeAt(e.clientY)) * 10) / 10;
    if (edge === "start") onDraft({ start: Math.min(t, draft.end - 0.3) });
    else onDraft({ end: Math.max(t, draft.start + 0.3) });
  };
  const endDraftEdge = () => {
    const edge = draftEdge.current;
    draftEdge.current = null;
    if (edge && draft) play((edge === "start" ? draft.start : draft.end) - LISTEN_S, (edge === "start" ? draft.start : draft.end) + LISTEN_S);
  };

  const pick = (b: Block) => {
    const w = b.words[Math.floor(b.words.length / 2)];
    setAnchor({ ti: w.ti, wi: w.wi });
    scrollText(b.words[0].ti);
    play(b.start, b.end);
  };

  const borderTime = (a: Block | null, b: Block | null) => (a && b ? (a.end + b.start) / 2 : null);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon-sm" variant="outline" onClick={() => (playing ? player.toggle() : play(sel?.start ?? 0))} title="Abspielen/Pause (Leertaste)">
          {playing && ps.playing ? <PauseIcon /> : <PlayIcon />}
        </Button>
        <span className="font-mono text-xs tabular-nums">{clock(playing ? ps.time : (sel?.start ?? 0))}</span>
        <label className="text-muted-foreground ml-auto flex items-center gap-1 text-[11px]" title="Maßstab: Sekunden pro Bildschirmhöhe">
          grob
          <input type="range" min={MIN_PPS} max={MAX_PPS} value={pps} onChange={(e) => setPps(Number(e.target.value))} className="w-20" />
          fein
        </label>
      </div>
      <label className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
        <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
        Spur folgt der Wiedergabe
        {peaks === "running" && (
          <span className="ml-auto flex items-center gap-1">
            <LoaderIcon className="size-3 animate-spin" />
            Wellenform wird berechnet
          </span>
        )}
      </label>

      <div className="text-muted-foreground flex text-[11px] font-medium" style={{ paddingLeft: GUTTER }}>
        <span style={{ width: LANE }}>Interviewer</span>
        <span style={{ width: LANE, marginLeft: GAP }}>Befragte:r</span>
      </div>

      <div
        ref={scroller}
        className="bg-card relative min-h-0 flex-1 overflow-y-auto rounded-md border"
        style={{ width: RAIL_WIDTH }}
        onScroll={draw}
        onPointerEnter={() => (hovering.current = true)}
        onPointerLeave={() => (hovering.current = false)}
        onClick={(e) => {
          if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.bg) play(timeAt(e.clientY));
        }}
      >
        <div data-bg="1" className="relative" style={{ height, width: RAIL_WIDTH }}>
          <canvas ref={canvas} data-bg="1" className="text-foreground sticky top-0 block" style={{ width: RAIL_WIDTH, height: viewH }} />

          {blocks.map((b) => {
            const lane = GUTTER + b.lane * (LANE + GAP);
            const w = LANE / b.cols;
            const isSel = b === sel;
            const h = Math.max((b.end - b.start) * pps, 5);
            return (
              <button
                key={b.key}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  pick(b);
                }}
                title={`${b.name} · ${clock(b.start)}–${clock(b.end)} · ${b.words.length} Wörter`}
                className={cn(
                  "absolute overflow-hidden rounded-sm border text-left text-[10px] leading-tight",
                  b.role === "interviewer" ? "bg-question/20 border-question/70" : "bg-foreground/10 border-foreground/35",
                  b.ins !== undefined && "border-dashed",
                  isSel && "ring-primary z-10 ring-2",
                  playing && ps.time >= b.start && ps.time <= b.end && "brightness-95",
                )}
                style={{ top: b.start * pps, height: h, left: lane + b.col * w, width: w - 2 }}
              >
                {h > 16 && <span className="block truncate px-1 pt-0.5 font-medium">{clock(b.start)}</span>}
              </button>
            );
          })}

          {sel && (
            <>
              {canMoveTop && <Handle top={((above!.end + sel.start) / 2) * pps} label="Anfang" onDown={(e) => startDrag(e, "top")} onMove={moveDrag} onUp={() => endDrag(above, sel)} />}
              {canMoveBottom && <Handle top={((sel.end + below!.start) / 2) * pps} label="Ende" onDown={(e) => startDrag(e, "bottom")} onMove={moveDrag} onUp={() => endDrag(sel, below)} />}
            </>
          )}

          {draft && (
            <div
              className="border-primary bg-primary/15 pointer-events-none absolute z-20 rounded-sm border-2 border-dashed"
              style={{ top: draft.start * pps, height: Math.max((draft.end - draft.start) * pps, 6), left: GUTTER + draftLane * (LANE + GAP), width: LANE - 2 }}
            >
              <span className="bg-primary text-primary-foreground absolute -top-px left-0 rounded-br px-1 text-[9px] font-semibold">neu</span>
            </div>
          )}
          {draft &&
            (["start", "end"] as const).map((edge) => (
              <div
                key={edge}
                role="separator"
                aria-label={`Neuer Absatz: ${edge === "start" ? "Anfang" : "Ende"} verschieben`}
                title={edge === "start" ? "Anfang des neuen Absatzes ziehen" : "Ende des neuen Absatzes ziehen"}
                className="absolute z-30 -my-1.5 h-3 cursor-row-resize touch-none"
                style={{ top: (edge === "start" ? draft.start : draft.end) * pps, left: GUTTER + draftLane * (LANE + GAP), width: LANE - 2 }}
                onPointerDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  e.currentTarget.setPointerCapture(e.pointerId);
                  draftEdge.current = edge;
                }}
                onPointerMove={moveDraftEdge}
                onPointerUp={endDraftEdge}
                onPointerCancel={endDraftEdge}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="bg-primary mx-auto mt-1 h-1 w-10 rounded-full" />
              </div>
            ))}

          {drag && (
            <div className="bg-primary pointer-events-none absolute right-0 left-0 z-30 h-px" style={{ top: drag.t * pps }}>
              <span className="bg-primary text-primary-foreground absolute right-1 -translate-y-full rounded px-1 text-[10px]">
                {clock(drag.t)} · {drag.moved} {drag.moved === 1 ? "Wort wechselt" : "Wörter wechseln"}
              </span>
            </div>
          )}

          {playing && <div className="bg-destructive pointer-events-none absolute right-0 left-0 z-20 h-0.5 transition-[top] duration-300 ease-linear" style={{ top: ps.time * pps }} />}
        </div>
      </div>

      <div className="min-h-[6.5rem] space-y-1.5 text-xs">
        {sel ? (
          <>
            <p className="font-medium">
              {sel.name} · {clock(sel.start)}–{clock(sel.end)} <span className="text-muted-foreground font-normal">({sel.words.length} Wörter)</span>
            </p>
            {sel.ins !== undefined && (
              <p className="flex items-center gap-2">
                <span className="text-muted-foreground">von dir eingefügt</span>
                <Button size="xs" variant="outline" onClick={() => onEditInsert(sel.words[0].ti)}>
                  Bearbeiten
                </Button>
              </p>
            )}
            <div className="flex flex-wrap items-center gap-1">
              <Button size="xs" variant="outline" onClick={() => play(sel.start, sel.end)}>
                <PlayIcon />
                Block
              </Button>
              <Button size="xs" variant="outline" onClick={() => play(sel.start - 0.5, sel.start + LISTEN_S)}>
                Anfang
              </Button>
              <Button size="xs" variant="outline" onClick={() => play(sel.end - LISTEN_S, sel.end + 0.5)}>
                Ende
              </Button>
            </div>
            {canMoveTop && (
              <Nudge label="Anfang" at={borderTime(above, sel)} onLess={() => void nudge("top", -1)} onMore={() => void nudge("top", 1)} lessTitle="Ein Wort früher beginnen" moreTitle="Ein Wort später beginnen" />
            )}
            {canMoveBottom && (
              <Nudge label="Ende" at={borderTime(sel, below)} onLess={() => void nudge("bottom", -1)} onMore={() => void nudge("bottom", 1)} lessTitle="Ein Wort früher enden" moreTitle="Ein Wort später enden" />
            )}
          </>
        ) : (
          <p className="text-muted-foreground">Block anklicken: abspielen und seine Grenzen verschieben. In der freien Spur klicken spielt ab dort.</p>
        )}
      </div>
    </div>
  );
}

function Handle({ top, label, onDown, onMove, onUp }: { top: number; label: string; onDown: (e: React.PointerEvent) => void; onMove: (e: React.PointerEvent) => void; onUp: () => void }) {
  return (
    <div
      role="separator"
      aria-label={`${label} verschieben`}
      title={`${label} verschieben (ziehen)`}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      onClick={(e) => e.stopPropagation()}
      className="group absolute right-0 left-0 z-20 -my-2 flex h-4 cursor-row-resize touch-none items-center"
      style={{ top }}
    >
      <div className="bg-primary/70 group-hover:bg-primary h-0.5 w-full" />
      <div className="bg-primary text-primary-foreground absolute left-1 rounded px-1 text-[9px] font-semibold">{label}</div>
    </div>
  );
}

function Nudge({ label, at, onLess, onMore, lessTitle, moreTitle }: { label: string; at: number | null; onLess: () => void; onMore: () => void; lessTitle: string; moreTitle: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-muted-foreground w-12" title="Wort für Wort verschieben, mit Hörprobe">
        {label}
      </span>
      <Button size="icon-xs" variant="outline" onClick={onLess} title={lessTitle}>
        <ChevronUpIcon />
      </Button>
      <Button size="icon-xs" variant="outline" onClick={onMore} title={moreTitle}>
        <ChevronDownIcon />
      </Button>
      <span className="text-muted-foreground font-mono">{at !== null ? clock(at) : ""}</span>
    </div>
  );
}
