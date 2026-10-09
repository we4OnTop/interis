import { useCallback, useEffect, useState } from "react";
import { ListChecksIcon, LoaderIcon, PlusIcon, WandSparklesIcon, XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, type ErrorRates, type TuneReport, type TuningState } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { clock, STAGE_LABEL } from "@/lib/format";
import { useProject } from "@/lib/project";
import { TurnPicker } from "@/pages/setup/TurnPicker";

const pct = (x: number) => `${(x * 100).toFixed(1).replace(".", ",")} %`;

const SETTING_LABEL: Record<string, string> = {
  sentence_level: "Sprecher pro Satz",
  min_duration_off: "Sprecherpausen überbrücken (s)",
  voice_margin: "Sätze nach Stimme zuordnen",
  glossary: "Gelernte Begriffe",
  vad_threshold: "Sprach-Empfindlichkeit",
  beam_size: "Suchbreite (Beam)",
  room_mic: "Raummikrofon",
  dereverb: "Hall reduzieren",
  compute_type: "Rechengenauigkeit",
};

function show(value: unknown): string {
  if (typeof value === "boolean") return value ? "an" : "aus";
  return value === null ? "automatisch" : String(value);
}

/** A stretch with its edges moved to whole speaker turns, and what it contains. */
interface Stretch {
  interview: string;
  start: number;
  end: number;
  turns: number;
  words: number;
  corrections: number;
  speaker_corrections: number;
  reviewed: boolean;
  begins: string;
  ends: string;
}

interface Row {
  interview: string;
  /** the picked stretch in seconds (before the edges are moved to whole blocks) */
  pick: { start: number; end: number } | null;
  stretch: Stretch | null;
  error: string | null;
}

const newRow = (interview: string): Row => ({ interview, pick: null, stretch: null, error: null });

