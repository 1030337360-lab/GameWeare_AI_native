import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export default function Profile() {
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth.user;

  if (!user) {
    return <div>Loading...</div>;
  }

  return (
    <main className="profile-page">
      <h1>Profile</h1>
      <p>Email: {user.email}</p>
      <p>Name: {user.displayName}</p>
      <button onClick={() => auth.logout()}>Logout</button>
    </main>
  );
}
