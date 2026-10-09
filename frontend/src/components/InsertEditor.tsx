import { useEffect, useRef, useState } from "react";
import { MinusIcon, PlayIcon, PlusIcon, Trash2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, enc, type Speaker } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";

/** A paragraph you type in, or one you typed in earlier (``id``). ``at`` is the place it gets. */
export interface Draft {
  id?: number;
  at: number;
  speaker: string;
  start: number;
  end: number;
  text: string;
}

const ROLE: Record<string, string> = { interviewer: "Interviewer", interviewee: "Befragte:r", unknown: "" };

/** 75.5 → "1:15.5" */
export function fmtTime(t: number): string {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

/** "1:15.5", "75.5" or "1:15" → seconds; null if invalid. */
export function parseTime(text: string): number | null {
  const m = text.trim().match(/^(?:(\d+):)?(\d+(?:[.,]\d+)?)$/);
  return m ? Number(m[1] ?? 0) * 60 + Number(m[2].replace(",", ".")) : null;
}

function TimeField({ label, value, onChange }: { label: string; value: number; onChange: (t: number) => void }) {
  const [text, setText] = useState(fmtTime(value));
  useEffect(() => setText(fmtTime(value)), [value]); // dragged in the time track
  const parsed = parseTime(text);
  return (
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <div className="flex items-center gap-1">
        <Button type="button" size="icon-xs" variant="outline" title="0,5 s früher" onClick={() => onChange(Math.max(0, value - 0.5))}>
          <MinusIcon />
        </Button>
        <Input
          className="h-7 w-20 text-center font-mono text-xs"
          value={text}
          aria-invalid={parsed === null}
          onChange={(e) => {
            setText(e.target.value);
            const t = parseTime(e.target.value);
            if (t !== null) onChange(t);
          }}
        />
        <Button type="button" size="icon-xs" variant="outline" title="0,5 s später" onClick={() => onChange(value + 0.5)}>
          <PlusIcon />
        </Button>
      </div>
    </div>
  );
}

export function InsertEditor({
  interview,
  speakers,
  draft,
  onChange,
  onClose,
  onSaved,
  play,
}: {
  interview: string;
  speakers: Speaker[];
  draft: Draft;
  onChange: (d: Draft) => void;
  onClose: () => void;
  onSaved: (at: number) => void;
  play: (start: number, end?: number) => void;
}) {
  const { confirm, fail, notify } = useFeedback();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => area.current?.focus(), []);

  const valid = draft.text.trim() !== "" && draft.end > draft.start;
  const words = draft.text.trim() ? draft.text.trim().split(/\s+/).length : 0;

  const save = async (force = false) => {
    setBusy(true);
    setError(null);
    try {
      const body = { speaker: draft.speaker, start: draft.start, end: draft.end, text: draft.text };
      if (draft.id === undefined) await api("POST", `/api/interviews/${enc(interview)}/inserts`, { ...body, at: draft.at });
      else await api("PUT", `/api/interviews/${enc(interview)}/inserts/${draft.id}`, { ...body, force });
      notify(draft.id === undefined ? "Absatz eingefügt – „Analyse aktualisieren“ übernimmt ihn in die Fragen-Erkennung" : "Gespeichert");
      onSaved(draft.at);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && draft.id !== undefined) {
        if (await confirm({ title: "Neuen Text speichern?", description: `${e.message}.`, confirm: "Ja, speichern", destructive: true })) {
          setBusy(false);
          return save(true);
        }
      } else setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const remove = async (force = false): Promise<void> => {
    try {
      await api("DELETE", `/api/interviews/${enc(interview)}/inserts/${draft.id}?force=${force}`);
      notify("Absatz entfernt");
      onSaved(draft.at);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        if (await confirm({ title: "Absatz trotzdem entfernen?", description: `${e.message}.`, confirm: "Entfernen", destructive: true })) return remove(true);
      } else fail(e);
    }
  };

  return (
    <div className="bg-muted/40 mx-4 my-2 grid gap-3 rounded-lg border border-dashed p-3" data-selbar>
      <p className="text-sm font-medium">{draft.id === undefined ? "Neuer Absatz" : "Eingefügten Absatz bearbeiten"}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1">
          <Label className="text-xs">Wer spricht?</Label>
          <Select value={draft.speaker} onValueChange={(v) => onChange({ ...draft, speaker: v })}>
            <SelectTrigger className="h-8 w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {speakers.map((s) => (
                <SelectItem key={s.label} value={s.label}>
                  {[s.display_name || s.label, ROLE[s.role]].filter((x, i, a) => x && a.indexOf(x) === i).join(" · ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <TimeField label="Anfang" value={draft.start} onChange={(t) => onChange({ ...draft, start: t })} />
        <TimeField label="Ende" value={draft.end} onChange={(t) => onChange({ ...draft, end: t })} />
        <Button type="button" size="sm" variant="outline" onClick={() => play(draft.start, draft.end)} title="Diese Zeitspanne der Aufnahme anhören">
          <PlayIcon />
          Anhören
        </Button>
      </div>
      <Textarea
        ref={area}
        value={draft.text}
        maxLength={2000}
        rows={2}
        placeholder="Was wurde gesagt?"
        onChange={(e) => onChange({ ...draft, text: e.target.value })}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && valid) void save();
          if (e.key === "Escape") onClose();
        }}
      />
      <p className="text-muted-foreground text-xs">
        Die Zeitspanne darf sich mit anderen Absätzen überlappen (z. B. ein „Mhm“ während die andere Person spricht). Anfang und Ende kannst du auch in der Zeitspur
        rechts ziehen. {words > 0 && `${words} ${words === 1 ? "Wort" : "Wörter"}.`}
      </p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!valid || busy} onClick={() => void save()}>
          Speichern
        </Button>
        <Button size="sm" variant="outline" onClick={onClose}>
          Abbrechen
        </Button>
        {draft.id !== undefined && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => void remove()}>
            <Trash2Icon />
            Absatz entfernen
          </Button>
        )}
      </div>
    </div>
  );
}
