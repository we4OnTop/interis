import { useEffect, useRef, useState } from "react";
import { ArrowDownIcon, ArrowUpIcon, FileAudioIcon, PlusIcon, UploadIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, enc, uploadFile } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { bytes, MODEL_LABEL } from "@/lib/format";
import { useProject } from "@/lib/project";

export const AUDIO_ACCEPT = "audio/*,video/*,.m4a,.mp3,.wav,.aac,.flac,.ogg,.opus,.wma,.webm,.mp4,.mov,.mkv,.avi,.3gp,.amr";
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;

export const extOf = (f: File) => (f.name.match(/\.([A-Za-z0-9]+)$/)?.[1] ?? "").toLowerCase();

/** Upload files as parts of an interview, one after another, reporting overall progress. */
export async function uploadParts(id: string, files: File[], onProgress: (fraction: number, index: number) => void) {
  const total = files.reduce((s, f) => s + f.size, 0) || 1;
  let done = 0;
  for (const [i, f] of files.entries()) {
    await uploadFile(`/api/interviews/${enc(id)}/parts?ext=${enc(extOf(f))}`, f, (x) => onProgress((done + x * f.size) / total, i));
    done += f.size;
  }
}

export function AddInterviewDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { detail, reload } = useProject();
  const { notify, fail } = useFeedback();
  const [id, setId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [model, setModel] = useState("whisper-large-v3");
  const [progress, setProgress] = useState<number | null>(null);
  const [current, setCurrent] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setId(detail?.next_id ?? "I01");
      setFiles([]);
      setProgress(null);
    }
  }, [open, detail?.next_id]);

  const move = (i: number, d: number) =>
    setFiles((fs) => {
      const next = [...fs];
      [next[i], next[i + d]] = [next[i + d], next[i]];
      return next;
    });

  const idValid = ID_PATTERN.test(id);
  const busy = progress !== null;

  const submit = async () => {
    try {
      setProgress(0);
      await api("POST", `/api/projects/${detail!.project.id}/interviews`, { interview: id });
      await uploadParts(id, files, (x, i) => {
        setProgress(x);
        setCurrent(i);
      });
      await api("POST", `/api/interviews/${enc(id)}/transcribe`, { model });
      notify(`${id}: ${files.length > 1 ? `${files.length} Teile hochgeladen` : "hochgeladen"} – Transkription eingereiht`);
      onOpenChange(false);
    } catch (e) {
      fail(e);
      setProgress(null);
    } finally {
      await reload();
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-xl" showCloseButton={!busy}>
        <DialogHeader>
          <DialogTitle>Gespräch hinzufügen</DialogTitle>
          <DialogDescription>
            Gab es eine Pause, wähle alle Aufnahmen des Gesprächs aus. Sie werden in der angezeigten Reihenfolge zu einem
            Gespräch zusammengesetzt.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="iid">Kürzel (Pseudonym)</Label>
            <Input
              id="iid"
              value={id}
              onChange={(e) => setId(e.target.value.trim())}
              className="w-40 font-mono"
              aria-invalid={!idValid}
              disabled={busy}
            />
            {!idValid && <p className="text-destructive text-xs">Nur Buchstaben, Ziffern, - und _ (keine echten Namen).</p>}
          </div>

          <div className="grid gap-2">
            <Label>Aufnahmen</Label>
            {files.length > 0 && (
              <ol className="divide-y rounded-md border">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="flex items-center gap-2 px-3 py-2 text-sm">
                    <span className="text-muted-foreground w-12 shrink-0 text-xs font-medium">Teil {i + 1}</span>
                    <FileAudioIcon className="text-muted-foreground size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate" title={f.name}>
                      {f.name}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">{bytes(f.size)}</span>
                    {!busy && (
                      <span className="flex shrink-0">
                        <Button variant="ghost" size="icon-xs" disabled={i === 0} onClick={() => move(i, -1)} title="nach oben">
                          <ArrowUpIcon />
                        </Button>
                        <Button variant="ghost" size="icon-xs" disabled={i === files.length - 1} onClick={() => move(i, 1)} title="nach unten">
                          <ArrowDownIcon />
                        </Button>
                        <Button variant="ghost" size="icon-xs" onClick={() => setFiles(files.filter((_, j) => j !== i))} title="entfernen">
                          <XIcon />
                        </Button>
                      </span>
                    )}
                    {busy && i === current && <span className="text-muted-foreground text-xs">lädt …</span>}
                  </li>
                ))}
              </ol>
            )}
            <input
              ref={input}
              type="file"
              multiple
              accept={AUDIO_ACCEPT}
              hidden
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []).sort((a, b) => a.name.localeCompare(b.name, "de", { numeric: true }));
                setFiles((fs) => [...fs, ...picked]);
                e.target.value = "";
              }}
            />
            {!busy && (
              <Button variant="outline" className="w-fit" onClick={() => input.current?.click()}>
                <PlusIcon />
                {files.length ? "Weitere Aufnahme hinzufügen" : "Aufnahme(n) auswählen"}
              </Button>
            )}
            <p className="text-muted-foreground text-xs">
              Die Dateien werden als <code>audio\{id || "…"}-1.endung</code> usw. in deinen Datenordner kopiert. Dateinamen werden nicht
              übernommen.
            </p>
          </div>

          <div className="grid gap-2">
            <Label>Genauigkeit</Label>
            <Select value={model} onValueChange={setModel} disabled={busy}>
              <SelectTrigger className="w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(detail?.models ?? []).map((m) => (
                  <SelectItem key={m} value={m}>
                    {MODEL_LABEL[m] ?? m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              Dauer: etwa 35–40 s pro Audiominute auf dem Entwicklungs-PC, auf dem Laptop etwa doppelt so lang. Die Transkription läuft im
              Hintergrund weiter, auch wenn du das Fenster schließt.
            </p>
          </div>

          {busy && (
            <div className="grid gap-1.5">
              <Progress value={progress * 100} />
              <p className="text-muted-foreground text-xs">Hochladen … {Math.round(progress * 100)} %</p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Abbrechen
          </Button>
          <Button disabled={busy || !idValid || files.length === 0} onClick={submit}>
            <UploadIcon />
            Hochladen & transkribieren
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
