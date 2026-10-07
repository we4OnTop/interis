import { useEffect, useState } from "react";
import { FolderOpenIcon, LoaderIcon, PlusIcon, ShieldCheckIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type ProjectSummary } from "@/lib/api";
import { useFeedback } from "@/lib/feedback";
import { href, navigate } from "@/lib/router";

export function ProjectsPage() {
  const { fail } = useFeedback();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () =>
      api<ProjectSummary[]>("GET", "/api/projects")
        .then((p) => alive && setProjects(p))
        .catch(fail);
    void load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    if (!name.trim()) return;
    try {
      const r = await api<{ id: number }>("POST", "/api/projects", { name: name.trim() });
      navigate(href.setup(r.id, "guide"));
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Projekte</h1>
        <p className="text-muted-foreground mt-1 flex items-center gap-1.5 text-sm">
          <ShieldCheckIcon className="size-4" />
          Ein Projekt = ein Interviewleitfaden und die Gespräche dazu. Alles bleibt auf diesem Rechner.
        </p>
      </div>

      {projects === null ? (
        <LoaderIcon className="text-muted-foreground size-5 animate-spin" />
      ) : projects.length === 0 ? (
        <p className="text-muted-foreground text-sm">Noch keine Projekte – lege unten dein erstes an.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <a key={p.id} href={p.transcribed && p.questions ? href.questions(p.id) : href.setup(p.id)} className="group">
              <Card className="group-hover:border-foreground/30 h-full gap-3 transition-colors">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <FolderOpenIcon className="text-muted-foreground size-4" />
                    {p.name}
                  </CardTitle>
                  <CardDescription>
                    {p.questions} Leitfadenfragen · {p.transcribed}/{p.interviews} Gespräche transkribiert
                  </CardDescription>
                </CardHeader>
                {p.active_jobs > 0 && (
                  <CardContent>
                    <Badge variant="suggest">
                      <LoaderIcon className="animate-spin" />
                      {p.active_jobs} in Arbeit
                    </Badge>
                  </CardContent>
                )}
              </Card>
            </a>
          ))}
        </div>
      )}

      <Card className="gap-4">
        <CardHeader>
          <CardTitle>Neues Projekt</CardTitle>
          <CardDescription>Danach gibst du den Leitfaden ein und lädst die Aufnahmen hoch.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex max-w-xl gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Masterarbeit – Interviews Pflege" maxLength={200} />
            <Button type="submit" disabled={!name.trim()}>
              <PlusIcon />
              Anlegen
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
