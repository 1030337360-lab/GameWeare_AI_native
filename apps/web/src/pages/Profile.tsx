import { ArrowRight, LogOut, Mail, Sparkles, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export default function Profile() {
  const auth = useAuth();
  const user = auth.user;

  if (!user) {
    return <div>Loading...</div>;
  }

  return (
    <main className="profile-page">
      <span className="section-kicker">YOUR SPACE</span>
      <div className="profile-heading"><div><h1>Welcome back, {user.displayName || "creator"}.</h1><p>Your place to play, create, and keep exploring.</p></div><span className="profile-avatar"><UserRound size={31} /></span></div>
      <div className="profile-fields">
        <div><Mail size={19} /><span><small>EMAIL ADDRESS</small><strong>{user.email}</strong></span></div>
        <div><UserRound size={19} /><span><small>DISPLAY NAME</small><strong>{user.displayName || "Creator"}</strong></span></div>
      </div>
      <div className="profile-actions"><Link to="/create"><Sparkles size={18} /> Create something <ArrowRight size={17} /></Link><button onClick={() => void auth.logout()}><LogOut size={17} /> Sign out</button></div>
    </main>
  );
}
