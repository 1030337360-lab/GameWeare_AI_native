import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { Gamepad2, Play, Plus, UserRound } from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";

type Game = {
  id: string;
  title: string;
  author: string;
  description: string;
  tags: string[];
  publishedAt: string;
  coverUrl: string;
  plays: number;
  section: string;
};

type Manifest = {
  id: string;
  title: string;
  runtime: string;
  entry: string;
  bundleUrl: string;
  assets: string[];
};

const fallbackGames: Game[] = [
  {
    id: "astro-ludo",
    title: "Astro Ludo",
    author: "xiaoling",
    description: "Fast tabletop moves in a glowing space arcade.",
    tags: ["Board", "Arcade"],
    publishedAt: "2026-06-18T10:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1614728894747-a83421e2b9c9?auto=format&fit=crop&w=900&q=80",
    plays: 1200000,
    section: "Players' Choice"
  },
  {
    id: "color-bloom",
    title: "Color Bloom",
    author: "emanfatima",
    description: "A bright matching puzzle generated from a single prompt.",
    tags: ["Puzzle", "Generated"],
    publishedAt: "2026-06-18T11:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=900&q=80",
    plays: 700000,
    section: "Trending"
  },
  {
    id: "rail-in-air",
    title: "Rail in Air",
    author: "Majisok",
    description: "Balance a flying rail cart through neon gates.",
    tags: ["Runner", "Physics"],
    publishedAt: "2026-06-18T12:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=80",
    plays: 4500000,
    section: "Recommended For You"
  }
];

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`);
    if (!response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

function formatPlays(plays: number) {
  if (plays >= 1000000) return `${(plays / 1000000).toFixed(plays % 1000000 === 0 ? 0 : 1)}M`;
  if (plays >= 1000) return `${(plays / 1000).toFixed(plays % 1000 === 0 ? 0 : 1)}K`;
  return String(plays);
}

function App() {
  const [games, setGames] = React.useState<Game[]>(fallbackGames);

  React.useEffect(() => {
    fetchJson<Game[]>("/games", fallbackGames).then(setGames);
  }, []);

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Header />
        <Routes>
          <Route path="/" element={<Home games={games} />} />
          <Route path="/create" element={<Create />} />
          <Route path="/games/:gameId" element={<GameDetail games={games} />} />
          <Route path="/play/:gameId" element={<PlayGame games={games} />} />
          <Route path="/profile" element={<Profile />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

function Header() {
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <Gamepad2 size={24} />
        <span>Yahaha</span>
      </Link>
      <nav>
        <NavLink to="/">Home</NavLink>
        <NavLink to="/create">Create</NavLink>
        <NavLink to="/profile">Profile</NavLink>
      </nav>
      <Link to="/create" className="create-button">
        <Plus size={18} />
        Create
      </Link>
    </header>
  );
}

function Home({ games }: { games: Game[] }) {
  const sections = ["Players' Choice", "Trending", "Recommended For You", "Recently Created"];

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">AI native arcade</p>
          <h1>Play community games. Generate the next one.</h1>
          <p>Browse playable HTML5 game manifests now; the Create pipeline is stubbed but its API shape is preserved.</p>
        </div>
        <Link to="/create" className="hero-action">
          <Plus size={20} />
          Start creating
        </Link>
      </section>
      {sections.map((section) => {
        const sectionGames = games.filter((game) => game.section === section);
        if (sectionGames.length === 0) return null;
        return <GameSection key={section} title={section} games={sectionGames} />;
      })}
    </main>
  );
}

function GameSection({ title, games }: { title: string; games: Game[] }) {
  return (
    <section className="game-section">
      <h2>{title}</h2>
      <div className="game-grid">
        {games.map((game) => (
          <article className="game-card" key={game.id}>
            <Link to={`/games/${game.id}`} className="cover-link">
              <img src={game.coverUrl} alt="" />
              <span className="play-count">{formatPlays(game.plays)}</span>
            </Link>
            <div className="card-body">
              <div>
                <h3>{game.title}</h3>
                <p>by {game.author}</p>
              </div>
              <Link to={`/play/${game.id}`} className="icon-action" title={`Play ${game.title}`}>
                <Play size={18} />
              </Link>
            </div>
            <div className="tag-row">
              {game.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function GameDetail({ games }: { games: Game[] }) {
  const { gameId } = useParams();
  const game = games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId);

  if (!game) return <EmptyState title="Game not found" body="The selected game id is not in the local catalog." />;

  return (
    <main className="detail-layout">
      <img src={game.coverUrl} alt="" className="detail-cover" />
      <section className="detail-copy">
        <p className="eyebrow">{game.section}</p>
        <h1>{game.title}</h1>
        <p>{game.description}</p>
        <div className="meta-grid">
          <span>Author: {game.author}</span>
          <span>Plays: {formatPlays(game.plays)}</span>
          <span>Published: {new Date(game.publishedAt).toLocaleDateString()}</span>
        </div>
        <div className="tag-row">
          {game.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <Link to={`/play/${game.id}`} className="primary-action">
          <Play size={18} />
          Play now
        </Link>
      </section>
    </main>
  );
}

function PlayGame({ games }: { games: Game[] }) {
  const { gameId } = useParams();
  const game = games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId);
  const [manifest, setManifest] = React.useState<Manifest | null>(null);

  React.useEffect(() => {
    if (!gameId) return;
    fetchJson<Manifest | null>(`/play/${gameId}/manifest`, null).then(setManifest);
  }, [gameId]);

  if (!game) return <EmptyState title="Game not found" body="The selected game id is not in the local catalog." />;

  return (
    <main className="play-layout">
      <section className="play-header">
        <div>
          <p className="eyebrow">Sandbox Play</p>
          <h1>{game.title}</h1>
        </div>
        <Link to={`/games/${game.id}`} className="secondary-action">Details</Link>
      </section>
      <iframe
        className="game-frame"
        title={game.title}
        sandbox="allow-scripts"
        src={manifest?.bundleUrl ?? `${API_BASE_URL}/bundles/games/${game.id}/index.html`}
      />
      <p className="manifest-note">
        Runtime: {manifest?.runtime ?? "iframe-html5"} · Entry: {manifest?.entry ?? "index.html"}
      </p>
    </main>
  );
}

function Create() {
  const [message, setMessage] = React.useState("");
  const [status, setStatus] = React.useState("Create implementation is intentionally stubbed for this milestone.");

  async function submitJob(event: React.FormEvent) {
    event.preventDefault();
    const response = await fetch(`${API_BASE_URL}/create/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: message, files: [] })
    });
    const payload = await response.json();
    setStatus(`Job ${payload.id} accepted with status ${payload.status}. Real generation is not implemented yet.`);
  }

  return (
    <main className="create-layout">
      <section>
        <p className="eyebrow">Create stub</p>
        <h1>Describe a game idea</h1>
        <p>The UI and API contract are present, while the actual multi-agent generation pipeline is out of scope for this minimum runnable build.</p>
      </section>
      <form className="prompt-panel" onSubmit={submitJob}>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="A neon puzzle game where players connect constellations..."
        />
        <button type="submit">Create job</button>
      </form>
      <div className="status-panel">{status}</div>
    </main>
  );
}

function Profile() {
  return (
    <main className="create-layout">
      <UserRound size={42} />
      <h1>Profile</h1>
      <p>Session-aware profile data will be connected after the authentication flow is expanded.</p>
    </main>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <main className="empty-state">
      <h1>{title}</h1>
      <p>{body}</p>
      <Link to="/" className="primary-action">Back home</Link>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
