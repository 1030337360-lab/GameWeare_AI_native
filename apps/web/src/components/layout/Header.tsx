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
          <Link className="site-brand" to="/" aria-label="GameWeare 首页">
            <span className="brand-mark"><Gamepad2 size={21} strokeWidth={2.4} /></span>
            <span>Game<span className="brand-accent">Weare</span></span>
            <span className="brand-beta">BETA</span>
          </Link>

          <nav className="desktop-nav" aria-label="主导航">
            <NavLink to="/" end><Compass size={17} /> 探索</NavLink>
            <NavLink to={createTarget}><Sparkles size={17} /> 创作</NavLink>
            <NavLink to={auth.authenticated ? "/rewards" : "/auth/login?next=/rewards"}><Gift size={17} /> 奖励</NavLink>
            {(auth.user?.role === "admin" || auth.user?.role === "maintainer") && <NavLink to="/maintenance"><ShieldCheck size={17} /> 管理后台</NavLink>}
          </nav>

          <div className="header-actions">
            {auth.authenticated ? (
              <>
                <NavLink className="header-profile" to="/profile"><UserRound size={17} /> 个人中心</NavLink>
                <button className="header-signout" onClick={() => void auth.logout()}>退出登录</button>
              </>
            ) : (
              <>
                <NavLink className="header-login" to="/auth/login"><LogIn size={17} /> 登录</NavLink>
                <Link className="header-join" to="/auth/register">立即加入 <span aria-hidden="true">↗</span></Link>
              </>
            )}
          </div>
        </div>
      </header>

      <nav className="mobile-dock" aria-label="移动端导航">
        <NavLink to="/" end><Compass size={20} /><span>探索</span></NavLink>
        <Link to={createTarget} className={createActive ? "active" : ""} aria-current={createActive ? "page" : undefined}><Sparkles size={21} /><span>创作</span></Link>
        <NavLink to={auth.authenticated ? "/rewards" : "/auth/login?next=/rewards"}><Gift size={20} /><span>奖励</span></NavLink>
        {(auth.user?.role === "admin" || auth.user?.role === "maintainer") && <NavLink to="/maintenance"><ShieldCheck size={20} /><span>管理</span></NavLink>}
        <Link to={auth.authenticated ? "/profile" : "/auth/login"} className={accountActive ? "active" : ""} aria-current={accountActive ? "page" : undefined}>
          <UserRound size={20} /><span>{auth.authenticated ? "我的" : "登录"}</span>
        </Link>
      </nav>
    </>
  );
}
