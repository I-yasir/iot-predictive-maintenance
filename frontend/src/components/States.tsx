import { AlertCircle, Cpu, Inbox, Play, RotateCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import s from "./ui.module.css";

export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: React.CSSProperties }) {
  return <div className={s.skeleton} style={{ height: h, width: w, ...style }} aria-hidden="true" />;
}

export function Loading({ label = "Loading", rows = 3, h = 120 }: { label?: string; rows?: number; h?: number }) {
  return (
    <div role="status" aria-label={label} style={{ display: "grid", gap: 12 }}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} h={h} />
      ))}
    </div>
  );
}

export function NoAssets() {
  return (
    <div className={`card ${s.empty}`}>
      <Inbox size={48} aria-hidden="true" />
      <h2>No telemetry yet</h2>
      <p className="muted">Start a dataset replay or connect an ESP32 and assets appear here as soon as they send data.</p>
      <div className={s.actions}>
        <Link className="btn primary" to="/test">
          <Play size={16} aria-hidden="true" /> Start dataset replay
        </Link>
        <Link className="btn" to="/test#esp32">
          <Cpu size={16} aria-hidden="true" /> Connect an ESP32
        </Link>
      </div>
    </div>
  );
}

export function NoMatch({ onClear }: { onClear: () => void }) {
  return (
    <div className={`card ${s.empty}`}>
      <p>No assets match these filters.</p>
      <button onClick={onClear}>Clear filters</button>
    </div>
  );
}

export function ErrorCard({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={`card ${s.errorCard}`} role="alert">
      <h2 style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <AlertCircle size={20} aria-hidden="true" /> Something went wrong
      </h2>
      <p className="muted">{message}</p>
      {onRetry ? (
        <button onClick={onRetry}>
          <RotateCw size={16} aria-hidden="true" /> Retry
        </button>
      ) : null}
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("view error", error, info.componentStack);
  }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error)
      return <ErrorCard message="This view failed to render. The rest of the dashboard still works." onRetry={() => this.setState({ error: null })} />;
    return this.props.children;
  }
}

/** Accessible data-table fallback for charts (docs/03 §3.2). */
export function DataFallback({ caption, columns, rows }: { caption: string; columns: string[]; rows: (string | number)[][] }) {
  return (
    <details>
      <summary>View data</summary>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j} className={typeof c === "number" ? "r" : undefined}>{c}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
