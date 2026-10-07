import { useEffect } from "react";
import { PauseIcon, PlayIcon, RotateCcwIcon, RotateCwIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { stamp } from "@/lib/format";
import { usePlayer, usePlayerState } from "@/lib/player";

/** Bottom bar while something is playing. Shortcuts: Space = play/pause, Alt+← / Alt+→ = 5 s back/forward. */
export function PlayerBar() {
  const ps = usePlayerState();
  const player = usePlayer();

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (!ps.id || (e.target as HTMLElement).closest("input, textarea, select, button, [role=dialog], [contenteditable]")) return;
      if (e.code === "Space") {
        e.preventDefault();
        player.toggle();
      } else if (e.altKey && e.key === "ArrowLeft") player.skip(-5);
      else if (e.altKey && e.key === "ArrowRight") player.skip(5);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [ps.id, player]);

  if (!ps.id) return null;
  return (
    <div className="bg-background/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur">
      <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-2">
        <span className="font-mono text-sm font-semibold">{ps.id}</span>
        <span className="text-muted-foreground font-mono text-sm tabular-nums">{stamp(ps.parts, ps.time)}</span>
        <div className="mx-auto flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" onClick={() => player.skip(-5)} title="5 s zurück (Alt+←)">
            <RotateCcwIcon />
          </Button>
          <Button size="icon" className="rounded-full" onClick={player.toggle} title="Abspielen/Pause (Leertaste)">
            {ps.playing ? <PauseIcon /> : <PlayIcon />}
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => player.skip(5)} title="5 s vor (Alt+→)">
            <RotateCwIcon />
          </Button>
        </div>
        <span className="text-muted-foreground hidden text-xs sm:inline">Leertaste · Alt+←/→</span>
        <Button variant="ghost" size="icon-sm" onClick={player.stop} title="Player schließen">
          <XIcon />
        </Button>
      </div>
    </div>
  );
}
