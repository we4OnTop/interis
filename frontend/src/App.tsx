import { useEffect, useState } from "react";
import { ColumnsIcon, FileTextIcon, ListChecksIcon, LoaderIcon, LockIcon, MoonIcon, SettingsIcon, SunIcon } from "lucide-react";

import { PlayerBar } from "@/components/PlayerBar";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, setUnauthorizedHandler } from "@/lib/api";
import { FeedbackProvider } from "@/lib/feedback";
import { PlayerProvider } from "@/lib/player";
import { ProjectProvider, useProject } from "@/lib/project";
import { href, navigate, useRoute, type Route } from "@/lib/router";
import { cn } from "@/lib/utils";
import { ColumnsPage } from "@/pages/ColumnsPage";
import { InterviewPage } from "@/pages/InterviewPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { QuestionsPage } from "@/pages/QuestionsPage";
import { SetupPage } from "@/pages/SetupPage";

type Auth = "checking" | "ok" | "missing";

export function App() {
  const [auth, setAuth] = useState<Auth>("checking");
  const route = useRoute();

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth("missing"));
    // The login token arrives in the URL fragment (never sent to any server) and is
    // exchanged once for an HttpOnly session cookie.
    const m = location.hash.match(/login=([A-Za-z0-9_-]+)/);
    const done = () => setAuth("ok");
    if (m) {
      api("POST", "/api/login", { token: m[1] })
        .then(() => {
          history.replaceState(null, "", `${location.pathname}#/`);
          window.dispatchEvent(new HashChangeEvent("hashchange"));
          done();
        })
        .catch(() => setAuth("missing"));
    } else {
      api("GET", "/api/projects").then(done, () => setAuth("missing"));
    }
  }, []);

  return (
    <TooltipProvider>
      <FeedbackProvider>
        <PlayerProvider>
          {auth === "checking" ? (
            <LoaderIcon className="text-muted-foreground m-8 size-5 animate-spin" />
          ) : auth === "missing" ? (
            <NotLoggedIn />
          ) : route.page === "projects" ? (
            <>
              <TopBar route={route} />
              <ProjectsPage />
            </>
          ) : (
            <ProjectProvider pid={route.pid}>
              <ProjectArea route={route} />
            </ProjectProvider>
          )}
          <PlayerBar />
        </PlayerProvider>
      </FeedbackProvider>
    </TooltipProvider>
  );
}

function NotLoggedIn() {
  return (
    <div className="mx-auto mt-24 max-w-md space-y-3 p-6 text-center">
      <LockIcon className="text-muted-foreground mx-auto size-8" />
      <h1 className="text-lg font-semibold">Nicht angemeldet</h1>
      <p className="text-muted-foreground text-sm">
        Bitte Interis über das Startmenü öffnen oder den Link verwenden, den <code>interis serve</code> im Terminal anzeigt.
      </p>
    </div>
  );
}

function ProjectArea({ route }: { route: Exclude<Route, { page: "projects" }> }) {
  const { detail, error } = useProject();
  if (error && !detail) return <p className="text-destructive p-6">{error}</p>;
  if (!detail) return <LoaderIcon className="text-muted-foreground m-8 size-5 animate-spin" />;
  return (
    <>
      <TopBar route={route} />
      {route.page === "questions" && <QuestionsPage code={route.code} />}
      {route.page === "columns" && <ColumnsPage />}
      {route.page === "setup" && <SetupPage tab={route.tab} />}
      {route.page === "interview" && <InterviewPage key={route.id} id={route.id} focusTurn={route.turn} />}
    </>
  );
}

function useDarkMode() {
  const [dark, setDark] = useState(() => localStorage.getItem("interis.dark") === "1");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("interis.dark", dark ? "1" : "0");
  }, [dark]);
  return [dark, setDark] as const;
}

function TopBar({ route }: { route: Route }) {
  const [dark, setDark] = useDarkMode();
  return (
    <header className="bg-background/95 sticky top-0 z-30 flex h-14 items-center gap-4 border-b px-4 backdrop-blur">
      <a href={href.projects()} className="flex items-center gap-2 font-semibold tracking-tight">
        <span className="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md text-sm">I</span>
        Interis
      </a>
      {route.page !== "projects" && <ProjectNav route={route} />}
      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => setDark(!dark)} title={dark ? "Hell" : "Dunkel"}>
          {dark ? <SunIcon /> : <MoonIcon />}
        </Button>
      </div>
    </header>
  );
}

function ProjectNav({ route }: { route: Exclude<Route, { page: "projects" }> }) {
  const { detail } = useProject();
  const pid = detail!.project.id;
  const done = detail!.interviews.filter((iv) => iv.transcribed);
  const tab = (active: boolean, to: string, icon: React.ReactNode, label: string) => (
    <a
      href={to}
      className={cn(
        "text-muted-foreground hover:text-foreground flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors [&_svg]:size-4",
        active && "bg-accent text-foreground",
      )}
    >
      {icon}
      {label}
    </a>
  );
  return (
    <>
      <span className="text-muted-foreground">/</span>
      <span className="max-w-56 truncate text-sm font-medium" title={detail!.project.name}>
        {detail!.project.name}
      </span>
      <nav className="ml-2 flex items-center gap-1">
        {tab(route.page === "questions", href.questions(pid), <ListChecksIcon />, "Pro Frage")}
        {tab(route.page === "columns", href.columns(pid), <ColumnsIcon />, "Nebeneinander")}
        {done.length > 0 && (
          <Select value={route.page === "interview" ? route.id : ""} onValueChange={(id) => navigate(href.interview(pid, id))}>
            <SelectTrigger size="sm" className={cn("gap-1.5 border-0 shadow-none", route.page === "interview" && "bg-accent")}>
              <FileTextIcon className="size-4" />
              <SelectValue placeholder="Transkript" />
            </SelectTrigger>
            <SelectContent>
              {done.map((iv) => (
                <SelectItem key={iv.id} value={iv.id}>
                  <span className="font-mono">{iv.id}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {tab(route.page === "setup", href.setup(pid), <SettingsIcon />, "Leitfaden & Gespräche")}
      </nav>
    </>
  );
}
