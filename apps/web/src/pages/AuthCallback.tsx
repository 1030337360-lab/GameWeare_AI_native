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
    void auth.setTokenAndRefresh(token)
      .then(() => {
        window.history.replaceState(null, "", "/auth/callback");
        navigate("/profile", { replace: true });
      })
      .catch(() => navigate("/auth/login?oauth_error=invalid_session", { replace: true }));
  }, [auth.setTokenAndRefresh, navigate]);

  return (
    <main className="empty-state">
      <h1>Signing you in</h1>
      <p>Finishing account verification.</p>
    </main>
  );
}
