import { useState } from "react";
import { SaveIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { useProject } from "@/lib/project";

export function SettingsTab() {
  const { detail, reload } = useProject();
  const { notify, fail } = useFeedback();
  const p = detail!.project;
  const [name, setName] = useState(p.name);
  const [hotwords, setHotwords] = useState(p.hotwords);

  return (
    <Card className="max-w-3xl gap-4">
      <CardHeader>
        <CardTitle>Projekt-Einstellungen</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2">
          <Label htmlFor="pname">Name</Label>
          <Input id="pname" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="hot">Glossar</Label>
          <Textarea
            id="hot"
            value={hotwords}
            onChange={(e) => setHotwords(e.target.value)}
            maxLength={2000}
            placeholder="z. B. Stakeholder, Deployment, Machine Learning, SAP S/4HANA, Müller-Lüdenscheidt"
          />
          <CardDescription>
            Namen und Fachbegriffe – auch englische –, die in den Gesprächen vorkommen. Die Spracherkennung bekommt sie als Hinweis und
            schreibt sie dann meist richtig. Gilt für Transkriptionen, die danach gestartet werden.
          </CardDescription>
        </div>
        <Button
          disabled={!name.trim() || (name === p.name && hotwords === p.hotwords)}
          onClick={async () => {
            try {
              await api("PATCH", `/api/projects/${p.id}`, { name: name.trim(), hotwords });
              notify("Gespeichert");
              await reload();
            } catch (e) {
              fail(e);
            }
          }}
        >
          <SaveIcon />
          Speichern
        </Button>
      </CardContent>
    </Card>
  );
}
