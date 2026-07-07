import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export default function AuthCallback() {
  const auth = useAuth();
  const navigate = useNavigate();

  React.useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = hash.get("access_token");
    if (!token) {
      navigate("/auth/login");
      return;
    }
    // TODO: Implement setTokenAndRefresh in useAuth
    // auth.setTokenAndRefresh(token).then(() => navigate("/profile"));
    navigate("/profile");
  }, [auth, navigate]);

  return (
    <main className="empty-state">
      <h1>Signing you in</h1>
      <p>Finishing account verification.</p>
    </main>
  );
}
