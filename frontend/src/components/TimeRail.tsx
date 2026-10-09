import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDownIcon, ChevronUpIcon, LoaderIcon, MoveVerticalIcon, PauseIcon, PlayIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, enc, type InterviewDetail } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { fmtTime, parseTime, type Draft } from "@/components/InsertEditor";
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
        last.start = Math.min(last.start, w.s); // word times of neighbouring segments can overlap a little
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

/** A time you can type exactly: the menu that opens on a right click on an edge. */
interface Precise {
  x: number;
  y: number;
  title: string;
  fields: { key: string; label: string; value: number }[];
  /** what the values will do, shown while typing (null: not valid) */
  info: (v: Record<string, number>) => string | null;
  apply: (v: Record<string, number>) => void | Promise<void>;
  listen: (v: Record<string, number>) => void;
}

function PreciseMenu({ menu, onClose }: { menu: Precise; onClose: () => void }) {
  const [texts, setTexts] = useState(() => Object.fromEntries(menu.fields.map((f) => [f.key, fmtTime(f.value)])));
  const values = Object.fromEntries(menu.fields.map((f) => [f.key, parseTime(texts[f.key])])) as Record<string, number | null>;
  const ok = Object.values(values).every((v) => v !== null);
  const info = ok ? menu.info(values as Record<string, number>) : null;
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    first.current?.select();
    const away = (e: MouseEvent) => !(e.target as HTMLElement).closest("[data-precise]") && onClose();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [onClose]);
  const go = async () => {
    if (!ok || info === null) return;
    await menu.apply(values as Record<string, number>);
    onClose();
  };
  return (
    <div
      data-precise
      className="bg-popover text-popover-foreground fixed z-50 grid w-64 gap-2 rounded-md border p-3 text-xs shadow-lg"
      style={{ left: Math.min(menu.x, window.innerWidth - 270), top: Math.min(menu.y, window.innerHeight - 220) }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <p className="font-medium">{menu.title}</p>
      {menu.fields.map((f, i) => (
        <label key={f.key} className="grid gap-1">
          <span className="text-muted-foreground">{f.label} (min:s.zehntel, z. B. 3:07.4)</span>
          <input
            ref={i === 0 ? first : undefined}
            className="bg-background h-8 w-full rounded-md border px-2 font-mono text-sm"
            value={texts[f.key]}
            aria-invalid={values[f.key] === null}
            onChange={(e) => setTexts({ ...texts, [f.key]: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && void go()}
          />
        </label>
      ))}
      <p className={cn("min-h-4", info === null ? "text-destructive" : "text-muted-foreground")}>{ok ? (info ?? "Dieser Wert ist nicht möglich.") : "Zeit z. B. 3:07.4 oder 187,4"}</p>
      <div className="flex gap-1">
        <Button size="xs" disabled={!ok || info === null} onClick={() => void go()}>
          Übernehmen
        </Button>
        <Button size="xs" variant="outline" disabled={!ok || info === null} onClick={() => menu.listen(values as Record<string, number>)}>
          <PlayIcon />
          Hörprobe
        </Button>
        <Button size="xs" variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
      </div>
    </div>
  );
}

interface FreeDrag {
  key: string; // "draft" or "ins:<id>"
  part: "start" | "end" | "move";
  t0: number;
  start0: number;
  end0: number;
  start: number;
  end: number;
  moved: boolean;
}

const MIN_LEN = 0.3;
const round1 = (t: number) => Math.round(t * 10) / 10;

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
  const [edit, setEdit] = useState(false); // resize mode: nothing is played, edges and boxes can be moved
  const [drag, setDrag] = useState<{ t: number; moved: number } | null>(null);
  const [ghost, setGhost] = useState<{ key: string; start: number; end: number } | null>(null);
  const [menu, setMenu] = useState<Precise | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const headLabel = useRef<HTMLSpanElement>(null);
  const [viewH, setViewH] = useState(600);
  const hovering = useRef(false);
  const dragging = useRef<{ k0: number; words: W[]; k: number } | null>(null);
  const freeDrag = useRef<FreeDrag | null>(null);
  const suppressClick = useRef(false);

  const blocks = useMemo(() => buildBlocks(d), [d]);
  const duration = useMemo(() => d.parts.reduce((m, p) => Math.max(m, p.offset_s + p.duration_s), 0) || (blocks.at(-1)?.end ?? 0), [d.parts, blocks]);
  const height = Math.ceil((duration + 4) * pps);
  const playing = ps.id === d.id;
  const draftLane = draft && d.speakers.find((x) => x.label === draft.speaker)?.role === "interviewer" ? 0 : 1;
  useEffect(() => setGhost(null), [d]); // the saved values arrive with the reloaded transcript

  /** a block's times, with the box you are dragging right now */
  const span = (b: Block) => (b.ins !== undefined && ghost?.key === `ins:${b.ins}` ? { start: ghost.start, end: ghost.end } : { start: b.start, end: b.end });

  const selIndex = anchor ? blocks.findIndex((b) => b.words.some((w) => w.ti === anchor.ti && w.wi === anchor.wi)) : -1;
  const sel = selIndex >= 0 ? blocks[selIndex] : null;
  const above = selIndex > 0 ? blocks[selIndex - 1] : null;
  const below = selIndex >= 0 && selIndex < blocks.length - 1 ? blocks[selIndex + 1] : null;
  // the border between two recorded blocks moves by giving words to the other speaker; a paragraph
  // you typed in has its own times
  const movable = (a: Block | null, b: Block | null) => !!(a && b && a.ins === undefined && b.ins === undefined);
  const canMoveTop = !!(sel && movable(above, sel));
  const canMoveBottom = !!(sel && movable(sel, below));

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

  // ---- the playhead reads the audio's own clock every frame (the state updates only a few times a
  // second), and the track follows it
  useEffect(() => {
    const line = head.current;
    if (!line) return;
    if (!playing) {
      line.style.display = "none";
      return;
    }
    let raf = 0;
    const tick = () => {
      const t = player.now();
      if (t !== null) {
        line.style.display = "block";
        line.style.top = `${t * pps}px`;
        if (headLabel.current) headLabel.current.textContent = fmtTime(t);
        const sc = scroller.current;
        if (sc && follow && ps.playing && !dragging.current && !freeDrag.current && !hovering.current) {
          const y = t * pps;
          if (y < sc.scrollTop + viewH * 0.1 || y > sc.scrollTop + viewH * 0.7) scrollTo(t);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, ps.playing, follow, pps, viewH, player, scrollTo]);

  useEffect(() => {
    let timer = 0;
    const on = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (hovering.current || dragging.current || freeDrag.current || (playing && ps.playing)) return;
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

  // ---- moving the border between two recorded blocks: words change speaker
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
  const autoScroll = (clientY: number) => {
    const sc = scroller.current!;
    const r = sc.getBoundingClientRect();
    if (clientY < r.top + 24) sc.scrollTop -= 10;
    else if (clientY > r.bottom - 24) sc.scrollTop += 10;
  };

  const startBorder = (e: React.PointerEvent, upper: Block, lower: Block) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    const words = [...upper.words, ...lower.words];
    dragging.current = { k0: upper.words.length, words, k: upper.words.length };
    setDrag({ t: (upper.end + lower.start) / 2, moved: 0 });
  };

  const moveBorder = (e: React.PointerEvent) => {
    const g = dragging.current;
    if (!g) return;
    autoScroll(e.clientY);
    const t = timeAt(e.clientY);
    const k = splitAt(g.words, t);
    if (k !== g.k) {
      markMoving(g.words, false);
      markMoving(k < g.k0 ? g.words.slice(k, g.k0) : g.words.slice(g.k0, k), true);
      g.k = k;
    }
    setDrag({ t, moved: Math.abs(k - g.k0) });
  };

  const endBorder = (upper: Block, lower: Block) => {
    const g = dragging.current;
    dragging.current = null;
    setDrag(null);
    if (!g) return;
    markMoving(g.words, false);
    // keep the selection on a word that does not change hands
    if (sel === upper) setAnchor({ ti: upper.words[0].ti, wi: upper.words[0].wi });
    else if (sel === lower) setAnchor({ ti: lower.words.at(-1)!.ti, wi: lower.words.at(-1)!.wi });
    if (g.k !== g.k0) void commit(upper, lower, g.k);
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
    setAnchor(side === "top" ? { ti: lower.words.at(-1)!.ti, wi: lower.words.at(-1)!.wi } : { ti: upper.words[0].ti, wi: upper.words[0].wi });
    await commit(upper, lower, k);
    if (!edit) play(all[k].s - LISTEN_S, all[k].s + LISTEN_S);
  };

  // ---- paragraphs you typed in (saved or being typed): move the box, drag an edge
  const saveInsert = useCallback(
    async (id: number, start: number, end: number) => {
      try {
        await api("PUT", `/api/interviews/${enc(d.id)}/inserts/${id}`, { start, end });
        onChanged();
      } catch (e) {
        fail(e);
        setGhost(null);
      }
    },
    [d.id, onChanged, fail],
  );

  const startFree = (e: React.PointerEvent, key: string, part: FreeDrag["part"], start: number, end: number) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    freeDrag.current = { key, part, t0: timeAt(e.clientY), start0: start, end0: end, start, end, moved: false };
  };

  const moveFree = (e: React.PointerEvent) => {
    const g = freeDrag.current;
    if (!g) return;
    autoScroll(e.clientY);
    const dt = timeAt(e.clientY) - g.t0;
    let start = g.start0;
    let end = g.end0;
    if (g.part === "start") start = Math.min(Math.max(0, round1(g.start0 + dt)), g.end0 - MIN_LEN);
    else if (g.part === "end") end = Math.max(round1(g.end0 + dt), g.start0 + MIN_LEN);
    else {
      start = Math.max(0, round1(g.start0 + dt));
      end = start + (g.end0 - g.start0);
    }
    if (Math.abs(dt) > 0.05) g.moved = true;
    g.start = start;
    g.end = end;
    if (g.key === "draft") onDraft({ start, end });
    else setGhost({ key: g.key, start, end });
  };

  const endFree = () => {
    const g = freeDrag.current;
    freeDrag.current = null;
    if (!g) return;
    if (g.moved && g.part === "move") {  // the click that follows a dragged box is not a selection
      suppressClick.current = true;
      setTimeout(() => (suppressClick.current = false), 0);
    }
    if (g.moved && g.key !== "draft") void saveInsert(Number(g.key.slice(4)), g.start, g.end);
    else if (g.key !== "draft") setGhost(null);
  };

  // ---- exact values: right click on an edge
  const askBorder = (e: React.MouseEvent, upper: Block, lower: Block) => {
    e.preventDefault();
    e.stopPropagation();
    const all = [...upper.words, ...lower.words];
    const k0 = upper.words.length;
    setMenu({
      x: e.clientX,
      y: e.clientY,
      title: `Grenze ${upper.name} → ${lower.name}`,
      fields: [{ key: "t", label: "Zeit der Grenze", value: (upper.end + lower.start) / 2 }],
      info: (v) => {
        const k = splitAt(all, v.t);
        const n = Math.abs(k - k0);
        return n === 0 ? "Keine Änderung" : `${n} ${n === 1 ? "Wort wechselt" : "Wörter wechseln"} · Grenze rastet bei ${fmtTime(all[k - 1].e)}–${fmtTime(all[k].s)} ein`;
      },
      apply: async (v) => {
        setAnchor(sel === upper ? { ti: upper.words[0].ti, wi: upper.words[0].wi } : sel === lower ? { ti: lower.words.at(-1)!.ti, wi: lower.words.at(-1)!.wi } : anchor);
        await commit(upper, lower, splitAt(all, v.t));
      },
      listen: (v) => play(v.t - LISTEN_S, v.t + LISTEN_S),
    });
  };

  const askFree = (e: React.MouseEvent, key: string, part: "start" | "end", name: string, start: number, end: number) => {
    e.preventDefault();
    e.stopPropagation();
    const field = part === "start" ? { key: "t", label: "Anfang", value: start } : { key: "t", label: "Ende", value: end };
    setMenu({
      x: e.clientX,
      y: e.clientY,
      title: `${part === "start" ? "Anfang" : "Ende"} von ${name}`,
      fields: [field],
      info: (v) => {
        const s = part === "start" ? v.t : start;
        const en = part === "end" ? v.t : end;
        if (s < 0 || en - s < MIN_LEN) return null;
        if (en - s > 600) return null;
        if (en > duration + 5) return null;
        return `Dauer ${(en - s).toFixed(1)} s`;
      },
      apply: (v) => {
        const s = part === "start" ? v.t : start;
        const en = part === "end" ? v.t : end;
        if (key === "draft") onDraft({ start: s, end: en });
        else return saveInsert(Number(key.slice(4)), s, en);
      },
      listen: (v) => play(v.t - LISTEN_S, v.t + LISTEN_S),
    });
  };

  const pick = (b: Block) => {
    const w = b.words[Math.floor(b.words.length / 2)];
    setAnchor({ ti: w.ti, wi: w.wi });
    scrollText(b.words[0].ti);
    if (!edit) play(b.start, b.end);
  };

  const borderTime = (a: Block | null, b: Block | null) => (a && b ? (a.end + b.start) / 2 : null);
  const selSpan = sel ? span(sel) : null;

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon-sm" variant="outline" onClick={() => (playing ? player.toggle() : play(sel?.start ?? 0))} title="Abspielen/Pause (Leertaste)">
          {playing && ps.playing ? <PauseIcon /> : <PlayIcon />}
        </Button>
        <span className="font-mono text-xs tabular-nums">{clock(playing ? ps.time : (sel?.start ?? 0))}</span>
        <Button
          size="sm"
          variant={edit ? "default" : "outline"}
          aria-pressed={edit}
          onClick={() => setEdit(!edit)}
          title="Größe ändern: Kanten und Boxen ziehen, ohne dass etwas abgespielt wird"
        >
          <MoveVerticalIcon />
          Größe ändern
        </Button>
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
      {edit && (
        <p className="bg-primary/10 text-foreground rounded-md px-2 py-1 text-[11px] leading-snug">
          <b>Größe ändern</b>, es wird nichts abgespielt. Kanten ziehen; eingefügte Absätze lassen sich auch als ganze Box verschieben. <b>Rechtsklick auf eine Kante</b>: genaue Zeit eingeben.
        </p>
      )}

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
          if (!edit && (e.target === e.currentTarget || (e.target as HTMLElement).dataset.bg)) play(timeAt(e.clientY));
        }}
      >
        <div data-bg="1" className="relative" style={{ height, width: RAIL_WIDTH }}>
          <canvas ref={canvas} data-bg="1" className="text-foreground sticky top-0 block" style={{ width: RAIL_WIDTH, height: viewH }} />

          {blocks.map((b) => {
            const lane = GUTTER + b.lane * (LANE + GAP);
            const w = LANE / b.cols;
            const isSel = b === sel;
            const { start, end } = span(b);
            const h = Math.max((end - start) * pps, 5);
            const typed = b.ins !== undefined;
            const key = `ins:${b.ins}`;
            return (
              <button
                key={b.key}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (suppressClick.current) {
                    suppressClick.current = false;
                    return;
                  }
                  pick(b);
                }}
                onPointerDown={edit && typed ? (e) => startFree(e, key, "move", b.start, b.end) : undefined}
                onPointerMove={edit && typed ? moveFree : undefined}
                onPointerUp={edit && typed ? endFree : undefined}
                onPointerCancel={edit && typed ? endFree : undefined}
                title={`${b.name} · ${fmtTime(start)}–${fmtTime(end)} · ${b.words.length} Wörter`}
                className={cn(
                  "absolute overflow-hidden rounded-sm border text-left text-[10px] leading-tight",
                  b.role === "interviewer" ? "bg-question/20 border-question/70" : "bg-foreground/10 border-foreground/35",
                  typed && "border-dashed",
                  edit && typed && "cursor-move touch-none",
                  isSel && "ring-primary z-10 ring-2",
                  playing && ps.time >= start && ps.time <= end && "brightness-95",
                )}
                style={{ top: start * pps, height: h, left: lane + b.col * w, width: w - 2 }}
              >
                {h > 16 && <span className="block truncate px-1 pt-0.5 font-medium">{clock(start)}</span>}
              </button>
            );
          })}

          {/* resize mode: every border between two recorded blocks, and the edges of typed-in boxes */}
          {edit &&
            blocks.slice(0, -1).map((a, i) => {
              const b = blocks[i + 1];
              if (!movable(a, b)) return null;
              const t = (a.end + b.start) / 2;
              return (
                <Handle
                  key={`${a.key}|${b.key}`}
                  top={t * pps}
                  label={fmtTime(t)}
                  title="Grenze verschieben (ziehen) · Rechtsklick: genaue Zeit"
                  onDown={(e) => startBorder(e, a, b)}
                  onMove={moveBorder}
                  onUp={() => endBorder(a, b)}
                  onMenu={(e) => askBorder(e, a, b)}
                />
              );
            })}
          {edit &&
            blocks
              .filter((b) => b.ins !== undefined)
              .map((b) => {
                const key = `ins:${b.ins}`;
                const { start, end } = span(b);
                const lane = GUTTER + b.lane * (LANE + GAP);
                return (["start", "end"] as const).map((part) => (
                  <EdgeTab
                    key={`${key}:${part}`}
                    part={part}
                    time={part === "start" ? start : end}
                    top={(part === "start" ? start : end) * pps}
                    left={lane}
                    title={`${part === "start" ? "Anfang" : "Ende"} ziehen · Rechtsklick: genaue Zeit`}
                    onDown={(e) => startFree(e, key, part, b.start, b.end)}
                    onMove={moveFree}
                    onUp={endFree}
                    onMenu={(e) => askFree(e, key, part, b.name, start, end)}
                  />
                ));
              })}

          {draft && (
            <div
              className={cn("border-primary bg-primary/15 absolute z-20 rounded-sm border-2 border-dashed", edit ? "cursor-move touch-none" : "pointer-events-none")}
              style={{ top: draft.start * pps, height: Math.max((draft.end - draft.start) * pps, 6), left: GUTTER + draftLane * (LANE + GAP), width: LANE - 2 }}
              onPointerDown={edit ? (e) => startFree(e, "draft", "move", draft.start, draft.end) : undefined}
              onPointerMove={edit ? moveFree : undefined}
              onPointerUp={edit ? endFree : undefined}
              onPointerCancel={edit ? endFree : undefined}
            >
              <span className="bg-primary text-primary-foreground absolute -top-px left-0 rounded-br px-1 text-[9px] font-semibold">neu</span>
            </div>
          )}
          {draft &&
            (["start", "end"] as const).map((part) => (
              <EdgeTab
                key={part}
                part={part}
                time={part === "start" ? draft.start : draft.end}
                top={(part === "start" ? draft.start : draft.end) * pps}
                left={GUTTER + draftLane * (LANE + GAP)}
                title={`Neuer Absatz: ${part === "start" ? "Anfang" : "Ende"} ziehen · Rechtsklick: genaue Zeit`}
                onDown={(e) => startFree(e, "draft", part, draft.start, draft.end)}
                onMove={moveFree}
                onUp={endFree}
                onMenu={(e) => askFree(e, "draft", part, "neuer Absatz", draft.start, draft.end)}
              />
            ))}

          {drag && (
            <div className="bg-primary pointer-events-none absolute right-0 left-0 z-30 h-px" style={{ top: drag.t * pps }}>
              <span className="bg-primary text-primary-foreground absolute right-1 -translate-y-full rounded px-1 text-[10px]">
                {fmtTime(drag.t)} · {drag.moved} {drag.moved === 1 ? "Wort wechselt" : "Wörter wechseln"}
              </span>
            </div>
          )}

          <div ref={head} className="bg-destructive pointer-events-none absolute right-0 left-0 z-20 hidden h-0.5">
            <span ref={headLabel} className="bg-destructive absolute left-0 -translate-y-full rounded-tr px-1 font-mono text-[9px] text-white" />
          </div>
        </div>
      </div>
      {menu && <PreciseMenu menu={menu} onClose={() => setMenu(null)} />}

      <div className="min-h-[6.5rem] space-y-1.5 text-xs">
        {sel && selSpan ? (
          <>
            <p className="font-medium">
              {sel.name} · {fmtTime(selSpan.start)}–{fmtTime(selSpan.end)} <span className="text-muted-foreground font-normal">({sel.words.length} Wörter)</span>
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
              <Button size="xs" variant="outline" onClick={() => play(selSpan.start, selSpan.end)}>
                <PlayIcon />
                Block
              </Button>
              <Button size="xs" variant="outline" onClick={() => play(selSpan.start - 0.5, selSpan.start + LISTEN_S)}>
                Anfang
              </Button>
              <Button size="xs" variant="outline" onClick={() => play(selSpan.end - LISTEN_S, selSpan.end + 0.5)}>
                Ende
              </Button>
            </div>
            {canMoveTop && (
              <Nudge label="Anfang" at={borderTime(above, sel)} onLess={() => void nudge("top", -1)} onMore={() => void nudge("top", 1)} lessTitle="Ein Wort früher beginnen" moreTitle="Ein Wort später beginnen" />
            )}
            {canMoveBottom && (
              <Nudge label="Ende" at={borderTime(sel, below)} onLess={() => void nudge("bottom", -1)} onMore={() => void nudge("bottom", 1)} lessTitle="Ein Wort früher enden" moreTitle="Ein Wort später enden" />
            )}
            {sel.ins === undefined && !canMoveTop && !canMoveBottom && <p className="text-muted-foreground">Dieser Block hat keinen aufgenommenen Nachbarn: seine Zeiten ergeben sich aus den Wörtern.</p>}
          </>
        ) : (
          <p className="text-muted-foreground">Block anklicken: abspielen. „Größe ändern“ einschalten, um Grenzen und Boxen zu verschieben, ohne abzuspielen.</p>
        )}
      </div>
    </div>
  );
}

