import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { enc } from "./api";
import { partAt, type TimelinePart } from "./format";

// One audio player for the whole app. Times are on the interview's joint timeline; for
// interviews recorded in several parts the right file is chosen automatically and playback
// continues with the next part at the end of one.

export interface PlayerSource {
  id: string;
  parts: TimelinePart[];
}

interface PlayerState {
  id: string | null;
  time: number; // joint timeline
  playing: boolean;
  part: number;
  parts: TimelinePart[];
}

interface PlayerControls {
  play: (src: PlayerSource, start: number, end?: number | null) => void;
  toggle: () => void;
  seek: (t: number) => void;
  skip: (delta: number) => void;
  stop: () => void;
}

const StateCtx = createContext<PlayerState>({ id: null, time: 0, playing: false, part: 0, parts: [] });
const ControlsCtx = createContext<PlayerControls | null>(null);

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const src = useRef<{ source: PlayerSource; part: number } | null>(null);
  const stopAt = useRef<number | null>(null);
  const [state, setState] = useState<PlayerState>({ id: null, time: 0, playing: false, part: 0, parts: [] });

  const offset = (part: number) => src.current?.source.parts[part]?.offset_s ?? 0;

  const load = useCallback((source: PlayerSource, part: number) => {
    const a = audio.current!;
    if (src.current?.source.id !== source.id || src.current.part !== part) {
      a.src = `/api/interviews/${enc(source.id)}/audio/${part}`;
    }
    src.current = { source, part };
  }, []);

  const seekTo = useCallback(
    (t: number, autoplay: boolean) => {
      const s = src.current;
      if (!s) return;
      const { part, local } = partAt(s.source.parts, t);
      load(s.source, part);
      const a = audio.current!;
      const go = () => {
        a.currentTime = local;
        if (autoplay) void a.play();
      };
      if (a.readyState >= 1) go();
      else a.addEventListener("loadedmetadata", go, { once: true });
    },
    [load],
  );

  useEffect(() => {
    const a = new Audio();
    a.preload = "metadata";
    audio.current = a;
    const update = () => {
      const s = src.current;
      if (!s) return;
      const t = offset(s.part) + a.currentTime;
      if (stopAt.current !== null && t >= stopAt.current) {
        a.pause();
        stopAt.current = null;
      }
      setState({ id: s.source.id, time: t, playing: !a.paused, part: s.part, parts: s.source.parts });
    };
    const ended = () => {
      const s = src.current;
      if (s && s.part + 1 < s.source.parts.length) {
        load(s.source, s.part + 1);
        void a.play();
      } else update();
    };
    a.addEventListener("timeupdate", update);
    a.addEventListener("play", update);
    a.addEventListener("pause", update);
    a.addEventListener("ended", ended);
    return () => {
      a.pause();
      a.removeAttribute("src");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const controls = useMemo<PlayerControls>(
    () => ({
      play: (source, start, end) => {
        src.current = src.current?.source.id === source.id ? { source, part: src.current.part } : null;
        if (!src.current) {
          src.current = { source, part: -1 };
        }
        stopAt.current = end ?? null;
        seekTo(Math.max(0, start - 0.15), true);
      },
      toggle: () => {
        const a = audio.current!;
        if (!src.current) return;
        if (a.paused) void a.play();
        else a.pause();
      },
      seek: (t) => {
        stopAt.current = null;
        seekTo(t, !audio.current!.paused);
      },
      skip: (delta) => {
        const s = src.current;
        if (!s) return;
        stopAt.current = null;
        seekTo(Math.max(0, offset(s.part) + audio.current!.currentTime + delta), !audio.current!.paused);
      },
      stop: () => {
        audio.current!.pause();
        src.current = null;
        setState({ id: null, time: 0, playing: false, part: 0, parts: [] });
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [seekTo],
  );

  return (
    <ControlsCtx.Provider value={controls}>
      <StateCtx.Provider value={state}>{children}</StateCtx.Provider>
    </ControlsCtx.Provider>
  );
}

export const usePlayer = () => useContext(ControlsCtx)!;
export const usePlayerState = () => useContext(StateCtx);
