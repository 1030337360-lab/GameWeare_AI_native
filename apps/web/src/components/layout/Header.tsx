import { Compass, Gamepad2, Gift, LogIn, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

export default function Header() {
  const auth = useAuth();
  const location = useLocation();
  const createTarget = auth.authenticated ? "/create" : "/auth/login?next=/create";
  const createActive = location.pathname === "/create" ||
    (!auth.authenticated && location.pathname === "/auth/login" && new URLSearchParams(location.search).get("next") === "/create");
  const accountActive = auth.authenticated ? location.pathname === "/profile" : location.pathname === "/auth/login" && !createActive;

  return (
    <>
      <header className="site-header">
        <div className="site-header-inner">
          <Link className="site-brand" to="/" aria-label="Gameweare home">
            <span className="brand-mark"><Gamepad2 size={21} strokeWidth={2.4} /></span>
            <span>game<span className="brand-accent">weare</span></span>
            <span className="brand-beta">BETA</span>
          </Link>

          <nav className="desktop-nav" aria-label="Main navigation">
            <NavLink to="/" end><Compass size={17} /> Explore</NavLink>
            <NavLink to={createTarget}><Sparkles size={17} /> Create</NavLink>
            <NavLink to={auth.authenticated ? "/rewards" : "/auth/login?next=/rewards"}><Gift size={17} /> Rewards</NavLink>
            {(auth.user?.role === "admin" || auth.user?.role === "maintainer") && <NavLink to="/maintenance"><ShieldCheck size={17} /> 管理后台</NavLink>}
          </nav>

          <div className="header-actions">
            {auth.authenticated ? (
              <>
                <NavLink className="header-profile" to="/profile"><UserRound size={17} /> Profile</NavLink>
                <button className="header-signout" onClick={() => void auth.logout()}>Sign out</button>
              </>
            ) : (
              <>
                <NavLink className="header-login" to="/auth/login"><LogIn size={17} /> Log in</NavLink>
                <Link className="header-join" to="/auth/register">Join now <span aria-hidden="true">↗</span></Link>
              </>
            )}
          </div>
        </div>
      </header>

      <nav className="mobile-dock" aria-label="Mobile navigation">
        <NavLink to="/" end><Compass size={20} /><span>Explore</span></NavLink>
        <Link to={createTarget} className={createActive ? "active" : ""} aria-current={createActive ? "page" : undefined}><Sparkles size={21} /><span>Create</span></Link>
        <NavLink to={auth.authenticated ? "/rewards" : "/auth/login?next=/rewards"}><Gift size={20} /><span>Rewards</span></NavLink>
        {(auth.user?.role === "admin" || auth.user?.role === "maintainer") && <NavLink to="/maintenance"><ShieldCheck size={20} /><span>管理</span></NavLink>}
        <Link to={auth.authenticated ? "/profile" : "/auth/login"} className={accountActive ? "active" : ""} aria-current={accountActive ? "page" : undefined}>
          <UserRound size={20} /><span>{auth.authenticated ? "Profile" : "Log in"}</span>
        </Link>
      </nav>
    </>
  );
}
