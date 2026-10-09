import { useEffect, useState } from "react";

// Hash-based routes (no router library):
//   #/                         projects
//   #/p/<pid>                  project: by question (combined)
//   #/p/<pid>/columns          project: side by side (one column per interview)
//   #/p/<pid>/workflow         project: workflow status per interview
//   #/p/<pid>/extract          project: extracts per question and interview
//   #/p/<pid>/setup            project: guide + interviews
//   #/p/<pid>/i/<id>?t=<turn>  transcript
export type Route =
  | { page: "projects" }
  | { page: "system" }
  | { page: "questions"; pid: number; code: string | null }
  | { page: "columns"; pid: number }
  | { page: "workflow"; pid: number }
  | { page: "extract"; pid: number }
  | { page: "setup"; pid: number; tab: string | null }
  | { page: "interview"; pid: number; id: string; turn: number | null };

export function parseRoute(hash: string): Route {
  const [path, query] = hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query || "");
  const parts = (path || "/").split("/").filter(Boolean);
  if (parts[0] === "system") return { page: "system" };
  if (parts[0] !== "p" || !parts[1] || Number.isNaN(Number(parts[1]))) return { page: "projects" };
  const pid = Number(parts[1]);
  if (parts[2] === "columns") return { page: "columns", pid };
  if (parts[2] === "workflow") return { page: "workflow", pid };
  if (parts[2] === "extract") return { page: "extract", pid };
  if (parts[2] === "setup") return { page: "setup", pid, tab: params.get("tab") };
  if (parts[2] === "i" && parts[3]) {
    const t = params.get("t");
    return { page: "interview", pid, id: decodeURIComponent(parts[3]), turn: t === null ? null : Number(t) };
  }
  return { page: "questions", pid, code: params.get("q") };
}

export const href = {
  projects: () => "#/",
  system: () => "#/system",
  questions: (pid: number, code?: string | null) => `#/p/${pid}${code ? `?q=${encodeURIComponent(code)}` : ""}`,
  columns: (pid: number) => `#/p/${pid}/columns`,
  workflow: (pid: number) => `#/p/${pid}/workflow`,
  extract: (pid: number) => `#/p/${pid}/extract`,
  setup: (pid: number, tab?: string) => `#/p/${pid}/setup${tab ? `?tab=${tab}` : ""}`,
  interview: (pid: number, id: string, turn?: number | null) =>
    `#/p/${pid}/i/${encodeURIComponent(id)}${turn === undefined || turn === null ? "" : `?t=${turn}`}`,
};

export function navigate(to: string, replace = false) {
  if (replace) history.replaceState(null, "", to);
  else location.hash = to;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
