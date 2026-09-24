import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { API_BASE_URL } from "../utils/constants";

export default function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/profile";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const email = (form.elements.namedItem("email") as HTMLInputElement).value;
    const password = (form.elements.namedItem("password") as HTMLInputElement).value;
    try {
      await auth.login(email, password);
      navigate(next);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Login failed");
    }
  }

  return (
    <div className="auth-page">
      <h1>Login</h1>
      <form onSubmit={submit}>
        <input type="email" name="email" placeholder="Email" required />
        <input type="password" name="password" placeholder="Password" required />
        <button type="submit">Login</button>
      </form>
      <p><a href={`${API_BASE_URL}/auth/google/start`}>Continue with Google</a></p>
      <p>
        Don't have an account? <a href="/auth/register">Register</a>
      </p>
    </div>
  );
}
