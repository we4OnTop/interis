import { useRef, useState } from "react";
import {
  AlertTriangleIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  FileAudioIcon,
  FileTextIcon,
  LoaderIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";

import { Hint } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api, ApiError, enc, type InterviewRow } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { bytes, clock, STAGE_LABEL, STAGES } from "@/lib/format";
import { useProject } from "@/lib/project";
import { href } from "@/lib/router";

import { AddInterviewDialog, AUDIO_ACCEPT, uploadParts } from "./AddInterviewDialog";

export function InterviewsTab() {
  const { detail, reload } = useProject();
  const { notify, fail } = useFeedback();
  const [adding, setAdding] = useState(false);
  const ivs = detail!.interviews;
  const mismatch = ivs.some((iv) => iv.guide_mismatch);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => setAdding(true)}>
          <PlusIcon />
          Gespräch hinzufügen
        </Button>
        {mismatch && (
          <Button
            variant="outline"
            onClick={async () => {
              try {
                const r = await api<{ reanalyze: number }>("POST", `/api/projects/${detail!.project.id}/reanalyze`);
                notify(`${r.reanalyze} Gespräch(e) werden mit dem aktuellen Leitfaden neu analysiert`);
                await reload();
              } catch (e) {
                fail(e);
              }
            }}
          >
            <RefreshCwIcon />
            Mit aktuellem Leitfaden neu analysieren
          </Button>
        )}
      </div>

      {ivs.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground py-6 text-sm">Noch keine Gespräche in diesem Projekt.</CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {ivs.map((iv) => (
            <InterviewCard key={iv.id} iv={iv} />
          ))}
        </div>
      )}
      <AddInterviewDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}

