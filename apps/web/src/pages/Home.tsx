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
      <section className="home-hero" aria-label="Featured game">
        <div className="hero-copy">
          <div className="hero-kicker"><span className="live-indicator" /> A NEW SPACE FOR PLAY</div>
          <h1>{featuredGame ? <>Find your next <em>obsession.</em></> : <>Ideas become <em>playable.</em></>}</h1>
          <p>{featuredGame
            ? "Discover remarkable games from a growing community of creators. Jump in, find a favorite, and make something of your own."
            : "A home for games made by people with ideas. Explore new worlds, then create one of your own."}</p>
          <div className="hero-actions">
            <Link className="hero-primary" to={featuredGame ? `/play/${featuredGame.id}` : createTarget}>
              {featuredGame ? <Play size={17} fill="currentColor" /> : <Sparkles size={18} />}
              {featuredGame ? "Play featured game" : "Create a game"}<ArrowRight size={17} />
            </Link>
            <a className="hero-secondary" href="#discover">Explore games <ArrowUpRight size={17} /></a>
          </div>
          <div className="hero-footnote"><Gamepad2 size={16} /> Explore. Create. Play again.</div>
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
          <div className="hero-art-label"><span>01 / INFINITE POSSIBILITIES</span><span>GAMEWEARE ✦</span></div>
        </div>
      </section>

      {trending.length > 0 && <section className="trending-strip" aria-label="热门游戏"><span className="section-kicker">TRENDING NOW</span><div>{trending.map((item, index) => <Link key={item.id} to={`/games/${item.id}`}><b>{String(index + 1).padStart(2, "0")}</b><span>{item.title}<small>{item.author} · {formatPlays(item.plays)} plays</small></span><ArrowRight size={16} /></Link>)}</div></section>}
      <section id="discover" className="discover-section">
        <div className="discover-heading">
          <div><span className="section-kicker">THE ARCADE</span><h2>Discover your next game<span>.</span></h2></div>
          <span className="game-total">{games.length} {games.length === 1 ? "GAME" : "GAMES"} TO EXPLORE</span>
        </div>
        <div className="catalog-controls">
          <label className="catalog-search"><Search size={19} /><span className="sr-only">Search games</span>
            <input type="search" placeholder="Search by title or creator" value={draftSearch}
              onChange={(e) => setDraftSearch(e.target.value)} />
            <kbd>⌕</kbd>
          </label>
          <div className="tags" aria-label="Filter by tag">
          <button className={!selectedTag ? "active" : ""} onClick={() => updateFilter(search, "")}>All games</button>
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
        {loading && games.length === 0 ? <div className="catalog-state" role="status"><span className="loading-orb" /> Loading the arcade...</div>
          : games.length === 0 ? (
            <div className="catalog-empty">
              <div className="empty-symbol"><Gamepad2 size={36} /></div>
              <div><span className="section-kicker">{error ? "CONNECTION UNAVAILABLE" : isFiltering ? "NO MATCHES YET" : "THE STORY STARTS HERE"}</span>
                <h3>{error ? "The arcade is taking a breather." : isFiltering ? "No games found." : "The first game could be yours."}</h3>
                <p>{error ? "We couldn't load games right now. Try refreshing in a moment." : isFiltering
                  ? "Try another search or clear your filters to see more games."
                  : "Published games will appear here. Bring your idea to life and help fill the arcade."}</p>
                {isFiltering ? <button className="empty-link" onClick={() => { setDraftSearch(""); updateFilter("", ""); }}>Clear filters <ArrowRight size={17} /></button>
                  : <Link className="empty-link" to={createTarget}>Start creating <ArrowRight size={17} /></Link>}
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
        <div><h3>{game.title}</h3><p>by {game.creatorName || "Gameweare creator"}</p></div>
        <span className="catalog-plays"><Play size={13} fill="currentColor" /> {formatPlays(game.plays)}</span>
      </div>
    </Link>
  );
}
