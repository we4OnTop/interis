import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { DownloadIcon, LoaderIcon, Trash2Icon } from "lucide-react";

import { PlayButton, Time } from "@/components/review";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, type Extract } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { useProject } from "@/lib/project";
import { href } from "@/lib/router";

/** Auswertung: one row per guide question, one column per interview, the extracts (Kernaussagen) in the cells. */
export function ExtractPage() {
  const { detail, dataVersion } = useProject();
  const { fail, notify } = useFeedback();
  const pid = detail!.project.id;
  const [rows, setRows] = useState<Extract[] | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await api<{ extracts: Extract[] }>("GET", `/api/projects/${pid}/extracts`)).extracts);
    } catch (e) {
      fail(e);
    }
  }, [pid, fail]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const questions = detail!.guide?.questions ?? [];
  const ids = detail!.interviews.filter((iv) => iv.transcribed).map((iv) => iv.id);
  const byCell = useMemo(() => {
    const m = new Map<string, Extract[]>();
    for (const x of rows ?? []) {
      const key = `${x.guide_code}|${x.interview}`;
      m.set(key, [...(m.get(key) ?? []), x]);
    }
    return m;
  }, [rows]);

  if (!rows) return <LoaderIcon className="text-muted-foreground m-6 size-5 animate-spin" />;
  if (!questions.length)
    return (
      <p className="text-muted-foreground p-4 sm:p-6 text-sm">
        Noch kein Leitfaden. <a className="underline" href={href.setup(pid)}>Leitfaden & Gespräche einrichten</a>
      </p>
    );

  return (
    <div className="mx-auto max-w-[120rem] space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">Auswertung</h1>
          <p className="text-muted-foreground text-sm">
            Kernaussagen je Leitfadenfrage und Gespräch, in eigenen Worten. {rows.length} {rows.length === 1 ? "Extrakt" : "Extrakte"} insgesamt.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <a href={`/api/projects/${pid}/extracts/export?format=docx`}>
            <DownloadIcon />
            Als Word exportieren
          </a>
        </Button>
        <Button asChild variant="outline" size="sm">
          <a href={`/api/projects/${pid}/extracts/export?format=csv`}>
            <DownloadIcon />
            Als CSV (Excel) exportieren
          </a>
        </Button>
      </div>

      {ids.length === 0 ? (
        <p className="text-muted-foreground text-sm">Noch keine transkribierten Gespräche.</p>
      ) : (
        <div className="overflow-auto">
          <div
            className="bg-card grid w-max min-w-full rounded-lg border text-sm"
            style={{ gridTemplateColumns: `minmax(200px, 260px) repeat(${ids.length}, minmax(300px, 420px))` }}
          >
            <div className="bg-card sticky top-0 left-0 z-30 border-r border-b p-3 font-semibold">Leitfaden</div>
            {ids.map((id) => (
              <div key={id} className="bg-card sticky top-0 z-20 border-r border-b p-3">
                <a href={href.interview(pid, id)} className="font-mono font-semibold hover:underline">
                  {id}
                </a>
              </div>
            ))}
            {questions.map((q) => (
              <Fragment key={q.code}>
                <div className="bg-muted/40 sticky left-0 z-10 border-r border-b p-3">
                  <span className="text-question mr-1.5 font-semibold">{q.code}</span>
                  <span>{q.text}</span>
                </div>
                {ids.map((id) => (
                  <div key={id} className="min-w-0 space-y-2 border-r border-b p-3">
                    {(byCell.get(`${q.code}|${id}`) ?? []).map((x) => (
                      <ExtractItem key={`${x.id}|${x.updated_at}`} x={x} onChanged={load} onNotify={notify} onFail={fail} />
                    ))}
                  </div>
                ))}
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExtractItem({
  x,
  onChanged,
  onNotify,
  onFail,
}: {
  x: Extract;
  onChanged: () => Promise<void>;
  onNotify: (text: string) => void;
  onFail: (e: unknown) => void;
}) {
  const { confirm } = useFeedback();
  const [draft, setDraft] = useState(x.paraphrase);

  const save = async () => {
    try {
      await api("PATCH", `/api/extracts/${x.id}`, { paraphrase: draft });
      onNotify("Kernaussage gespeichert");
      await onChanged();
    } catch (e) {
      onFail(e);
    }
  };

  const remove = async () => {
    const ok = await confirm({
      title: "Extrakt löschen?",
      description: "Die Kernaussage wird entfernt. Das Transkript bleibt unverändert.",
      confirm: "Löschen",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api("DELETE", `/api/extracts/${x.id}`);
      onNotify("Extrakt gelöscht");
      await onChanged();
    } catch (e) {
      onFail(e);
    }
  };

  return (
    <div className="border-question/30 space-y-1.5 border-l-2 pl-2">
      <div className="flex items-center gap-1">
        <PlayButton id={x.interview} start={x.start} end={x.end} />
        <Time id={x.interview} t={x.start} />
        <span className="flex-1" />
        <Button variant="ghost" size="icon-xs" className="text-muted-foreground hover:text-destructive" title="Extrakt löschen" onClick={() => void remove()}>
          <Trash2Icon />
        </Button>
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">„{x.text}“</p>
      <Textarea
        aria-label="Kernaussage (in eigenen Worten)"
        placeholder="Kernaussage in eigenen Worten"
        maxLength={2000}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="min-h-12 text-sm"
      />
      {draft !== x.paraphrase && (
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setDraft(x.paraphrase)}>
            Zurücksetzen
          </Button>
          <Button size="sm" onClick={() => void save()}>
            Kernaussage speichern
          </Button>
        </div>
      )}
    </div>
  );
}
