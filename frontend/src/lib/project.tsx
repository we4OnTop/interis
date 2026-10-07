import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api, type InterviewRow, type ProjectDetail } from "./api";
import type { PlayerSource } from "./player";

// The open project, reloaded on demand and polled while transcriptions are running.
// `dataVersion` increases whenever a job finishes, so views showing transcripts refetch.

interface ProjectCtx {
  detail: ProjectDetail | null;
  error: string | null;
  reload: () => Promise<void>;
  dataVersion: number;
  bump: () => void;
  source: (id: string) => PlayerSource;
  interview: (id: string) => InterviewRow | undefined;
}

const Ctx = createContext<ProjectCtx | null>(null);

const active = (d: ProjectDetail | null) =>
  !!d?.interviews.some((iv) => iv.job && (iv.job.status === "queued" || iv.job.status === "running"));

export function ProjectProvider({ pid, children }: { pid: number; children: ReactNode }) {
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const finished = useRef<string>("");

  const reload = useCallback(async () => {
    try {
      const d = await api<ProjectDetail>("GET", `/api/projects/${pid}`);
      // a job finished since the last poll -> transcripts/analysis changed
      const done = d.interviews.map((iv) => `${iv.id}:${iv.job?.id}:${iv.job?.status}`).join("|");
      if (finished.current && done !== finished.current) setDataVersion((v) => v + 1);
      finished.current = done;
      setDetail(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pid]);

  useEffect(() => {
    setDetail(null);
    finished.current = "";
    void reload();
  }, [reload]);

  const polling = active(detail);
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => void reload(), 2500);
    return () => clearInterval(t);
  }, [polling, reload]);

  const value: ProjectCtx = {
    detail,
    error,
    reload,
    dataVersion,
    bump: () => setDataVersion((v) => v + 1),
    source: (id) => ({ id, parts: detail?.interviews.find((i) => i.id === id)?.parts ?? [] }),
    interview: (id) => detail?.interviews.find((i) => i.id === id),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useProject = () => useContext(Ctx)!;
