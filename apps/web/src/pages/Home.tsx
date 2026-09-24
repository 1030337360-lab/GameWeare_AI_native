import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { formatPlays } from "../utils/helpers";
import type { Game } from "../types";

interface HomeProps {
  games: Game[];
  availableTags: string[];
  search: string;
  selectedTag: string;
}

export default function Home({ games, availableTags, search, selectedTag }: HomeProps) {
  const auth = useAuth();
  const navigate = useNavigate();
  const sections = ["Players' Choice", "Trending", "Recommended For You", "Recently Created"];
  const isFiltering = Boolean(search || selectedTag);

  function updateFilter(nextSearch: string, nextTag = selectedTag) {
    const query = new URLSearchParams();
    if (nextSearch.trim()) query.set("q", nextSearch.trim());
    if (nextTag) query.set("tag", nextTag);
    navigate(`/?${query.toString()}`, { replace: true });
  }

  const featuredGame = games[0];

  return (
    <main className="home">
      {/* Featured Section */}
      {featuredGame && <section className="featured">
        <div className="featured-content">
          <img src={featuredGame.thumbnailUrl ?? ""} alt={featuredGame.title} />
          <div className="featured-info">
            <h1>{featuredGame.title}</h1>
            <p>{featuredGame.tags.join(" · ")}</p>
            <div className="stats">
              <span>{formatPlays(featuredGame.plays)} plays</span>
              <span>{formatPlays(featuredGame.likes)} likes</span>
            </div>
            <button onClick={() => navigate(`/play/${featuredGame.id}`)}>
              Play Now
            </button>
          </div>
        </div>
      </section>}

      {/* Filter Bar */}
      <section className="filters">
        <input
          type="text"
          placeholder="Search games..."
          value={search}
          onChange={(e) => updateFilter(e.target.value)}
        />
        <div className="tags">
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
      </section>

      {/* Game Sections */}
      {games.length === 0 && <section className="results"><h2>No published games yet</h2><p>Create and publish a game to see it here.</p></section>}
      {isFiltering ? (
        <section className="results">
          <h2>Search Results</h2>
          <div className="game-grid">
            {games.map((game) => (
              <GameCard key={game.id} game={game} />
            ))}
          </div>
        </section>
      ) : (
        sections.map((section) => {
          const sectionGames = games.filter((g) => g.section === section);
          if (!sectionGames.length) return null;
          return (
            <section key={section} className="section">
              <h2>{section}</h2>
              <div className="game-rail">
                {sectionGames.map((game) => (
                  <GameCard key={game.id} game={game} />
                ))}
              </div>
            </section>
          );
        })
      )}
    </main>
  );
}

function GameCard({ game }: { game: Game }) {
  const navigate = useNavigate();
  return (
    <div className="game-card" onClick={() => navigate(`/games/${game.id}`)}>
      <img src={game.thumbnailUrl ?? ""} alt={game.title} />
      <div className="game-info">
        <h3>{game.title}</h3>
        <p>{game.creatorName}</p>
        <div className="stats">
          <span>{formatPlays(game.plays)} plays</span>
          <span>{formatPlays(game.likes)} likes</span>
        </div>
      </div>
    </div>
  );
}
