import { BookOpenTextIcon, MicIcon, SettingsIcon } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProject } from "@/lib/project";
import { href, navigate } from "@/lib/router";

import { GuideTab } from "./setup/GuideTab";
import { InterviewsTab } from "./setup/InterviewsTab";
import { SettingsTab } from "./setup/SettingsTab";

export function SetupPage({ tab }: { tab: string | null }) {
  const { detail } = useProject();
  const pid = detail!.project.id;
  const current = tab ?? (detail!.guide ? "interviews" : "guide");
  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-6">
      <Tabs value={current} onValueChange={(t) => navigate(href.setup(pid, t), true)} className="gap-5">
        <TabsList>
          <TabsTrigger value="interviews">
            <MicIcon />
            Gespräche ({detail!.interviews.length})
          </TabsTrigger>
          <TabsTrigger value="guide">
            <BookOpenTextIcon />
            Leitfaden {detail!.guide ? `(${detail!.guide.questions.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="settings">
            <SettingsIcon />
            Einstellungen
          </TabsTrigger>
        </TabsList>
        <TabsContent value="interviews">
          <InterviewsTab />
        </TabsContent>
        <TabsContent value="guide">
          <GuideTab key={detail!.guide_text} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab key={`${detail!.project.name}|${detail!.project.hotwords}|${detail!.project.smoothing_tags ?? ""}`} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
