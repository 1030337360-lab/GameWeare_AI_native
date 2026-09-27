import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export default function RegisterPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const email = (form.elements.namedItem("email") as HTMLInputElement).value;
    const password = (form.elements.namedItem("password") as HTMLInputElement).value;
    const displayName = (form.elements.namedItem("displayName") as HTMLInputElement).value;
    setError("");
    if (new TextEncoder().encode(password).length > 72) {
      setError("Password must be at most 72 bytes");
      return;
    }
    setSubmitting(true);
    try {
      await auth.register(email, password, displayName);
      navigate("/profile");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1>Register</h1>
      <form onSubmit={submit}>
        <label>Display name<input type="text" name="displayName" placeholder="Your name" autoComplete="nickname" maxLength={100} required /></label>
        <label>Email<input type="email" name="email" placeholder="you@example.com" autoComplete="email" required /></label>
        <label>Password<input type="password" name="password" placeholder="At least 8 characters" autoComplete="new-password" minLength={8} required /></label>
        <p className="auth-hint">Use at least 8 characters. Maximum 72 bytes.</p>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>{submitting ? "Creating account..." : "Create account"}</button>
      </form>
      <p>
        Already have an account? <Link to="/auth/login">Log in</Link>
      </p>
    </div>
  );
}
