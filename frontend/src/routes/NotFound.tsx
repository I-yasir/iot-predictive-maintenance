import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div className="card" style={{ display: "grid", gap: 12, justifyItems: "start" }}>
      <h1>Page not found</h1>
      <p className="muted">There is nothing at this address.</p>
      <Link className="btn primary" to="/overview">Go to overview</Link>
    </div>
  );
}
