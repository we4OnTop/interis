import { useEffect, useRef, useState } from "react";
import { FileUpIcon, ListPlusIcon, SaveIcon } from "lucide-react";

import { QuestionMeta } from "@/components/review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api, postFile, type Guide } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { useProject } from "@/lib/project";

const TEMPLATE = `# Leitfaden

## Einstieg
- F1: Erzählen Sie mir bitte, wie Ihr Arbeitsalltag aussieht.
  ~ Wie sieht ein typischer Tag bei Ihnen aus?
  > Seit wann machen Sie das?

## Hauptteil
- F2: …
`;

export function GuideTab() {
  const { detail, reload } = useProject();
  const { notify, fail } = useFeedback();
  const saved = detail!.guide_text;
  const [text, setText] = useState(saved || TEMPLATE);
  const [preview, setPreview] = useState<{ guide: Guide | null; error: string | null }>({ guide: null, error: null });
  const [saving, setSaving] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const dirty = text !== saved;

  useEffect(() => {
    const t = setTimeout(() => {
      api<{ guide: Guide | null; error: string | null }>("POST", "/api/guide/parse", { text }).then(setPreview, fail);
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const linesToQuestions = () =>
    setText(
      text
        .split("\n")
        .map((line) => {
          const t = line.trim();
          return !t || /^(#|[-*~>]|\d+[.)]\s)/.test(t) ? line : `- ${t}`;
        })
        .join("\n"),
    );

  const fromTypst = async (typst: string) => {
    const r = await api<{ text: string }>("POST", "/api/guide/import-typst", { text: typst });
    setText(r.text);
    notify("Typst-Leitfaden übernommen – bitte prüfen und speichern.");
  };

  const load = async (f: File) => {
    try {
      if (f.name.toLowerCase().endsWith(".typ")) {
        await fromTypst(await f.text());
      } else if (f.name.toLowerCase().endsWith(".docx")) {
        const r = await postFile<{ text: string }>("/api/guide/import-docx", f);
        setText(r.text);
        notify("Word-Datei übernommen – bitte prüfen: nur Zeilen mit „- “ gelten als Fragen.");
      } else {
        setText(await f.text());
      }
    } catch (e) {
      fail(e);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await api<{ questions: number; reanalyze: number }>("PUT", `/api/projects/${detail!.project.id}/guide`, { text });
      notify(`Leitfaden gespeichert: ${r.questions} Fragen${r.reanalyze ? ` – ${r.reanalyze} Gespräch(e) werden neu analysiert` : ""}`);
      await reload();
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };

  let section: string | null = null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Leitfaden</CardTitle>
          <CardDescription>
            Jede Frage beginnt mit „- “. Kürzel wie „F1:“ sind optional. „~“ = andere Formulierung, „&gt;“ = geplante Nachfrage, „!“ =
            Hinweis für dich, „##“ = Abschnitt. „[optional]“ oder „[Nebenfrage]“ am Zeilenende: darf entfallen. Ein Typst-Leitfaden
            (#frage, #impuls) kann direkt eingefügt oder geladen werden.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => file.current?.click()}>
              <FileUpIcon />
              Datei laden (.typ, .docx, .md, .txt)
            </Button>
            <Button variant="outline" size="sm" onClick={linesToQuestions} title="Macht aus jeder einfachen Textzeile eine Frage">
              <ListPlusIcon />
              Jede Zeile als Frage
            </Button>
            <input
              ref={file}
              type="file"
              accept=".typ,.md,.txt,.docx"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void load(f);
              }}
            />
          </div>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPaste={(e) => {
              // a whole Typst guide pasted in: convert it instead of inserting the source
              const pasted = e.clipboardData.getData("text");
              if (/#frage[([]/.test(pasted)) {
                e.preventDefault();
                fromTypst(pasted).catch(fail);
              }
            }}
            spellCheck
            className="field-sizing-fixed h-[28rem] resize-y font-mono text-[13px] leading-relaxed"
          />
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving || !dirty || !!preview.error}>
              <SaveIcon />
              Leitfaden speichern
            </Button>
            <span className="text-muted-foreground text-xs">
              {!saved ? "Vorlage – bitte anpassen und speichern" : dirty ? "Nicht gespeicherte Änderungen" : "Gespeichert"}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Vorschau</CardTitle>
          <CardDescription>
            {preview.guide
              ? `${preview.guide.questions.length} Fragen erkannt, davon ${preview.guide.questions.filter((q) => !q.droppable).length} Pflichtfragen`
              : preview.error
                ? "Fehler im Leitfaden"
                : "…"}
          </CardDescription>
        </CardHeader>
        <CardContent className="max-h-[34rem] space-y-2 overflow-auto">
          {preview.error && <p className="text-destructive text-sm">{preview.error}</p>}
          {preview.guide?.questions.map((q) => {
            const heading = q.section && q.section !== section ? q.section : null;
            section = q.section;
            return (
              <div key={q.code}>
                {heading && <h4 className="text-muted-foreground mt-4 mb-1 text-xs font-semibold tracking-wide uppercase">{heading}</h4>}
                <div className="flex gap-2 text-sm">
                  <Badge variant="question" className="mt-0.5 shrink-0">
                    {q.code}
                  </Badge>
                  <div>
                    <p>{q.text}</p>
                    {q.variants.length > 0 && <p className="text-muted-foreground text-xs">auch: {q.variants.join(" · ")}</p>}
                    {q.probes.length > 0 && <p className="text-muted-foreground text-xs">Nachfragen: {q.probes.join(" · ")}</p>}
                    <QuestionMeta q={q} />
                  </div>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
