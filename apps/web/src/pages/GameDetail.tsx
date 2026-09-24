import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { formatPlays } from "../utils/helpers";
import type { Game } from "../types";

interface GameDetailProps {
  games: Game[];
}

export default function GameDetail({ games }: GameDetailProps) {
  const { gameId } = useParams();
  const auth = useAuth();
  const navigate = useNavigate();
  
  const game = games.find((item) => item.id === gameId);
  
  if (!game) {
    return <div>Game not found</div>;
  }

  async function updateInteraction(kind: "like" | "favorite", enabled: boolean) {
    if (!auth.authenticated) {
      navigate("/auth/login");
      return;
    }
    try {
      const response = await auth.apiFetch(`/games/${game!.id}/${kind}`, {
        method: enabled ? "PUT" : "DELETE",
      });
      if (response.ok) {
        // Refresh game data
      }
    } catch (error) {
      console.error(`Failed to ${kind} game:`, error);
    }
  }

  async function remixCurrentGame() {
    if (!auth.authenticated) {
      navigate("/auth/login");
      return;
    }
    try {
      const response = await auth.apiFetch(`/games/${game!.id}/remix`, { method: "POST" });
      if (response.ok) {
        const remix = await response.json();
        navigate(`/create`);
      }
    } catch (error) {
      console.error("Failed to remix game:", error);
    }
  }

  return (
    <div className="game-detail">
      <div className="game-header">
        <img src={game.thumbnailUrl ?? ""} alt={game.title} />
        <div className="game-info">
          <h1>{game.title}</h1>
          <p>{game.creatorName}</p>
          <div className="stats">
            <span>{formatPlays(game.plays)} plays</span>
            <span>{formatPlays(game.likes)} likes</span>
          </div>
          <div className="actions">
            <button onClick={() => navigate(`/play/${game.id}`)}>Play</button>
            <button onClick={() => updateInteraction("like", !game.likedByMe)}>
              {game.likedByMe ? "Unlike" : "Like"}
            </button>
            <button onClick={() => updateInteraction("favorite", !game.favoritedByMe)}>
              {game.favoritedByMe ? "Unfavorite" : "Favorite"}
            </button>
            <button onClick={remixCurrentGame}>Remix</button>
          </div>
        </div>
      </div>
    </div>
  );
}
