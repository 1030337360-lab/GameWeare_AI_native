import React from "react";
import type { Game } from "./types";
import { Link, Routes, Route, useLocation, useSearchParams } from "react-router-dom";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { API_BASE_URL } from "./utils/constants";
import Header from "./components/layout/Header";
import ProtectedRoute from "./components/layout/ProtectedRoute";
import Home from "./pages/Home";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import GameDetail from "./pages/GameDetail";
import PlayGame from "./pages/PlayGame";
import AuthCallback from "./pages/AuthCallback";

import Create from "./pages/Create";
import Profile from "./pages/Profile";
import MaintainerPanel from "./pages/MaintainerPanel";
import Rewards from "./pages/Rewards";

export default function App() {
  return <AuthProvider><AppRoutes /></AuthProvider>;
}

function AppRoutes() {
  const { token } = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [games, setGames] = React.useState<Game[]>([]);
  const [featuredGame, setFeaturedGame] = React.useState<Game | null>(null);
  const [availableTags, setAvailableTags] = React.useState<string[]>([]);
  const [catalogLoading, setCatalogLoading] = React.useState(true);
  const [catalogError, setCatalogError] = React.useState(false);

  React.useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);

  function updateGame(game: Game) {
    setGames((prev) => prev.map((g) => (g.id === game.id ? game : g)));
  }

  React.useEffect(() => {
    let active = true;
    setCatalogLoading(true);
    setCatalogError(false);
    const query = new URLSearchParams();
    const search = searchParams.get("q");
    const tag = searchParams.get("tag");
    if (search) query.set("q", search);
    if (tag) query.set("tag", tag);
    const suffix = query.size ? `?${query}` : "";
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    Promise.all([
      fetch(`${API_BASE_URL}/games${suffix}`, { headers }),
      fetch(`${API_BASE_URL}/games/tags`, { headers }),
    ]).then(async ([gamesResponse, tagsResponse]) => {
      if (!gamesResponse.ok || !tagsResponse.ok) throw new Error("Could not load games");
      const payload = await gamesResponse.json() as Game[];
      const tags = await tagsResponse.json() as string[];
      if (active) {
        const normalized = payload.map((game) => ({ ...game,
          thumbnailUrl: game.coverUrl ? new URL(game.coverUrl, API_BASE_URL).toString() : null,
          creatorName: game.author }));
        setGames(normalized);
        if (!search && !tag && normalized.length > 0) setFeaturedGame(normalized[0]);
        setAvailableTags(tags);
        setCatalogLoading(false);
      }
    }).catch(() => { if (active) { setCatalogError(true); setCatalogLoading(false); } });
    return () => { active = false; };
  }, [searchParams, token]);

  return (
    <>
      <Header />
      <div className="page-stage" key={location.pathname}>
      <Routes location={location}>
        <Route
          path="/"
          element={<Home games={games} featuredGame={featuredGame} availableTags={availableTags} search={searchParams.get("q") ?? ""} selectedTag={searchParams.get("tag") ?? ""} loading={catalogLoading} error={catalogError} />}
        />
        <Route
          path="/create"
          element={
            <ProtectedRoute>
              <Create />
            </ProtectedRoute>
          }
        />
        <Route path="/games/:gameId" element={<GameDetail games={games} loading={catalogLoading} />} />
        <Route path="/play/:gameId" element={<PlayGame games={games} onGameUpdated={updateGame} />} />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <Profile />
            </ProtectedRoute>
          }
        />
        <Route path="/auth/login" element={<LoginPage />} />
        <Route path="/auth/register" element={<RegisterPage />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/maintenance" element={<ProtectedRoute><MaintainerPanel /></ProtectedRoute>} />
        <Route path="/rewards" element={<ProtectedRoute><Rewards /></ProtectedRoute>} />
      </Routes>
      </div>
      <footer className="site-footer">
        <span>© {new Date().getFullYear()} Gameweare <span className="footer-dot">✦</span> Made for play.</span>
        <div><Link to="/">Explore</Link><Link to={token ? "/create" : "/auth/login?next=/create"}>Create</Link><Link to={token ? "/rewards" : "/auth/login?next=/rewards"}>Rewards</Link></div>
      </footer>
    </>
  );
}
