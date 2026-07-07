import React from "react";
import { useAuth } from "../hooks/useAuth";

export default function MaintainerPanel() {
  const { apiFetch } = useAuth();
  const [status, setStatus] = React.useState("");

  React.useEffect(() => {
    setStatus("Maintainer panel loaded");
  }, []);

  return (
    <main className="maintainer-panel">
      <h1>Maintainer Panel</h1>
      <p>{status}</p>
    </main>
  );
}
