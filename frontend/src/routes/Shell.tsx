import { Activity, Bell, Brain, FlaskConical, LayoutGrid, Moon, Sun, WifiOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ErrorBoundary } from "../components/States";
import uiStyles from "../components/ui.module.css";
import { useLive } from "../hooks/live";
import { clockTime } from "../lib/format";
import s from "./shell.module.css";

const NAV = [
  { to: "/overview", label: "Overview", icon: LayoutGrid },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/test", label: "Test & Simulation", icon: FlaskConical },
  { to: "/about/model", label: "Model", icon: Brain },
];

type Theme = "dark" | "light";
function initialTheme(): Theme {
  try {
    const t = localStorage.getItem("pdm-theme");
    if (t === "dark" || t === "light") return t;
  } catch {
    /* storage blocked */
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("pdm-theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return [theme, setTheme];
}

export function ConnectionIndicator() {
  const live = useLive();
  if (!live.backend.reachable)
    return <span className={`${s.conn} ${s.down}`} role="status"><WifiOff size={14} aria-hidden="true" /> Offline</span>;
  if (live.ws === "live") return <span className={`${s.conn} ${s.live}`} role="status"><Activity size={14} aria-hidden="true" /> Live</span>;
  return (
    <span className={`${s.conn} ${s.reconnecting}`} role="status" title={live.retryInMs ? `Retrying in ${Math.round(live.retryInMs / 1000)} s` : undefined}>
      <Activity size={14} aria-hidden="true" /> Reconnecting…
    </span>
  );
}

export function Banners() {
  const live = useLive();
  if (!live.backend.reachable) {
    const at = live.backend.lastOkAt ? clockTime(live.backend.lastOkAt) : "before this page loaded";
    return (
      <div className={`${uiStyles.banner} ${uiStyles.bannerDown}`} role="alert">
        <WifiOff size={16} aria-hidden="true" /> Backend unreachable — showing last known data from {at}. Actions are disabled.
      </div>
    );
  }
  if (live.stale)
    return (
      <div className={`${uiStyles.banner} ${uiStyles.bannerStale}`} role="status">
        Live updates paused, reconnecting. Values may be stale.
      </div>
    );
  return null;
}

export function Shell({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useTheme();
  const loc = useLocation();
  const live = useLive();
  return (
    <div className={s.app}>
      <a href="#main" className="skip-link">Skip to content</a>
      <header className={s.top}>
        <Link to="/overview" className={s.brand} aria-label="PdM-Live overview">
          <Activity size={20} color="var(--accent)" aria-hidden="true" />
          <span className={s.brandText}>PdM-Live</span>
        </Link>
        <span className={s.spacer} />
        <ConnectionIndicator />
        <button className="ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
          {theme === "dark" ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
        </button>
      </header>
      <Banners />
      <div className={s.body}>
        <nav className={s.rail} aria-label="Main">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={s.navLink} title={label}>
              <Icon size={20} aria-hidden="true" />
              <span className={s.navLabel}>{label}</span>
            </NavLink>
          ))}
        </nav>
        <main className={s.main} id="main" tabIndex={-1}>
          <ErrorBoundary resetKey={loc.pathname}>{children}</ErrorBoundary>
        </main>
      </div>
      <div className="sr-only" aria-live={live.lastAlert?.to_state === "CRITICAL" ? "assertive" : "polite"}>
        {live.lastAlert ? `Alert: ${live.lastAlert.asset_id} ${live.lastAlert.from_state} to ${live.lastAlert.to_state}` : ""}
      </div>
    </div>
  );
}

export function PageHead({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className={s.pageHead}>
      <h1>{title}</h1>
      {children ? <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>{children}</div> : null}
    </div>
  );
}

/** true when write actions must be disabled (backend unreachable). */
export function useActionsDisabled(): boolean {
  return !useLive().backend.reachable;
}