/** The border between two recorded blocks: a line across both lanes with its time. */
function Handle({
  top,
  label,
  title,
  onDown,
  onMove,
  onUp,
  onMenu,
}: {
  top: number;
  label: string;
  title: string;
  onDown: (e: React.PointerEvent) => void;
  onMove: (e: React.PointerEvent) => void;
  onUp: () => void;
  onMenu: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      role="separator"
      aria-label="Grenze verschieben"
      title={title}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      onContextMenu={onMenu}
      onClick={(e) => e.stopPropagation()}
      className="group absolute right-0 left-0 z-20 -my-2 flex h-4 cursor-row-resize touch-none items-center"
      style={{ top }}
    >
      <div className="bg-primary/70 group-hover:bg-primary h-0.5 w-full" />
      <div className="bg-primary text-primary-foreground absolute left-1 rounded px-1 font-mono text-[9px] font-semibold">{label}</div>
    </div>
  );
}

/** A tab on the outside of the top or bottom edge of a box with free times, with the exact time on it. */
function EdgeTab({
  part,
  time,
  top,
  left,
  title,
  onDown,
  onMove,
  onUp,
  onMenu,
}: {
  part: "start" | "end";
  time: number;
  top: number;
  left: number;
  title: string;
  onDown: (e: React.PointerEvent) => void;
  onMove: (e: React.PointerEvent) => void;
  onUp: () => void;
  onMenu: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      role="separator"
      aria-label={`${part === "start" ? "Anfang" : "Ende"} verschieben`}
      title={title}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
      onContextMenu={onMenu}
      onClick={(e) => e.stopPropagation()}
      className="absolute z-30 flex h-4 cursor-row-resize touch-none items-center justify-center"
      style={{ top: part === "start" ? top - 16 : top, left, width: LANE - 2 }}
    >
      <div className="bg-primary text-primary-foreground flex items-center gap-1 rounded px-1.5 py-px font-mono text-[9px] font-semibold shadow">
        <span aria-hidden>{part === "start" ? "▲" : "▼"}</span>
        {fmtTime(time)}
      </div>
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
      <span className="text-muted-foreground font-mono">{at !== null ? fmtTime(at) : ""}</span>
    </div>
  );
}
