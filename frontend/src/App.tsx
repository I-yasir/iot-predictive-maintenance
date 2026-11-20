import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { useMe } from "./api/queries";
import { Loading } from "./components/States";
import { LiveProvider } from "./hooks/live";
import { Alerts } from "./routes/Alerts";
import { AssetDetail } from "./routes/AssetDetail";
import { AssetReport } from "./routes/AssetReport";
import { Login } from "./routes/Login";
import { ModelCard } from "./routes/ModelCard";
import { NotFound } from "./routes/NotFound";
import { Overview } from "./routes/Overview";
import { Shell } from "./routes/Shell";
import { TestPage } from "./routes/TestPage";
import { Tokens } from "./routes/Tokens";

function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const loc = useLocation();
  if (me.isPending) return <div style={{ padding: 24 }}><Loading rows={1} /></div>;
  // backend down: still render the app shell so cached data and the "unreachable" banner show
  if (me.data && me.data.auth_enabled && !me.data.authenticated) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <>{children}</>;
}

export function App({ live = true }: { live?: boolean }) {
  const nav = useNavigate();
  useEffect(() => setUnauthorizedHandler(() => nav("/login", { replace: true })), [nav]);
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/assets/:assetId/report" element={<RequireAuth><AssetReport /></RequireAuth>} />
      <Route
        path="*"
        element={
          <RequireAuth>
            <LiveProvider enabled={live}>
              <Shell>
                <Routes>
                  <Route path="/" element={<Navigate to="/overview" replace />} />
                  <Route path="/overview" element={<Overview />} />
                  <Route path="/assets/:assetId" element={<AssetDetail />} />
                  <Route path="/alerts" element={<Alerts />} />
                  <Route path="/test" element={<TestPage />} />
                  <Route path="/about/model" element={<ModelCard />} />
                  <Route path="/dev/tokens" element={<Tokens />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Shell>
            </LiveProvider>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