function JobStatus({ iv }: { iv: InterviewRow }) {
  const j = iv.job;
  if (j && j.status === "queued")
    return (
      <Badge variant="secondary">
        <LoaderIcon className="animate-spin" />
        {j.kind === "analyze" ? "Analyse wartet" : "wartet"}
        {j.queue_pos ? ` (Position ${j.queue_pos + 1})` : ""}
      </Badge>
    );
  if (j && j.status === "running") {
    if (j.kind === "analyze")
      return (
        <Badge variant="suggest">
          <LoaderIcon className="animate-spin" />
          Fragen werden neu erkannt
        </Badge>
      );
    const key = (j.stage || "start").split(":")[0];
    const step = STAGES.indexOf(key as (typeof STAGES)[number]);
    const overall = step >= 0 ? ((step + j.progress) / STAGES.length) * 100 : 0;
    return (
      <div className="w-full max-w-md space-y-1.5">
        <div className="flex items-center gap-2 text-sm">
          <LoaderIcon className="text-suggest size-4 animate-spin" />
          <span className="font-medium">
            {step >= 0 && `Schritt ${step + 1}/${STAGES.length}: `}
            {STAGE_LABEL[key] ?? key}
          </span>
          {j.progress > 0 && j.progress < 1 && <span className="text-muted-foreground">{Math.round(j.progress * 100)} %</span>}
          {j.started_at && (
            <span className="text-muted-foreground ml-auto text-xs">
              seit {new Date(j.started_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
        <Progress value={overall} />
      </div>
    );
  }
  if (j && j.status === "failed")
    return (
      <div className="text-destructive flex items-start gap-1.5 text-sm" title={j.message}>
        <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
        <span className="line-clamp-2">Fehler: {j.message.split("\n").pop()}</span>
      </div>
    );
  if (iv.transcribed && iv.parts_changed)
    return <Badge variant="suggest">Aufnahmen geändert – neu transkribieren</Badge>;
  if (iv.transcribed)
    return (
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="linked">fertig</Badge>
        {iv.guide_mismatch && <Badge variant="suggest">älterer Leitfaden</Badge>}
        {!iv.has_roles && <Badge variant="secondary">Rollen unklar</Badge>}
      </div>
    );
  if (j && j.status === "cancelled") return <Badge variant="secondary">abgebrochen</Badge>;
  return <Badge variant="outline">{iv.parts.length ? "bereit – noch nicht gestartet" : "noch keine Aufnahme"}</Badge>;
}

function InterviewCard({ iv }: { iv: InterviewRow }) {
  const { detail, reload } = useProject();
  const { notify, fail, confirm } = useFeedback();
  const addInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const j = iv.job;
  const busy = !!j && (j.status === "queued" || j.status === "running");
  const pid = detail!.project.id;

  const run = async (fn: () => Promise<unknown>, msg?: string) => {
    try {
      await fn();
      if (msg) notify(msg);
    } catch (e) {
      fail(e);
    } finally {
      await reload();
    }
  };

  const start = async () => {
    const model = (j?.kind === "transcribe" && j.options.model) || "whisper-large-v3";
    try {
      await api("POST", `/api/interviews/${enc(iv.id)}/transcribe`, { model });
      notify(`${iv.id}: Transkription eingereiht`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && iv.transcribed) {
        const ok = await confirm({
          title: `${iv.id} neu transkribieren?`,
          description:
            "Dabei entstehen neue Wortpositionen. Deine Arbeit an diesem Gespräch wird deshalb entfernt: Fragen-Zuordnungen, Verknüpfungen, Korrekturen, Glättungen, Begründungen, Extrakte und der Status „Korrektur abgeschlossen“.",
          confirm: "Neu transkribieren",
          destructive: true,
        });
        if (ok) await run(() => api("POST", `/api/interviews/${enc(iv.id)}/transcribe`, { model, discard_markings: true }), `${iv.id}: Transkription eingereiht`);
        return;
      }
      fail(e);
    } finally {
      await reload();
    }
  };

  const reorder = (i: number, d: number) => {
    const order = iv.parts.map((p) => p.idx);
    [order[i], order[i + d]] = [order[i + d], order[i]];
    void run(() => api("PUT", `/api/interviews/${enc(iv.id)}/parts`, { order }));
  };

  const canStart = !busy && iv.parts.length > 0 && (!iv.transcribed || iv.parts_changed || j?.status === "failed");

  return (
    <Card className="gap-3 py-4">
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-base font-semibold">{iv.id}</span>
          {iv.duration_s !== null && <span className="text-muted-foreground text-sm">{clock(iv.duration_s)}</span>}
          <div className="min-w-0 flex-1">
            <JobStatus iv={iv} />
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {iv.transcribed && (
              <Button asChild variant="outline" size="sm">
                <a href={href.interview(pid, iv.id)}>
                  <FileTextIcon />
                  Transkript
                </a>
              </Button>
            )}
            {canStart && (
              <Button size="sm" onClick={start}>
                {iv.transcribed ? <RotateCcwIcon /> : <PlayIcon />}
                {iv.transcribed ? "Neu transkribieren" : j?.status === "failed" ? "Erneut starten" : "Transkription starten"}
              </Button>
            )}
            {busy && (
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  const ok = await confirm({
                    title: `${iv.id}: Auftrag abbrechen?`,
                    description: "Bereits fertige Schritte bleiben zwischengespeichert und werden beim nächsten Start übersprungen.",
                    confirm: "Abbrechen",
                  });
                  if (ok) await run(() => api("POST", `/api/jobs/${j!.id}/cancel`), "Abgebrochen");
                }}
              >
                <SquareIcon />
                Abbrechen
              </Button>
            )}
            {!busy && (
              <Hint text="Gespräch aus Interis entfernen">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={async () => {
                    const ok = await confirm({
                      title: `${iv.id} entfernen?`,
                      description:
                        "Gelöscht werden: Transkript, Zwischenergebnisse, deine Markierungen und die hochgeladenen Kopien der Aufnahmen.\nDeine Originaldateien bleiben, wo sie sind.",
                      confirm: "Entfernen",
                      destructive: true,
                    });
                    if (ok) await run(() => api("DELETE", `/api/interviews/${enc(iv.id)}`), `${iv.id} entfernt`);
                  }}
                >
                  <Trash2Icon />
                </Button>
              </Hint>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {iv.parts.map((p, i) => (
            <div key={p.idx} className="bg-muted/50 flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
              <FileAudioIcon className="text-muted-foreground size-3.5" />
              <span className="font-medium">{iv.parts.length > 1 ? `Teil ${i + 1}` : "Aufnahme"}</span>
              <span className="text-muted-foreground">
                .{p.ext} · {bytes(p.size)}
                {p.duration_s !== null && ` · ${clock(p.duration_s)}`}
              </span>
              {!p.exists && <span className="text-destructive">fehlt!</span>}
              {!busy && iv.parts.length > 1 && (
                <>
                  <Button variant="ghost" size="icon-xs" className="size-5" disabled={i === 0} onClick={() => reorder(i, -1)} title="früher">
                    <ArrowUpIcon className="size-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="size-5"
                    disabled={i === iv.parts.length - 1}
                    onClick={() => reorder(i, 1)}
                    title="später"
                  >
                    <ArrowDownIcon className="size-3" />
                  </Button>
                </>
              )}
              {!busy && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="hover:text-destructive size-5"
                  title="Teil entfernen"
                  onClick={async () => {
                    const ok = await confirm({
                      title: `Teil ${i + 1} von ${iv.id} entfernen?`,
                      description: p.uploaded
                        ? "Die hochgeladene Kopie wird gelöscht. Danach muss das Gespräch neu transkribiert werden."
                        : "Die Datei selbst bleibt erhalten.",
                      confirm: "Entfernen",
                      destructive: true,
                    });
                    if (ok) await run(() => api("DELETE", `/api/interviews/${enc(iv.id)}/parts/${p.idx}`));
                  }}
                >
                  <XIcon className="size-3" />
                </Button>
              )}
            </div>
          ))}
          {!busy &&
            (uploading !== null ? (
              <span className="text-muted-foreground flex items-center gap-2 text-xs">
                <LoaderIcon className="size-3.5 animate-spin" /> lädt … {Math.round(uploading * 100)} %
              </span>
            ) : (
              <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={() => addInput.current?.click()}>
                <PlusIcon />
                Teil hinzufügen
              </Button>
            ))}
          <input
            ref={addInput}
            type="file"
            multiple
            accept={AUDIO_ACCEPT}
            hidden
            onChange={async (e) => {
              const files = Array.from(e.target.files ?? []).sort((a, b) => a.name.localeCompare(b.name, "de", { numeric: true }));
              e.target.value = "";
              if (!files.length) return;
              setUploading(0);
              await run(() => uploadParts(iv.id, files, (x) => setUploading(x)), "Hochgeladen");
              setUploading(null);
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