export function TuningCard() {
  const { detail } = useProject();
  const { notify, fail } = useFeedback();
  const ready = detail!.interviews.filter((i) => i.transcribed && i.has_audio).map((i) => i.id);
  const [rows, setRows] = useState<Row[]>([newRow(ready[0] ?? "")]);
  const [budget, setBudget] = useState("60");
  const [state, setState] = useState<TuningState | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await api<TuningState>("GET", "/api/tuning"));
    } catch (e) {
      fail(e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const job = state?.job ?? null;
  const running = job?.status === "queued" || job?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [running, load]);

  const update = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const [picking, setPicking] = useState<number | null>(null);

  const pick = (i: number, start: number, end: number) => {
    update(i, { pick: { start, end }, stretch: null, error: null });
    api<Stretch>("POST", "/api/tuning/preview", { interview: rows[i].interview, start, end })
      .then((st) => update(i, { stretch: st }))
      .catch((e: Error) => update(i, { error: e.message }));
  };

  const windows = rows.map((r) => r.stretch);
  const valid = windows.every((w) => w !== null);

  const start = async () => {
    try {
      await api("POST", "/api/tuning", {
        windows: windows.map((w) => ({ interview: w!.interview, start: w!.start, end: w!.end })),
        budget_minutes: Number(budget) || null,
      });
      notify("Optimierung gestartet");
    } catch (e) {
      fail(e);
    }
    await load();
  };

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>Automatisch optimieren</CardTitle>
        <CardDescription>
          Dein korrigierter Text dient als Maßstab. Interis transkribiert die gewählten Ausschnitte mit verschiedenen Einstellungen neu (Hall,
          Raummikrofon, Sprecher pro Satz, Stimme, Beam, Genauigkeit, gelernte Begriffe …), misst falsche Wörter und falsch zugeordnete Sprecher
          und behält die beste Kombination. Sie wird als Einstellung „Optimiert …“ gespeichert und zum Standard. Wähle Ausschnitte, die du
          vollständig korrigiert hast (oder „Korrektur abgeschlossen“ gesetzt). Den Ausschnitt wählst du in einem Fenster mit dem korrigierten Transkript,
          Block für Block (ein Block endet, wenn die andere Person spricht); so beginnt und endet die Aufnahme nie mitten im Satz. Mit zwei oder mehr
          Ausschnitten wird das Ergebnis an einem geprüft, den die Suche nicht gesehen hat.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {ready.length === 0 ? (
          <p className="text-muted-foreground text-sm">Erst ein Gespräch mit Aufnahme transkribieren und korrigieren.</p>
        ) : (
          <>
            <div className="grid gap-3">
              {rows.map((r, i) => (
                <div key={i} className="grid gap-2 rounded-md border p-3">
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="grid gap-1.5">
                      <Label>Gespräch</Label>
                      <Select value={r.interview} onValueChange={(v) => update(i, { ...newRow(v) })} disabled={running}>
                        <SelectTrigger className="w-32">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ready.map((id) => (
                            <SelectItem key={id} value={id}>
                              {id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button variant="outline" disabled={running || !r.interview} onClick={() => setPicking(i)}>
                      <ListChecksIcon />
                      {r.stretch ? "Ausschnitt ändern …" : "Ausschnitt im Transkript wählen …"}
                    </Button>
                    {rows.length > 1 && !running && (
                      <Button variant="ghost" size="icon-xs" title="entfernen" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                        <XIcon />
                      </Button>
                    )}
                  </div>
                  <StretchInfo row={r} />
                </div>
              ))}
              {rows.length < 6 && !running && (
                <Button variant="outline" size="sm" className="w-fit" onClick={() => setRows([...rows, newRow(ready[0])])}>
                  <PlusIcon />
                  Weiteren Ausschnitt
                </Button>
              )}
            </div>
            {picking !== null && (
              <TurnPicker
                open
                interview={rows[picking].interview}
                current={rows[picking].stretch}
                onOpenChange={(o) => !o && setPicking(null)}
                onPick={(a, b) => pick(picking, a, b)}
              />
            )}
            <div className="flex flex-wrap items-end gap-4">
              <div className="grid gap-1.5">
                <Label htmlFor="tbudget">Höchstens (Minuten)</Label>
                <Input id="tbudget" className="w-28" inputMode="numeric" value={budget} disabled={running} onChange={(e) => setBudget(e.target.value.replace(/\D/g, ""))} />
              </div>
              <Button onClick={start} disabled={running || !valid}>
                <WandSparklesIcon />
                Optimierung starten
              </Button>
              {state && !state.has_profile && (
                <span className="text-muted-foreground text-xs">Ohne Stimmprofil („Stimme lernen“ im Transkript) wird die Zuordnung nach Stimme nicht mitgetestet.</span>
              )}
            </div>
          </>
        )}

        {running && job && (
          <div className="grid gap-1.5">
            <Progress value={job.progress * 100} />
            <p className="text-muted-foreground text-xs">
              {job.status === "queued" ? "wartet" : (STAGE_LABEL[job.stage.split(":")[0]] ?? job.stage)} … Jede Einstellung dauert etwa so lange wie die Transkription der Ausschnitte.
            </p>
          </div>
        )}
        {job?.status === "failed" && <p className="text-destructive text-sm whitespace-pre-wrap">{job.message}</p>}
        {state?.report && !running && <Report report={state.report} />}
      </CardContent>
    </Card>
  );
}

function StretchInfo({ row }: { row: Row }) {
  const st = row.stretch;
  if (row.error) return <p className="text-destructive text-xs">{row.error}</p>;
  if (!row.pick) return <p className="text-muted-foreground text-xs">Noch kein Ausschnitt gewählt.</p>;
  if (!st) return <LoaderIcon className="text-muted-foreground size-4 animate-spin" />;
  const unchecked = st.corrections + st.speaker_corrections === 0 && !st.reviewed;
  return (
    <div className="grid gap-1 text-xs">
      <p>
        <b>
          {clock(st.start)} – {clock(st.end)}
        </b>{" "}
        <span className="text-muted-foreground">
          · {st.turns} Blöcke · {st.words} Wörter ·{" "}
          {st.corrections} Wortkorrekturen · {st.speaker_corrections} Sprecherkorrekturen{st.reviewed ? " · Korrektur abgeschlossen" : ""}
        </span>
      </p>
      <p className="text-muted-foreground">
        Beginnt mit „{st.begins}“ und endet mit „{st.ends}“
      </p>
      {unchecked && <p className="text-destructive">In diesem Ausschnitt ist nichts korrigiert – er zählt nur als Maßstab, wenn du ihn durchgesehen hast.</p>}
    </div>
  );
}

function Rates({ label, r }: { label: string; r: ErrorRates }) {
  return (
    <div className="grid gap-0.5">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="text-sm">
        falsche Wörter <b>{pct(r.wer)}</b> · falsche Sprecher <b>{pct(r.speaker_error)}</b>
      </span>
    </div>
  );
}

function Report({ report }: { report: TuneReport }) {
  return (
    <div className="grid gap-3 rounded-md border p-4">
      <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
        Letztes Ergebnis ({report.windows.join(", ")})
        <Badge variant={report.held_out ? "linked" : "suggest"}>{report.held_out ? "an ungesehenem Ausschnitt geprüft" : "nicht an ungesehenen Daten geprüft"}</Badge>
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Rates label="vorher" r={report.baseline.validation} />
        <Rates label="nachher" r={report.best.validation} />
      </div>
      {report.improved ? (
        <ul className="text-muted-foreground list-disc pl-5 text-xs">
          {Object.entries(report.changed).map(([k, v]) => (
            <li key={k}>
              {SETTING_LABEL[k] ?? k}: {show(v)}
              {k === "glossary" && report.glossary ? ` (${report.glossary} Begriffe)` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-xs">Keine bessere Kombination gefunden – die Einstellungen sind unverändert.</p>
      )}
      {report.note && <p className="text-xs">{report.note}</p>}
      <p className="text-muted-foreground text-xs">
        {report.evaluations} Einstellungen probiert ({report.stopped === "converged" ? "bis keine Verbesserung mehr kam" : report.stopped}).
      </p>
    </div>
  );
}
