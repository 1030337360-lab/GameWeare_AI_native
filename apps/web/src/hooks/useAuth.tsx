import React from "react";
import { useNavigate } from "react-router-dom";
import { TOKEN_STORAGE_KEY } from "../utils/constants";
import { buildApiFetch } from "../services/api";
import { login as authLogin, register as authRegister, fetchSession, logout as authLogout } from "../services/auth";
import type { AuthContextValue, UserProfile } from "../types";

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function useAuth() {
  const context = React.useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(localStorage.getItem(TOKEN_STORAGE_KEY));
  const [user, setUser] = React.useState<UserProfile | null>(null);
  const [authenticated, setAuthenticated] = React.useState(false);
  const navigate = useNavigate();

  const apiFetch = React.useMemo(() => buildApiFetch(token), [token]);

  React.useEffect(() => {
    if (!token) {
      setAuthenticated(false);
      setUser(null);
      return;
    }
    fetchSession(token)
      .then((session) => {
        if (!session.authenticated || !session.user) throw new Error("Session expired");
        setUser(session.user);
        setAuthenticated(true);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setAuthenticated(false);
        setUser(null);
      });
  }, [token]);

  const login = React.useCallback(
    async (email: string, password: string) => {
      const response = await authLogin(email, password);
      const accessToken = response.accessToken ?? response.token;
      localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
      setToken(accessToken);
      setUser(response.user);
      setAuthenticated(true);
    },
    []
  );

  const register = React.useCallback(
    async (email: string, password: string, displayName: string) => {
      const response = await authRegister(email, password, displayName);
      const accessToken = response.accessToken ?? response.token;
      localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
      setToken(accessToken);
      setUser(response.user);
      setAuthenticated(true);
    },
    []
  );

  const logout = React.useCallback(async () => {
    if (token) {
      await authLogout(token);
    }
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setUser(null);
    setAuthenticated(false);
    navigate("/");
  }, [token, navigate]);

  const setTokenAndRefresh = React.useCallback(async (nextToken: string) => {
    const session = await fetchSession(nextToken);
    if (!session.authenticated || !session.user) throw new Error("Google login session is invalid");
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    setUser(session.user);
    setAuthenticated(true);
  }, []);

  const expiresIn = 3600; // TODO: 从登录响应中获取

  const value = React.useMemo(
    () => ({
      user,
      token,
      authenticated,
      expiresIn,
      apiFetch,
      login,
      logout,
      register,
      setTokenAndRefresh,
    }),
    [user, token, authenticated, expiresIn, apiFetch, login, logout, register, setTokenAndRefresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
