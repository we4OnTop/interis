import { useCallback, useEffect, useState } from "react";

import { api, type Compare } from "./api";
import { useFeedback } from "./feedback";
import { useProject } from "./project";

/** Comparison data of the open project; refetched when transcripts or decisions change. */
export function useCompare() {
  const { detail, dataVersion } = useProject();
  const { fail } = useFeedback();
  const pid = detail!.project.id;
  const [data, setData] = useState<Compare | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setData(await api<Compare>("GET", `/api/projects/${pid}/compare`));
      setError(null);
    } catch (e) {
      fail(e);
      setError(e instanceof Error ? e.message : String(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid]);

  useEffect(() => {
    void reload();
  }, [reload, dataVersion, detail?.guide_text]);

  return { data, reload, error };
}

/** Interviews hidden from the comparison (remembered per project in this browser). */
export function useHidden(pid: number) {
  const key = `interis.hidden.${pid}`;
  const [hidden, setHidden] = useState<Set<string>>(() => new Set(JSON.parse(localStorage.getItem(key) || "[]")));
  const toggle = (id: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      localStorage.setItem(key, JSON.stringify([...next]));
      return next;
    });
  return { hidden, toggle };
}

export function useStoredFlag(key: string, initial: boolean) {
  const [value, setValue] = useState(() => {
    const v = localStorage.getItem(key);
    return v === null ? initial : v === "1";
  });
  return [
    value,
    (v: boolean) => {
      localStorage.setItem(key, v ? "1" : "0");
      setValue(v);
    },
  ] as const;
}
