import { useCallback, useEffect, useMemo, useState } from "react";
import { FlaskConicalIcon, LoaderIcon, PlayIcon, SaveIcon, StarIcon, Trash2Icon, XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, type SettingsInfo, type TranscriptionSettings, type Trial, type TrialResult, type TrialSteps } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { clock, MODEL_LABEL, STAGE_LABEL } from "@/lib/format";
import { usePlayer } from "@/lib/player";
import { useProject } from "@/lib/project";
import { cn } from "@/lib/utils";

const BUILTIN = "builtin";

/** One line describing settings, used for presets, trials and jobs. */
export function settingsSummary(s: Partial<TranscriptionSettings>): string {
  return [
    s.model === "whisper-large-v3-turbo" ? "turbo" : "large-v3",
    s.compute_type === "float32" ? "float32" : null,
    s.beam_size && s.beam_size !== 5 ? `Beam ${s.beam_size}` : null,
    s.room_mic ? "Raummikrofon" : null,
    s.dereverb ? `Hall ↓ (${s.wpe_taps}/${s.wpe_delay}/${s.wpe_iterations})` : null,
    s.vad_threshold != null ? `VAD ${s.vad_threshold}` : null,
    s.speakers === 0 ? "Sprecher auto" : s.speakers && s.speakers !== 2 ? `${s.speakers} Sprecher` : null,
    s.min_duration_off != null ? `Pausen ${s.min_duration_off} s` : null,
    s.sentence_level ? "Sprecher pro Satz" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step,
  placeholder,
  help,
}: {
  id: string;
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min: number;
  max: number;
  step: number;
  placeholder?: string;
  help: string;
}) {
  return (
    <div className="grid content-start gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        className="w-32"
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? null : Math.min(max, Math.max(min, Number(raw))));
        }}
      />
      <p className="text-muted-foreground text-xs">{help}</p>
    </div>
  );
}

