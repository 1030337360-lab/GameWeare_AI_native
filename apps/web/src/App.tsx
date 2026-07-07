import React from "react";
import type { Game } from "./types";
import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
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
  const [games, setGames] = React.useState<Game[]>([]);
  const [availableTags, setAvailableTags] = React.useState<string[]>([]);

  function updateGame(game: Game) {
    setGames((prev) => prev.map((g) => (g.id === game.id ? game : g)));
  }

  // TODO: Load games data

  return (
    <AuthProvider>
      <Header />
      <Routes>
        <Route
          path="/"
          element={<Home games={games} availableTags={availableTags} search="" selectedTag="" />}
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
    </AuthProvider>
  );
}
