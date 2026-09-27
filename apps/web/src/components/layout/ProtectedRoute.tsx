import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const location = useLocation();

  // A stored token is checked asynchronously after a full page reload.
  if (auth.token && !auth.authenticated) {
    return <div role="status" style={{ minHeight: "50vh", display: "grid", placeItems: "center" }}>正在验证登录状态…</div>;
  }

  if (!auth.authenticated) {
    return <Navigate to={`/auth/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }

  return <>{children}</>;
}
