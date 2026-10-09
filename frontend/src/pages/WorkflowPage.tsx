import { useCallback, useEffect, useState } from "react";
import { CheckIcon, CircleAlertIcon, LoaderIcon, MinusIcon } from "lucide-react";

import { LoadError } from "@/components/LoadError";
import { Badge } from "@/components/ui/badge";
import { api, type Workflow, type WorkflowInterview } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { useProject } from "@/lib/project";
import { href } from "@/lib/router";

// Column per step. The done flags come from the server (web/workflow.py); the column titles are the step titles.
// The guide step is project-wide and the export step has no state, so both are only described in the step cards.
// done: null = informational only (shows `info` instead of a check or dash)
const COLUMNS: { id: string; done: (iv: WorkflowInterview) => boolean | null; info?: (iv: WorkflowInterview) => string }[] = [
  { id: "transcribe", done: (iv) => iv.done.transcribe },
  { id: "correct", done: (iv) => iv.done.correct },
  { id: "smooth", done: (iv) => iv.done.smooth },
  { id: "assign", done: () => null, info: (iv) => `${iv.asked} gestellt · ${iv.unassigned} spontan` },
  // an interview that is not transcribed yet has nothing to explain
  { id: "explain", done: (iv) => (iv.transcribed ? iv.done.explain : null) },
  { id: "extract", done: (iv) => iv.done.extract },
];

export function WorkflowPage() {
  const { detail, dataVersion } = useProject();
  const { fail } = useFeedback();
  const pid = detail!.project.id;
  const [wf, setWf] = useState<Workflow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setWf(await api<Workflow>("GET", `/api/projects/${pid}/workflow`));
      setError(null);
    } catch (e) {
      fail(e);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pid, fail]);

  useEffect(() => {
    void load();
  }, [load, dataVersion, detail?.guide_text]);

  if (!wf)
    return error ? <LoadError message={error} onRetry={() => void load()} /> : <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 sm:p-6">
      <section className="space-y-3">
        <div>
          <h1 className="text-lg font-semibold">Ablauf</h1>
          <p className="text-muted-foreground text-sm">
            {wf.guide_questions > 0 ? (
              <>Leitfaden mit {wf.guide_questions} Fragen.</>
            ) : (
              <>
                Noch kein Leitfaden. <a className="underline" href={href.setup(pid)}>Leitfaden & Gespräche einrichten</a>
              </>
            )}
          </p>
        </div>
        <ol className="grid gap-3">
          {wf.steps.map((s, i) => (
            <li key={s.id} className="bg-card flex gap-4 rounded-lg border p-4">
              <span className="bg-primary text-primary-foreground grid size-7 shrink-0 place-items-center rounded-full text-sm font-semibold">
                {i + 1}
              </span>
              <div className="space-y-1">
                <h2 className="font-semibold">{s.title}</h2>
                <p className="text-muted-foreground text-sm leading-relaxed">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Stand je Gespräch</h2>
        {wf.interviews.length === 0 ? (
          <p className="text-muted-foreground text-sm">Noch keine Gespräche.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs font-semibold tracking-wide uppercase">
                <tr>
                  <th className="px-3 py-2">Gespräch</th>
                  {COLUMNS.map((c) => (
                    <th key={c.id} className="px-3 py-2 text-center">
                      {wf.steps.find((s) => s.id === c.id)?.title ?? c.id}
                    </th>
                  ))}
                  <th className="px-3 py-2">Hinweise</th>
                  <th className="px-3 py-2">Öffnen</th>
                </tr>
              </thead>
              <tbody>
                {wf.interviews.map((iv) => (
                  <tr key={iv.id} className="border-t align-top">
                    <td className="px-3 py-2 font-mono font-semibold">{iv.id}</td>
                    {COLUMNS.map((c) => {
                      const v = c.done(iv);
                      return (
                        <td key={c.id} className="px-3 py-2 text-center">
                          {v === null ? (
                            <span className="text-muted-foreground text-xs">{c.info ? c.info(iv) : "–"}</span>
                          ) : v ? (
                            <CheckIcon className="text-linked mx-auto size-4" aria-label="erledigt" />
                          ) : (
                            <MinusIcon className="text-muted-foreground mx-auto size-4" aria-label="offen" />
                          )}
                        </td>
                      );
                    })}
                    <td className="px-3 py-2">
                      <div className="flex flex-col items-start gap-1">
                        {iv.edits_stale && (
                          <Badge variant="suggest">
                            <CircleAlertIcon />
                            Analyse veraltet
                          </Badge>
                        )}
                        {iv.transcribed && iv.missing.length > 0 && (
                          <span className="text-xs">fehlt – begründen: {iv.missing.join(", ")}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-col gap-1 whitespace-nowrap">
                        <a className="underline" href={href.interview(pid, iv.id)}>
                          Transkript
                        </a>
                        <a className="underline" href={href.columns(pid)}>
                          Nebeneinander
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
