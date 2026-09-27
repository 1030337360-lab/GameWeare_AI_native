import React from "react";
import { ArrowRight, ArrowUpRight, Gamepad2, Play, Search, Sparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { API_BASE_URL } from "../utils/constants";
import { formatPlays } from "../utils/helpers";
import type { Game } from "../types";

interface HomeProps {
  games: Game[];
  featuredGame: Game | null;
  availableTags: string[];
  search: string;
  selectedTag: string;
  loading: boolean;
  error: boolean;
}

export default function Home({ games, featuredGame, availableTags, search, selectedTag, loading, error }: HomeProps) {
  const auth = useAuth();
  const navigate = useNavigate();
  const [draftSearch, setDraftSearch] = React.useState(search);
  const [trending, setTrending] = React.useState<{ id: string; title: string; author: string; plays: number }[]>([]);
  const isFiltering = Boolean(search || selectedTag);
  const createTarget = auth.authenticated ? "/create" : "/auth/login?next=/create";

  React.useEffect(() => { setDraftSearch(search); }, [search]);
  React.useEffect(() => {
    let active = true;
    void fetch(`${API_BASE_URL}/games/trending?limit=5`).then(async response => {
      if (active && response.ok) setTrending(await response.json() as typeof trending);
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  React.useEffect(() => {
    if (draftSearch === search) return;
    const timer = window.setTimeout(() => updateFilter(draftSearch), 280);
    return () => window.clearTimeout(timer);
  }, [draftSearch, search, selectedTag]);

  function updateFilter(nextSearch: string, nextTag = selectedTag) {
    const query = new URLSearchParams();
    if (nextSearch.trim()) query.set("q", nextSearch.trim());
    if (nextTag) query.set("tag", nextTag);
    navigate(`/?${query.toString()}`, { replace: true });
  }


  return (
    <main className="home">
      <section className="home-hero" aria-label="精选游戏">
        <div className="hero-copy">
          <div className="hero-kicker"><span className="live-indicator" /> 发现好游戏</div>
          <h1>{featuredGame ? <>发现<em>好游戏。</em></> : <>让想法<em>成为游戏。</em></>}</h1>
          <p>{featuredGame
            ? "探索创作者的作品，找到喜欢的玩法，也可以动手创造属于自己的游戏。"
            : "在这里探索新玩法，分享自己的游戏创意。"}</p>
          <div className="hero-actions">
            <Link className="hero-primary" to={featuredGame ? `/play/${featuredGame.id}` : createTarget}>
              {featuredGame ? <Play size={17} fill="currentColor" /> : <Sparkles size={18} />}
              {featuredGame ? "游玩精选游戏" : "创作游戏"}<ArrowRight size={17} />
            </Link>
            <a className="hero-secondary" href="#discover">浏览游戏 <ArrowUpRight size={17} /></a>
          </div>
          <div className="hero-footnote"><Gamepad2 size={16} /> 探索、创作、再玩一局。</div>
        </div>
        <div className="hero-art" aria-hidden="true">
          {featuredGame?.thumbnailUrl ? <img src={featuredGame.thumbnailUrl} alt="" /> : (
            <div className="hero-world">
              <span className="world-orbit orbit-one" /><span className="world-orbit orbit-two" />
              <span className="world-sun" /><span className="world-ground" />
              <span className="world-card card-one">✦</span><span className="world-card card-two">◈</span>
              <span className="world-cross cross-one">+</span><span className="world-cross cross-two">+</span>
            </div>
          )}
          <div className="hero-art-label"><span>01 / 无限可能</span><span>GAMEWEARE ✦</span></div>
        </div>
      </section>

      {trending.length > 0 && <section className="trending-strip" aria-label="热门游戏"><span className="section-kicker">热门游戏</span><div>{trending.map((item, index) => <Link key={item.id} to={`/games/${item.id}`}><b>{String(index + 1).padStart(2, "0")}</b><span>{item.title}<small>{item.author} · {formatPlays(item.plays)} 次游玩</small></span><ArrowRight size={16} /></Link>)}</div></section>}
      <section id="discover" className="discover-section">
        <div className="discover-heading">
          <div><span className="section-kicker">游戏广场</span><h2>发现下一款游戏<span>.</span></h2></div>
          <span className="game-total">共 {games.length} 款游戏</span>
        </div>
        <div className="catalog-controls">
          <label className="catalog-search"><Search size={19} /><span className="sr-only">搜索游戏</span>
            <input type="search" placeholder="搜索游戏或创作者" value={draftSearch}
              onChange={(e) => setDraftSearch(e.target.value)} />
            <kbd>⌕</kbd>
          </label>
          <div className="tags" aria-label="按标签筛选">
          <button className={!selectedTag ? "active" : ""} onClick={() => updateFilter(search, "")}>全部游戏</button>
          {availableTags.map((tag) => (
            <button
              key={tag}
              className={selectedTag === tag ? "active" : ""}
              onClick={() => updateFilter(search, selectedTag === tag ? "" : tag)}
            >
              {tag}
            </button>
          ))}
          </div>
        </div>
        {loading && games.length === 0 ? <div className="catalog-state" role="status"><span className="loading-orb" /> 正在加载游戏...</div>
          : games.length === 0 ? (
            <div className="catalog-empty">
              <div className="empty-symbol"><Gamepad2 size={36} /></div>
              <div><span className="section-kicker">{error ? "连接暂时不可用" : isFiltering ? "暂无搜索结果" : "从这里开始"}</span>
                <h3>{error ? "游戏广场暂时无法加载。" : isFiltering ? "没有找到游戏。" : "第一款游戏，等你创造。"}</h3>
                <p>{error ? "暂时无法加载游戏，请稍后刷新。" : isFiltering
                  ? "试试其他关键词，或清除筛选条件。"
                  : "发布后的游戏会出现在这里，快来分享你的想法。"}</p>
                {isFiltering ? <button className="empty-link" onClick={() => { setDraftSearch(""); updateFilter("", ""); }}>清除筛选 <ArrowRight size={17} /></button>
                  : <Link className="empty-link" to={createTarget}>开始创作 <ArrowRight size={17} /></Link>}
              </div>
            </div>
          ) : (
            <div className="catalog-grid">
              {games.map((game) => <GameCard key={game.id} game={game} />)}
            </div>
          )}
      </section>
    </main>
  );
}

function GameCard({ game }: { game: Game }) {
  return (
    <Link className="catalog-card" to={`/games/${game.id}`}>
      <div className="catalog-cover">
        {game.thumbnailUrl ? <img src={game.thumbnailUrl} alt="" loading="lazy" /> : <span className="cover-placeholder"><Gamepad2 size={38} /></span>}
        <span className="cover-open"><ArrowUpRight size={19} /></span>
      </div>
      <div className="catalog-card-content">
        <div><h3>{game.title}</h3><p>作者：{game.creatorName || "GameWeare 创作者"}</p></div>
        <span className="catalog-plays"><Play size={13} fill="currentColor" /> {formatPlays(game.plays)}</span>
      </div>
    </Link>
  );
}
