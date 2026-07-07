import React from "react";
import { Link } from "react-router-dom";

interface EmptyStateProps {
  title: string;
  body: string;
}

export default function EmptyState({ title, body }: EmptyStateProps) {
  return (
    <main className="empty-state">
      <h1>{title}</h1>
      <p>{body}</p>
      <Link to="/" className="primary-action">Back home</Link>
    </main>
  );
}
