import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

export default function Header() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const createTarget = auth.authenticated ? "/create" : "/auth/login?next=/create";
  const createClassName =
    auth.authenticated && location.pathname === "/create" ? "active" : "";

  return (
    <header className="header">
      <div className="logo" onClick={() => navigate("/")}>
        Gameweare
      </div>
      <nav>
        <a href="/" className={location.pathname === "/" ? "active" : ""}>
          Home
        </a>
        <a href={createTarget} className={createClassName}>
          Create
        </a>
        {auth.authenticated ? (
          <>
            <a href="/profile" className={location.pathname === "/profile" ? "active" : ""}>
              Profile
            </a>
            <button onClick={() => auth.logout()}>Logout</button>
          </>
        ) : (
          <>
            <a href="/auth/login">Login</a>
            <a href="/auth/register">Register</a>
          </>
        )}
      </nav>
    </header>
  );
}
