import React from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { getAnonymousId } from "../utils/helpers";
import type { Game } from "../types";

interface PlayGameProps {
  games: Game[];
  onGameUpdated: (game: Game) => void;
}

export default function PlayGame({ games, onGameUpdated }: PlayGameProps) {
  const { gameId } = useParams();
  const { apiFetch, token } = useAuth();
  const frameRef = React.useRef<HTMLIFrameElement | null>(null);
  const anonymousId = React.useMemo(() => getAnonymousId(), []);

  const game = games.find((item) => item.id === gameId);

  React.useEffect(() => {
    if (!game) return;
    
    // Report play event
    async function reportPlayEvent(eventType: string) {
      try {
        await apiFetch("/play/events", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            gameId: game!.id,
            eventType,
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
  }, [game, apiFetch, anonymousId]);

  if (!game) {
    return <div>Game not found</div>;
  }

  const documentUrl = game.thumbnailUrl; // TODO: Get actual document URL

  return (
    <div className="play-game">
      <iframe
        ref={frameRef}
        src={documentUrl ?? ""}
        title={game.title}
        style={{ width: "100%", height: "100vh", border: "none" }}
      />
    </div>
  );
}
