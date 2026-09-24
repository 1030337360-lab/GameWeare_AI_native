import React from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { getAnonymousId } from "../utils/helpers";
import { API_BASE_URL } from "../utils/constants";
import type { Game } from "../types";

interface PlayGameProps {
  games: Game[];
  onGameUpdated: (game: Game) => void;
}

export default function PlayGame({ games, onGameUpdated }: PlayGameProps) {
  const { gameId } = useParams();
  const { apiFetch } = useAuth();
  const frameRef = React.useRef<HTMLIFrameElement | null>(null);
  const anonymousId = React.useMemo(() => getAnonymousId(), []);
  const [documentUrl, setDocumentUrl] = React.useState<string | null>(null);
  const [loadError, setLoadError] = React.useState("");

  const game = games.find((item) => item.id === gameId);

  React.useEffect(() => {
    if (!gameId) return;
    let active = true;
    setDocumentUrl(null);
    setLoadError("");
    apiFetch(`/play/${encodeURIComponent(gameId)}/manifest`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Game is not published or its document is unavailable.");
        const manifest = await response.json() as { documentUrl?: string };
        if (!manifest.documentUrl) throw new Error("Game document is unavailable.");
        if (active) setDocumentUrl(`${API_BASE_URL}${manifest.documentUrl}`);
      })
      .catch((error) => { if (active) setLoadError(error instanceof Error ? error.message : "Could not load game."); });
    return () => { active = false; };
  }, [apiFetch, gameId]);

  React.useEffect(() => {
    if (!gameId || !documentUrl) return;
    
    // Report play event
    async function reportPlayEvent(eventType: string) {
      try {
        await apiFetch("/play/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            gameId,
            event: eventType,
            anonymousId,
          }),
        });
      } catch (error) {
        console.error("Failed to report play event:", error);
      }
    }

    reportPlayEvent("game_start");
    
    return () => {
      reportPlayEvent("game_end");
    };
  }, [gameId, documentUrl, apiFetch, anonymousId]);

  if (loadError) return <div className="play-game">{loadError}</div>;
  if (!documentUrl) return <div className="play-game">Loading game...</div>;

  return (
    <div className="play-game">
      <iframe
        ref={frameRef}
        src={documentUrl}
        title={game?.title ?? "Game"}
        sandbox="allow-scripts"
        onLoad={() => { if (game) onGameUpdated(game); }}
        style={{ width: "100%", height: "100vh", border: "none" }}
      />
    </div>
  );
}
