import React from "react";
import type { Game } from "./types";
import { Routes, Route, useLocation, useSearchParams } from "react-router-dom";
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

export default function App() {
  return <AuthProvider><AppRoutes /></AuthProvider>;
}

function AppRoutes() {
  const { token } = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [games, setGames] = React.useState<Game[]>([]);
  const [availableTags, setAvailableTags] = React.useState<string[]>([]);

  function updateGame(game: Game) {
    setGames((prev) => prev.map((g) => (g.id === game.id ? game : g)));
  }

  React.useEffect(() => {
    let active = true;
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
        setGames(payload.map((game) => ({ ...game, thumbnailUrl: game.coverUrl || null, creatorName: game.author })));
        setAvailableTags(tags);
      }
    }).catch(() => { if (active) { setGames([]); setAvailableTags([]); } });
    return () => { active = false; };
  }, [location.pathname, searchParams, token]);

  return (
    <>
      <Header />
      <Routes>
        <Route
          path="/"
          element={<Home games={games} availableTags={availableTags} search={searchParams.get("q") ?? ""} selectedTag={searchParams.get("tag") ?? ""} />}
        />
        <Route
          path="/create"
          element={
            <ProtectedRoute>
              <Create />
            </ProtectedRoute>
          }
        />
        <Route path="/games/:gameId" element={<GameDetail games={games} />} />
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
      </Routes>
    </>
  );
}
