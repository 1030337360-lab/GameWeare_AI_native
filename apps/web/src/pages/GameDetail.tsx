import React from "react";
import { ArrowLeft, ArrowRight, Gamepad2, Heart, MessageCircle, Play, Repeat2, Send, Star, Trash2, UserRoundPlus } from "lucide-react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { formatPlays, readApiError } from "../utils/helpers";
import { API_BASE_URL } from "../utils/constants";
import type { Game } from "../types";

interface GameDetailProps {
  games: Game[];
  loading: boolean;
}

type GameComment = { id: string; userId: string; author: string; content: string; createdAt: string; mine: boolean };
type CommentPage = { items: GameComment[]; hasMore: boolean; page: number; total: number };

export default function GameDetail({ games, loading }: GameDetailProps) {
  const { gameId } = useParams();
  const auth = useAuth();
  const navigate = useNavigate();
  
  const [detailGame, setDetailGame] = React.useState<Game | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(true);
  const game = (detailGame?.id === gameId ? detailGame : null) ?? games.find((item) => item.id === gameId);
  const [liked, setLiked] = React.useState(false);
  const [likeCount, setLikeCount] = React.useState(0);
  const [favorited, setFavorited] = React.useState(false);
  const [following, setFollowing] = React.useState(false);
  const [comments, setComments] = React.useState<GameComment[]>([]);
  const [commentsLoading, setCommentsLoading] = React.useState(true);
  const [commentTotal, setCommentTotal] = React.useState(0);
  const [hasMoreComments, setHasMoreComments] = React.useState(false);
  const [commentPage, setCommentPage] = React.useState(0);
  const [commentDraft, setCommentDraft] = React.useState("");
  const [commentBusy, setCommentBusy] = React.useState(false);
  const [commentError, setCommentError] = React.useState("");
  React.useEffect(() => { setLiked(Boolean(game?.likedByMe)); setLikeCount(game?.likes ?? 0); setFavorited(Boolean(game?.favoritedByMe)); }, [game?.id, game?.likedByMe, game?.likes, game?.favoritedByMe]);
  React.useEffect(() => {
    if (!gameId) return;
    let active = true;
    setCommentsLoading(true);
    setDetailLoading(true);
    void auth.apiFetch(`/games/${encodeURIComponent(gameId)}`).then(async response => {
      if (!active || !response.ok) return;
      const payload = await response.json() as Game;
      setDetailGame({ ...payload, thumbnailUrl: payload.coverUrl ? new URL(payload.coverUrl, API_BASE_URL).toString() : null, creatorName: payload.author });
    }).catch(() => {}).finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [auth.apiFetch, gameId]);
  React.useEffect(() => {
    if (!gameId) return;
    let active = true;
    setComments([]);
    setCommentError("");
    void auth.apiFetch(`/games/${encodeURIComponent(gameId)}/comments?limit=20&page=0`).then(async response => {
      if (!response.ok) throw new Error("评论暂时无法加载");
      const payload = await response.json() as CommentPage;
      if (active) { setComments(payload.items); setCommentTotal(payload.total); setHasMoreComments(payload.hasMore); setCommentPage(0); }
    }).catch(error => { if (active) setCommentError(error instanceof Error ? error.message : "评论暂时无法加载"); })
      .finally(() => { if (active) setCommentsLoading(false); });
    return () => { active = false; };
  }, [auth.apiFetch, gameId]);
  React.useEffect(() => {
    if (!auth.authenticated || !game?.creatorId || game.creatorId === auth.user?.id) return;
    let active = true;
    void auth.apiFetch(`/creators/${game.creatorId}/following/me`).then(async response => {
      if (active && response.ok) setFollowing(Boolean((await response.json() as { following: boolean }).following));
    });
    return () => { active = false; };
  }, [auth.authenticated, auth.apiFetch, auth.user?.id, game?.creatorId]);
  
  if (!game && (loading || detailLoading)) {
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
        if (kind === "like") {
          const state = await response.json() as { likes: number; likedByMe: boolean };
          setLiked(state.likedByMe);
          setLikeCount(state.likes);
        }
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

  async function submitComment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth.authenticated) { navigate(`/auth/login?next=${encodeURIComponent(`/games/${gameId}`)}`); return; }
    const content = commentDraft.trim();
    if (!content || content.length > 1000 || !gameId) return;
    setCommentBusy(true); setCommentError("");
    try {
      const response = await auth.apiFetch(`/games/${encodeURIComponent(gameId)}/comments`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }),
      });
      if (!response.ok) throw new Error((await readApiError(response)).message || "评论发送失败");
      const posted = await response.json() as GameComment;
      setComments(current => [posted, ...current]);
      setCommentTotal(current => current + 1);
      setCommentDraft("");
    } catch (error) { setCommentError(error instanceof Error ? error.message : "评论发送失败"); }
    finally { setCommentBusy(false); }
  }

  async function deleteComment(commentId: string) {
    if (!gameId) return;
    setCommentBusy(true); setCommentError("");
    try {
      const response = await auth.apiFetch(`/games/${encodeURIComponent(gameId)}/comments/${encodeURIComponent(commentId)}`, { method: "DELETE" });
      if (!response.ok) throw new Error((await readApiError(response)).message || "删除失败");
      setComments(current => current.filter(comment => comment.id !== commentId));
      setCommentTotal(current => Math.max(0, current - 1));
    } catch (error) { setCommentError(error instanceof Error ? error.message : "删除失败"); }
    finally { setCommentBusy(false); }
  }

  async function loadMoreComments() {
    if (!gameId) return;
    setCommentBusy(true); setCommentError("");
    try {
      const nextPage = commentPage + 1;
      const response = await auth.apiFetch(`/games/${encodeURIComponent(gameId)}/comments?limit=20&page=${nextPage}`);
      if (!response.ok) throw new Error("更多评论加载失败");
      const payload = await response.json() as CommentPage;
      setComments(current => [...current, ...payload.items.filter(item => !current.some(existing => existing.id === item.id))]);
      setCommentPage(nextPage);
      setHasMoreComments(payload.hasMore);
    } catch (error) { setCommentError(error instanceof Error ? error.message : "更多评论加载失败"); }
    finally { setCommentBusy(false); }
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
          <p>创作者：<strong>{game.creatorName || "GameWeare 创作者"}</strong></p>
          <div className="stats">
            <span>{formatPlays(game.plays)} plays</span>
            <span>{formatPlays(likeCount)} 次点赞</span>
            <span>{formatPlays(commentTotal)} 条评论</span>
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
      <section className="game-comments" aria-labelledby="game-comments-title">
        <div className="game-comments-heading"><div><span className="section-kicker">COMMUNITY / 玩家交流</span><h2 id="game-comments-title">评论区 <span>{commentTotal}</span></h2><p>聊聊玩法、关卡和你最喜欢的瞬间。</p></div><MessageCircle size={28} /></div>
        <form className="game-comment-form" onSubmit={submitComment}>
          <label htmlFor="game-comment-input">{auth.authenticated ? "写下你的评论" : "登录后参与讨论"}</label>
          <textarea id="game-comment-input" value={commentDraft} maxLength={1000} rows={3} disabled={!auth.authenticated || commentBusy} placeholder={auth.authenticated ? "分享你的体验，给创作者一些灵感…" : "登录后即可发表评论"} onChange={event => setCommentDraft(event.target.value)} />
          <div><small>{commentDraft.length} / 1000</small>{auth.authenticated ? <button type="submit" disabled={commentBusy || !commentDraft.trim()}><Send size={16} /> 发布评论</button> : <Link to={`/auth/login?next=${encodeURIComponent(`/games/${gameId}`)}`}>登录后评论 <ArrowRight size={16} /></Link>}</div>
        </form>
        {commentError && <p className="game-comment-error" role="alert">{commentError}</p>}
        <div className="game-comment-list">
          {commentsLoading && <p className="game-comment-empty">正在加载评论…</p>}
          {!commentsLoading && comments.length === 0 && !commentError && <p className="game-comment-empty">还没有评论，来写下第一条吧。</p>}
          {comments.map(comment => <article className="game-comment" key={comment.id}><div className="game-comment-avatar" aria-hidden="true">{comment.author?.slice(0, 1) || "玩"}</div><div className="game-comment-body"><div className="game-comment-meta"><strong>{comment.author || "玩家"}</strong><time>{new Date(comment.createdAt).toLocaleString("zh-CN")}</time>{comment.mine && <button type="button" disabled={commentBusy} onClick={() => void deleteComment(comment.id)} aria-label="删除我的评论"><Trash2 size={15} /> 删除</button>}</div><p>{comment.content}</p></div></article>)}
        </div>
        {hasMoreComments && <button className="game-comment-more" disabled={commentBusy} onClick={() => void loadMoreComments()}>加载更多评论 <ArrowRight size={16} /></button>}
      </section>
    </div>
  );
}
