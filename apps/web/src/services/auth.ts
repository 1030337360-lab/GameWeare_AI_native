// 认证相关 API

import { API_BASE_URL } from "../utils/constants";
import type { AuthResponse, SessionState, UserProfile } from "../types";

async function authError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null);
  const message = body && typeof body.message === "string" && body.message.trim()
    ? body.message
    : fallback;
  return new Error(message);
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw await authError(response, response.status === 401 ? "Invalid email or password" : "Login failed");
  }
  return (await response.json()) as AuthResponse;
}

export async function register(
  email: string,
  password: string,
  displayName: string
): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, displayName }),
  });
  if (!response.ok) {
    throw await authError(response, response.status === 409 ? "Email already registered" : "Registration failed");
  }
  return (await response.json()) as AuthResponse;
}

export async function fetchSession(token: string): Promise<SessionState> {
  const response = await fetch(`${API_BASE_URL}/auth/session`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error("Session expired");
  }
  return (await response.json()) as SessionState;
}

export async function logout(token: string): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}
