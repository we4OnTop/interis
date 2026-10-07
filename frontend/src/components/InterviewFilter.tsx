import { EyeIcon, EyeOffIcon, LightbulbIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function InterviewFilter({
  ids,
  hidden,
  toggle,
  showSuggestions,
  setShowSuggestions,
}: {
  ids: string[];
  hidden: Set<string>;
  toggle: (id: string) => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground mr-1 text-xs">Gespräche:</span>
      {ids.map((id) => {
        const off = hidden.has(id);
        return (
          <Button
            key={id}
            variant="outline"
            size="xs"
            className={cn("font-mono", off && "text-muted-foreground line-through opacity-60")}
            onClick={() => toggle(id)}
            title={off ? "einblenden" : "ausblenden"}
          >
            {off ? <EyeOffIcon /> : <EyeIcon />}
            {id}
          </Button>
        );
      })}
      <span className="bg-border mx-2 h-4 w-px" />
      <Button
        variant={showSuggestions ? "secondary" : "ghost"}
        size="xs"
        onClick={() => setShowSuggestions(!showSuggestions)}
        title="Automatische Vorschläge für Antworten an anderer Stelle"
      >
        <LightbulbIcon />
        Vorschläge {showSuggestions ? "an" : "aus"}
      </Button>
    </div>
  );
}
