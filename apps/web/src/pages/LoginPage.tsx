import React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { API_BASE_URL } from "../utils/constants";

export default function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/profile";
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const email = (form.elements.namedItem("email") as HTMLInputElement).value;
    const password = (form.elements.namedItem("password") as HTMLInputElement).value;
    setError("");
    setSubmitting(true);
    try {
      await auth.login(email, password);
      navigate(next.startsWith("/") && !next.startsWith("//") ? next : "/profile");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1>Login</h1>
      <form onSubmit={submit}>
        <label>Email<input type="email" name="email" placeholder="you@example.com" autoComplete="email" required /></label>
        <label>Password<input type="password" name="password" placeholder="Enter your password" autoComplete="current-password" required /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>{submitting ? "Signing in..." : "Log in"}</button>
      </form>
      <p><a href={`${API_BASE_URL}/auth/google/start`}>Continue with Google</a></p>
      <p>
        Don't have an account? <Link to="/auth/register">Register</Link>
      </p>
    </div>
  );
}
