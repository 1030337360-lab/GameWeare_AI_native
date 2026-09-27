import React from "react";
import { ArrowLeft, ArrowRight, Gamepad2, Heart, Play, Repeat2, Star, UserRoundPlus } from "lucide-react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { formatPlays } from "../utils/helpers";
import type { Game } from "../types";

interface GameDetailProps {
  games: Game[];
  loading: boolean;
}

export default function GameDetail({ games, loading }: GameDetailProps) {
  const { gameId } = useParams();
  const auth = useAuth();
  const navigate = useNavigate();
  
  const game = games.find((item) => item.id === gameId);
  const [liked, setLiked] = React.useState(false);
  const [favorited, setFavorited] = React.useState(false);
  const [following, setFollowing] = React.useState(false);
  React.useEffect(() => { setLiked(Boolean(game?.likedByMe)); setFavorited(Boolean(game?.favoritedByMe)); }, [game?.id, game?.likedByMe, game?.favoritedByMe]);
  React.useEffect(() => {
    if (!auth.authenticated || !game?.creatorId || game.creatorId === auth.user?.id) return;
    let active = true;
    void auth.apiFetch(`/creators/${game.creatorId}/following/me`).then(async response => {
      if (active && response.ok) setFollowing(Boolean((await response.json() as { following: boolean }).following));
    });
    return () => { active = false; };
  }, [auth.authenticated, auth.apiFetch, auth.user?.id, game?.creatorId]);
  
  if (!game && loading) {
    return <main className="detail-missing" role="status"><span className="loading-orb" /> Loading game...</main>;
  }
  if (!game) {
    return <main className="detail-missing"><Gamepad2 size={35} /><h1>Game not found</h1><p>This game may have moved or is no longer available.</p><Link to="/">Back to explore <ArrowRight size={17} /></Link></main>;
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
        if (kind === "like") setLiked(enabled);
        else setFavorited(enabled);
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

  async function toggleFollow() {
    if (!auth.authenticated) { navigate("/auth/login"); return; }
    if (!game?.creatorId) return;
    const response = await auth.apiFetch(`/creators/${game.creatorId}/follow`, { method: following ? "DELETE" : "PUT" });
    if (response.ok) setFollowing(!following);
  }

  return (
    <div className="game-detail">
      <Link className="detail-back" to="/"><ArrowLeft size={16} /> Back to explore</Link>
      <div className="game-header">
        <div className="detail-art">
          {game.thumbnailUrl ? <img src={game.thumbnailUrl} alt={game.title} /> : <div className="detail-art-fallback"><Gamepad2 size={78} /><span>GAMEWEARE ORIGINAL</span></div>}
        </div>
        <div className="game-info">
          <span className="section-kicker">READY TO PLAY</span>
          <h1>{game.title}</h1>
          <p>Created by <strong>{game.creatorName || "Gameweare creator"}</strong></p>
          <div className="stats">
            <span>{formatPlays(game.plays)} plays</span>
            <span>{formatPlays(game.likes)} likes</span>
          </div>
          <div className="actions">
            <button onClick={() => navigate(`/play/${game.id}`)}><Play size={17} fill="currentColor" /> Play now <ArrowRight size={16} /></button>
            <button aria-pressed={liked} onClick={() => updateInteraction("like", !liked)}>
              <Heart size={17} fill={liked ? "currentColor" : "none"} /> {liked ? "Liked" : "Like"}
            </button>
            <button aria-pressed={favorited} onClick={() => updateInteraction("favorite", !favorited)}>
              <Star size={17} fill={favorited ? "currentColor" : "none"} /> {favorited ? "Saved" : "Save"}
            </button>
            {game.creatorId && game.creatorId !== auth.user?.id && <button aria-pressed={following} onClick={() => void toggleFollow()}><UserRoundPlus size={17} /> {following ? "Following" : "Follow creator"}</button>}
            <button onClick={remixCurrentGame}><Repeat2 size={17} /> Remix</button>
          </div>
        </div>
      </div>
    </div>
  );
}