function parseClock(text: string): number | null {
  const parts = text.trim().split(":").map(Number);
  if (!parts.length || parts.some((n) => Number.isNaN(n) || n < 0)) return null;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

export function TranscriptionTab() {
  const { detail } = useProject();
  const { notify, fail, confirm } = useFeedback();
  const [info, setInfo] = useState<SettingsInfo | null>(null);
  const [selected, setSelected] = useState<string>(BUILTIN);
  const [form, setForm] = useState<TranscriptionSettings | null>(null);
  const [newName, setNewName] = useState("");
  const [trials, setTrials] = useState<Trial[]>([]);
  const [compare, setCompare] = useState<number[]>([]);
  const audioIds = detail!.interviews.filter((i) => i.has_audio).map((i) => i.id);
  const [interview, setInterview] = useState(audioIds[0] ?? "");
  const [from, setFrom] = useState("5:00");
  const [length, setLength] = useState("180");
  const [label, setLabel] = useState("");

  const loadSettings = useCallback(async (keep?: string) => {
    const s = await api<SettingsInfo>("GET", "/api/transcription/settings");
    setInfo(s);
    const pick = keep ?? String(s.presets.find((p) => p.is_default)?.id ?? BUILTIN);
    const preset = s.presets.find((p) => String(p.id) === pick);
    setSelected(preset ? pick : BUILTIN);
    setForm({ ...s.builtin, ...(preset?.options ?? {}) });
  }, []);

  const loadTrials = useCallback(async () => {
    const ids = new Set(detail!.interviews.map((i) => i.id));
    const all = await api<Trial[]>("GET", "/api/trials");
    const mine = all.filter((t) => ids.has(t.options.interview));
    setTrials(mine);
    // nothing shown yet: open the newest finished result
    setCompare((c) => {
      const kept = c.filter((id) => mine.some((t) => t.id === id && t.has_result));
      const newest = mine.find((t) => t.has_result);
      return kept.length || !newest ? kept : [newest.id];
    });
  }, [detail]);

  useEffect(() => {
    loadSettings().catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const busy = trials.some((t) => t.status === "queued" || t.status === "running");
  useEffect(() => {
    loadTrials().catch(fail);
    if (!busy) return;
    const timer = setInterval(() => loadTrials().catch(() => {}), 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, loadTrials]);

  if (!info || !form) return null;
  const preset = info.presets.find((p) => String(p.id) === selected) ?? null;
  const set = <K extends keyof TranscriptionSettings>(key: K, value: TranscriptionSettings[K]) => setForm({ ...form, [key]: value });
  const changed = JSON.stringify(form) !== JSON.stringify({ ...info.builtin, ...(preset?.options ?? {}) });

  const run = async (fn: () => Promise<unknown>, message: string, keep?: string) => {
    try {
      await fn();
      notify(message);
      await loadSettings(keep);
    } catch (e) {
      fail(e);
    }
  };

  const saveNew = async () => {
    try {
      const r = await api<{ id: number }>("POST", "/api/transcription/presets", { name: newName.trim(), settings: form });
      notify(`Einstellung „${newName.trim()}“ gespeichert`);
      setNewName("");
      await loadSettings(String(r.id));
    } catch (e) {
      fail(e);
    }
  };

  const startTrial = async () => {
    const start = parseClock(from);
    if (start === null) return fail(new Error("Start bitte als Minuten:Sekunden, z. B. 5:00"));
    try {
      await api("POST", "/api/trials", {
        interview,
        start,
        duration: Number(length),
        settings: form,
        label: label.trim() || (changed ? "" : (preset?.name ?? "Standard")),
      });
      notify("Probelauf eingereiht – das Ergebnis erscheint unten");
      await loadTrials();
    } catch (e) {
      fail(e);
    }
  };

  const toggleCompare = (id: number) =>
    setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-2)));

  return (
    <div className="space-y-4">
      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Transkriptions-Einstellungen</CardTitle>
          <CardDescription>
            Gelten für alle Projekte. Neue Transkriptionen verwenden die mit ★ markierte Einstellung:{" "}
            <span className="text-foreground font-medium">{info.default.preset}</span>. Erst mit einem Probelauf vergleichen, dann
            speichern.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-end gap-2">
            <div className="grid gap-1.5">
              <Label>Einstellung</Label>
              <Select
                value={selected}
                onValueChange={(v) => {
                  setSelected(v);
                  const p = info.presets.find((x) => String(x.id) === v);
                  setForm({ ...info.builtin, ...(p?.options ?? {}) });
                }}
              >
                <SelectTrigger className="w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={BUILTIN}>{info.presets.some((p) => p.is_default) ? "" : "★ "}Standard (eingebaut)</SelectItem>
                  {info.presets.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>
                      {p.is_default ? "★ " : ""}
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {preset && (
              <Button
                variant="outline"
                disabled={!changed}
                onClick={() =>
                  run(() => api("PUT", `/api/transcription/presets/${preset.id}`, { name: preset.name, settings: form }), "Gespeichert", selected)
                }
              >
                <SaveIcon />
                Speichern
              </Button>
            )}
            {(preset ? !preset.is_default : info.presets.some((p) => p.is_default)) && (
              <Button
                variant="outline"
                onClick={() =>
                  run(
                    () => api("PUT", "/api/transcription/default", { preset: preset?.id ?? null }),
                    `„${preset?.name ?? "Standard"}“ gilt jetzt für neue Transkriptionen`,
                    selected,
                  )
                }
              >
                <StarIcon />
                Für neue Transkriptionen verwenden
              </Button>
            )}
            {preset && (
              <Button
                variant="ghost"
                onClick={async () => {
                  if (await confirm({ title: `Einstellung „${preset.name}“ löschen?`, confirm: "Löschen", destructive: true }))
                    await run(() => api("DELETE", `/api/transcription/presets/${preset.id}`), "Gelöscht");
                }}
              >
                <Trash2Icon />
                Löschen
              </Button>
            )}
          </div>

          <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
            <div className="grid content-start gap-1.5">
              <Label>Modell</Label>
              <Select value={form.model} onValueChange={(v) => set("model", v)}>
                <SelectTrigger className="w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {info.models.map((m) => (
                    <SelectItem key={m} value={m}>
                      {MODEL_LABEL[m] ?? m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">turbo ist um ein Vielfaches schneller, aber etwas ungenauer.</p>
            </div>
            <div className="grid content-start gap-1.5">
              <Label>Rechengenauigkeit</Label>
              <Select value={form.compute_type} onValueChange={(v) => set("compute_type", v as TranscriptionSettings["compute_type"])}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="int8">int8 (schnell)</SelectItem>
                  <SelectItem value="float32">float32 (genauer)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">float32 rechnet ohne Rundung, ist aber deutlich langsamer.</p>
            </div>
            <NumberField
              id="beam"
              label="Suchbreite (Beam)"
              value={form.beam_size}
              onChange={(v) => set("beam_size", v ?? 5)}
              min={1}
              max={10}
              step={1}
              help="Wie viele Varianten pro Satz verglichen werden. 1 = am schnellsten, 5 = Standard."
            />
            <label className="flex items-start gap-2 text-sm">
              <Checkbox className="mt-0.5" checked={form.room_mic} onCheckedChange={(c) => set("room_mic", c === true)} />
              <span>
                Ein Mikrofon im Raum
                <span className="text-muted-foreground block text-xs">
                  Gleicht leise und laute Stimmen an, für Spracherkennung und Sprechertrennung. Gegen Hall hilft es nicht.
                </span>
              </span>
            </label>
            <div className="grid content-start gap-2 sm:col-span-2 lg:col-span-3 rounded-md border p-3">
              <label className="flex items-start gap-2 text-sm">
                <Checkbox className="mt-0.5" checked={form.dereverb} onCheckedChange={(c) => set("dereverb", c === true)} />
                <span>
                  Hall reduzieren (WPE, experimentell)
                  <span className="text-muted-foreground block text-xs">
                    Sagt den Nachhall aus dem eigenen Signal voraus und zieht ihn ab, vor Spracherkennung und Sprechertrennung. Ohne
                    trainiertes Modell. Mit einem Mikrofon ist der Effekt eher klein: unbedingt per Probelauf vergleichen. Kostet etwa
                    0,2–2 min Rechenzeit pro 10 min Audio, grob gemessen.
                  </span>
                </span>
              </label>
              {form.dereverb && (
                <div className="grid gap-x-6 gap-y-4 pl-6 sm:grid-cols-3">
                  <NumberField
                    id="taps"
                    label="Nachhall-Länge (Taps)"
                    value={form.wpe_taps}
                    onChange={(v) => set("wpe_taps", v ?? 10)}
                    min={3}
                    max={40}
                    step={1}
                    help="In Schritten zu 8 ms. 10 ≈ 80 ms (Standard); höher für hallige Räume, rechnet länger."
                  />
                  <NumberField
                    id="delay"
                    label="Verzögerung"
                    value={form.wpe_delay}
                    onChange={(v) => set("wpe_delay", v ?? 3)}
                    min={1}
                    max={8}
                    step={1}
                    help="So viele 8-ms-Schritte bleiben als direkter Schall unangetastet. 3 = Standard."
                  />
                  <NumberField
                    id="iter"
                    label="Durchläufe"
                    value={form.wpe_iterations}
                    onChange={(v) => set("wpe_iterations", v ?? 3)}
                    min={1}
                    max={10}
                    step={1}
                    help="Wie oft der Filter neu geschätzt wird. 3 = Standard; mehr bringt selten etwas."
                  />
                </div>
              )}
            </div>
            <NumberField
              id="vad"
              label="Sprach-Empfindlichkeit (VAD)"
              value={form.vad_threshold}
              onChange={(v) => set("vad_threshold", v)}
              min={0.1}
              max={0.9}
              step={0.05}
              placeholder={form.room_mic ? "auto: 0.35" : "auto: 0.5"}
              help="Niedriger findet leisere Sprache, aber auch eher Geräusche in Pausen. Leer = automatisch."
            />
            <NumberField
              id="speakers"
              label="Anzahl Sprecher"
              value={form.speakers}
              onChange={(v) => set("speakers", v ?? 2)}
              min={0}
              max={8}
              step={1}
              help="Die bekannte Zahl vorzugeben verringert Verwechslungen. 0 = automatisch erkennen."
            />
            <label className="flex items-start gap-2 text-sm">
              <Checkbox className="mt-0.5" checked={form.sentence_level} onCheckedChange={(c) => set("sentence_level", c === true)} />
              <span>
                Sprecher pro Satz
                <span className="text-muted-foreground block text-xs">
                  Ein Satz bekommt nur einen Sprecher (wer am längsten darin spricht). Verhindert Wechsel mitten im Satz, wo die
                  Sprechertrennung ihre Grenze leicht falsch setzt. Kurze Einwürfe („Ja.“) bleiben eigene Sätze.
                </span>
              </span>
            </label>
            <NumberField
              id="mdo"
              label="Sprecherpausen überbrücken (s)"
              value={form.min_duration_off}
              onChange={(v) => set("min_duration_off", v)}
              min={0}
              max={2}
              step={0.1}
              placeholder="Modell"
              help="Pausen eines Sprechers, die kürzer sind, gelten nicht als Wechsel: weniger zerstückelte Abschnitte, kurze Einwürfe („ja“) gehen eher unter."
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <Input className="w-64" placeholder="Name, z. B. Raummikrofon" value={newName} maxLength={60} onChange={(e) => setNewName(e.target.value)} />
            <Button variant="outline" disabled={!newName.trim()} onClick={saveNew}>
              <SaveIcon />
              Als neue Einstellung speichern
            </Button>
            {changed && <span className="text-muted-foreground text-xs">Geändert, nicht gespeichert – für den Probelauf nicht nötig</span>}
          </div>
        </CardContent>
      </Card>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Probelauf</CardTitle>
          <CardDescription>
            Transkribiert einen Ausschnitt mit den Einstellungen oben. Das Gespräch selbst, sein Transkript und deine Markierungen bleiben
            unverändert. Die Sprechertrennung ist auf einem kurzen Ausschnitt etwas unsicherer als auf dem ganzen Gespräch.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {audioIds.length === 0 ? (
            <p className="text-muted-foreground text-sm">Erst ein Gespräch mit Aufnahme hinzufügen.</p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid gap-1.5">
                <Label>Gespräch</Label>
                <Select value={interview} onValueChange={setInterview}>
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {audioIds.map((id) => (
                      <SelectItem key={id} value={id}>
                        {id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="from">ab (min:s)</Label>
                <Input id="from" className="w-24" value={from} onChange={(e) => setFrom(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label>Länge</Label>
                <Select value={length} onValueChange={setLength}>
                  <SelectTrigger className="w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[60, 180, 300, 600].map((s) => (
                      <SelectItem key={s} value={String(s)}>
                        {s / 60} min
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tlabel">Bezeichnung (optional)</Label>
                <Input id="tlabel" className="w-48" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} />
              </div>
              <Button onClick={startTrial} disabled={!interview}>
                <FlaskConicalIcon />
                Probelauf starten
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {trials.length > 0 && (
        <Card className="gap-4">
          <CardHeader>
            <CardTitle>Ergebnisse</CardTitle>
            <CardDescription>„Ansehen“ zeigt ein Ergebnis unten an; ein zweites dazunehmen, um beide nebeneinander zu vergleichen. Gelb = unsicher erkanntes Wort.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="divide-y rounded-md border">
              {trials.map((t) => (
                <TrialRow
                  key={t.id}
                  t={t}
                  checked={compare.includes(t.id)}
                  onCheck={() => toggleCompare(t.id)}
                  onApply={() => {
                    const { interview: _i, start: _s, duration: _d, label: _l, ...settings } = t.options;
                    setSelected(BUILTIN);
                    setForm({ ...info.builtin, ...settings });
                    notify("Einstellungen übernommen – zum Behalten als neue Einstellung speichern");
                  }}
                  onChanged={loadTrials}
                />
              ))}
            </ul>
            {compare.length > 0 && (
              <div className={cn("grid gap-4", compare.length === 2 && "lg:grid-cols-2")}>
                {compare
                  .map((id) => trials.find((t) => t.id === id))
                  .filter((t): t is Trial => !!t?.has_result)
                  .map((t) => (
                    <TrialView key={t.id} t={t} />
                  ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function TrialRow({
  t,
  checked,
  onCheck,
  onApply,
  onChanged,
}: {
  t: Trial;
  checked: boolean;
  onCheck: () => void;
  onApply: () => void;
  onChanged: () => Promise<void>;
}) {
  const { fail } = useFeedback();
  const active = t.status === "queued" || t.status === "running";
  const act = (fn: () => Promise<unknown>) => fn().then(onChanged).catch(fail);
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
      <Button
        size="sm"
        variant={checked ? "secondary" : "outline"}
        disabled={!t.has_result}
        aria-pressed={checked}
        onClick={onCheck}
        title={t.has_result ? undefined : "Erst wenn der Probelauf fertig ist"}
      >
        {checked ? "Angezeigt ✓" : "Ansehen"}
      </Button>
      <span className="font-mono text-xs">{t.options.interview}</span>
      <span className="text-muted-foreground text-xs">
        {clock(t.options.start)}–{clock(t.options.start + t.options.duration)}
      </span>
      <span className="min-w-0 flex-1">
        {t.options.label && <span className="mr-2 font-medium">{t.options.label}</span>}
        <span className="text-muted-foreground text-xs">{settingsSummary(t.options)}</span>
      </span>
      {active ? (
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <LoaderIcon className="size-3.5 animate-spin" />
          {t.status === "queued" ? "wartet" : `${STAGE_LABEL[(t.stage || "start").split(":")[0]] ?? t.stage} ${Math.round(t.progress * 100)} %`}
        </span>
      ) : t.status === "done" && t.elapsed_s != null ? (
        <Badge variant="outline" title="Rechenzeit / Audiolänge">
          {Math.round(t.elapsed_s)} s · Faktor {(t.elapsed_s / t.options.duration).toFixed(2)}×
        </Badge>
      ) : t.status !== "done" ? (
        <Badge variant="suggest" title={t.message}>
          {t.status === "cancelled" ? "abgebrochen" : "fehlgeschlagen"}
        </Badge>
      ) : null}
      {t.has_result && (
        <Button variant="ghost" size="sm" onClick={onApply} title="Diese Einstellungen oben übernehmen">
          Übernehmen
        </Button>
      )}
      {active ? (
        <Button variant="ghost" size="icon-sm" title="Abbrechen" onClick={() => act(() => api("POST", `/api/jobs/${t.id}/cancel`))}>
          <XIcon />
        </Button>
      ) : (
        <Button variant="ghost" size="icon-sm" title="Löschen" onClick={() => act(() => api("DELETE", `/api/trials/${t.id}`))}>
          <Trash2Icon />
        </Button>
      )}
    </li>
  );
}

function TrialView({ t }: { t: Trial }) {
  const { source } = useProject();
  const player = usePlayer();
  const { fail } = useFeedback();
  const [r, setR] = useState<TrialResult | null>(null);
  useEffect(() => {
    api<TrialResult>("GET", `/api/trials/${t.id}`).then(setR, fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t.id]);
  const roles = useMemo(() => new Map(r?.speakers.map((s, i) => [s.label, { role: s.role, i }]) ?? []), [r]);
  if (!r) return null;
  const offset = r.clip?.start_s ?? 0;
  const words = r.turns.reduce((n, turn) => n + turn.words.length, 0);
  const unsure = r.turns.reduce((n, turn) => n + turn.words.filter((w) => w.prob < 0.5).length, 0);
  return (
    <div className="min-w-0 space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium">{t.options.label || "Probelauf"}</span>
        <span className="text-muted-foreground text-xs">{settingsSummary(t.options)}</span>
      </div>
      <p className="text-muted-foreground text-xs">
        {words} Wörter, davon {unsure} unsicher · {r.speakers.length} Sprecher erkannt · {r.turns.length} Abschnitte
      </p>
      {r.steps && <StepsView id={t.id} steps={r.steps} length={r.duration_s} offset={offset} labels={r.speakers.map((s) => s.label)} />}
      <div className="max-h-[32rem] space-y-2 overflow-auto pr-1">
        {r.turns.map((turn, k) => {
          const who = turn.speaker ? roles.get(turn.speaker) : undefined;
          const name = who?.role === "interviewer" ? "Interviewer" : who?.role === "interviewee" ? "Befragte:r" : (turn.speaker ?? "?");
          return (
            <div key={k} className="flex gap-2 text-sm">
              <Button
                variant="ghost"
                size="icon-xs"
                className="mt-0.5 shrink-0"
                title="Abspielen"
                onClick={() => player.play(source(t.options.interview), offset + turn.start, offset + turn.end)}
              >
                <PlayIcon />
              </Button>
              <div className="min-w-0">
                <Badge variant={who?.i === 0 ? "question" : "linked"} className="mr-1.5">
                  {name}
                </Badge>
                <span className="text-muted-foreground mr-1.5 font-mono text-xs">{clock(offset + turn.start)}</span>
                {turn.words.map((w, j) => (
                  <span key={j} className={cn(w.prob < 0.5 && "rounded-sm bg-yellow-200/70 dark:bg-yellow-500/30")} title={`${Math.round(w.prob * 100)} %`}>
                    {w.text}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const STEP_NAME: [keyof TrialSteps["seconds"], string][] = [
  ["dereverb", "Hall reduzieren"],
  ["transcribe", "Spracherkennung"],
  ["align", "Wörter ausrichten"],
  ["diarize", "Sprechertrennung"],
  ["analyze", "Fragen erkennen"],
];
const SPEAKER_COLOR = ["bg-question", "bg-linked", "bg-suggest", "bg-muted-foreground"];

/** What each processing step of a trial did: the audio of every stage, run times, the raw recognition and who
 * speaks when, so the effect (and the cost) of a setting is visible. */
function StepsView({ id, steps, length, offset, labels }: { id: number; steps: TrialSteps; length: number; offset: number; labels: string[] }) {
  const total = Object.values(steps.seconds).reduce((a, b) => a + (b ?? 0), 0);
  const color = (spk: string) => SPEAKER_COLOR[Math.max(0, labels.indexOf(spk)) % SPEAKER_COLOR.length];
  const switches = steps.diarization.filter((s, i, all) => i > 0 && all[i - 1].speaker !== s.speaker).length;
  const share = labels.map((l) => [l, steps.diarization.filter((s) => s.speaker === l).reduce((a, s) => a + s.end - s.start, 0)] as const);
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">Schritte: anhören, Rechenzeit, Zwischenergebnisse</summary>
      <div className="mt-3 space-y-4">
        <section className="space-y-1.5">
          <h4 className="text-xs font-semibold tracking-wide uppercase">Audio je Schritt</h4>
          {steps.audio.map((a, i) => (
            <div key={a.file} className="flex flex-wrap items-center gap-2">
              <span className="w-48 text-xs">
                {a.label}
                {a.file === steps.heard_by_models && (
                  <span className="text-muted-foreground block">
                    ← hören Spracherkennung und Sprechertrennung{a.file.startsWith("03") ? "" : " und die Wort-Ausrichtung"}
                  </span>
                )}
                {/* levelling is only for recognition and diarization; alignment gets the stage before it */}
                {steps.heard_by_models.startsWith("03") && i === steps.audio.length - 2 && (
                  <span className="text-muted-foreground block">← hört die Wort-Ausrichtung</span>
                )}
              </span>
              <audio controls preload="none" className="h-8 max-w-full" src={`/api/trials/${id}/audio/${a.file}`} />
            </div>
          ))}
        </section>

        <section className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide uppercase">Rechenzeit</h4>
          <table className="text-xs">
            <tbody>
              {STEP_NAME.map(([key, name]) => (
                <tr key={key}>
                  <td className="pr-4">{name}</td>
                  <td className="text-right tabular-nums">
                    {steps.seconds[key] != null ? `${steps.seconds[key]} s` : <span className="text-muted-foreground">aus Zwischenspeicher / aus</span>}
                  </td>
                </tr>
              ))}
              <tr className="border-t font-medium">
                <td className="pr-4">gesamt</td>
                <td className="text-right tabular-nums">
                  {Math.round(total)} s · Faktor {(total / Math.max(length, 1)).toFixed(2)}×
                </td>
              </tr>
            </tbody>
          </table>
          <p className="text-muted-foreground text-xs">
            Faktor = Rechenzeit / Audiolänge. Schritte, deren Eingaben sich nicht geändert haben, kommen aus dem Zwischenspeicher und
            kosten nichts.
          </p>
        </section>

        <section className="space-y-1.5">
          <h4 className="text-xs font-semibold tracking-wide uppercase">Sprechertrennung: wer spricht wann</h4>
          <div className="bg-muted relative h-6 w-full overflow-hidden rounded">
            {steps.diarization.map((s, i) => (
              <div
                key={i}
                className={cn("absolute top-0 h-full opacity-80", color(s.speaker))}
                style={{ left: `${(s.start / length) * 100}%`, width: `${Math.max(((s.end - s.start) / length) * 100, 0.2)}%` }}
                title={`${s.speaker} ${clock(offset + s.start)}–${clock(offset + s.end)}`}
              />
            ))}
          </div>
          <p className="text-muted-foreground flex flex-wrap gap-3 text-xs">
            {share.map(([l, sec]) => (
              <span key={l} className="flex items-center gap-1">
                <span className={cn("inline-block size-2.5 rounded-sm", color(l))} />
                {l}: {Math.round(sec)} s
              </span>
            ))}
            <span>{switches} Wechsel</span>
            <span>{steps.diarization.filter((s) => s.end - s.start < 1).length} Abschnitte unter 1 s</span>
          </p>
        </section>

        <section className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide uppercase">Wörter ausrichten</h4>
          <p className="text-xs">
            {steps.aligned.aligned} von {steps.aligned.words} Wörtern zeitlich nachjustiert
            {steps.aligned.mean_shift_ms != null && `, im Mittel um ${steps.aligned.mean_shift_ms} ms verschoben`}.
          </p>
        </section>

        <section className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide uppercase">Spracherkennung roh (vor Sprechern)</h4>
          <div className="max-h-64 space-y-0.5 overflow-auto text-xs">
            {steps.recognised.map((s, i) => {
              const doubtful = s.avg_logprob < -0.8 || s.no_speech_prob > 0.5;
              return (
                <p key={i} className={cn(doubtful && "bg-yellow-200/60 dark:bg-yellow-500/25")} title={`Sicherheit (avg_logprob) ${s.avg_logprob} · keine Sprache ${s.no_speech_prob}`}>
                  <span className="text-muted-foreground mr-1.5 font-mono">{clock(offset + s.start)}</span>
                  {s.text}
                </p>
              );
            })}
          </div>
          <p className="text-muted-foreground text-xs">Gelb: unsicher erkannt oder vermutlich gar keine Sprache (mögliche Halluzination).</p>
        </section>
      </div>
    </details>
  );
}
