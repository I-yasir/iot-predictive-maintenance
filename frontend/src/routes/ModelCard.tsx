import { useModels } from "../api/queries";
import { ErrorCard, Loading } from "../components/States";
import { absTime } from "../lib/format";
import { testMetrics } from "./AssetDetail";
import { PageHead } from "./Shell";

export function ModelCard() {
  const q = useModels();
  if (q.isPending) return <><PageHead title="Model card" /><Loading rows={2} /></>;
  if (q.isError) return <ErrorCard message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  return (
    <>
      <PageHead title="Model card" />
      <p className="muted">One model bundle per C-MAPSS profile. RUL is predicted in cycles and capped at 125. Intervals are P10–P90 quantiles widened by split conformal calibration.</p>
      <div className="card table-wrap" style={{ maxHeight: "none", padding: 0 }}>
        <table>
          <caption className="sr-only">Active models</caption>
          <thead><tr><th scope="col">Profile</th><th scope="col">Version</th><th scope="col">Point estimate</th><th scope="col" className="r">Test RMSE</th><th scope="col" className="r">NASA score</th><th scope="col">Basis</th><th scope="col" className="r">CV RMSE</th><th scope="col" className="r">Window</th><th scope="col" className="r">Features</th><th scope="col">Created</th></tr></thead>
          <tbody>
            {q.data.items.map((m) => {
              const t = testMetrics(m);
              const capped = t.basis?.includes("capped");
              const cv = (m.cv ?? {}) as Record<string, unknown>;
              return (
                <tr key={m.profile}>
                  <td>{m.profile}</td>
                  <td className="mono">{m.model_version}</td>
                  <td style={{ whiteSpace: "normal" }}>{m.point_estimate}</td>
                  <td className="r">{(capped ? t.rmseCapped : t.rmse)?.toFixed(2) ?? "—"}</td>
                  <td className="r">{(capped ? t.scoreCapped : t.score)?.toFixed(0) ?? "—"}</td>
                  <td>{t.basis ?? "—"}</td>
                  <td className="r">{typeof cv.rmse_mean === "number" ? cv.rmse_mean.toFixed(2) : "—"}</td>
                  <td className="r">{m.window}</td>
                  <td className="r">{m.feature_names.length}</td>
                  <td>{m.created_utc ? absTime(m.created_utc) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {q.data.items.map((m) => (
        <details className="card" key={m.profile}>
          <summary style={{ font: "var(--type-h2)", color: "var(--text-primary)" }}>{m.profile} features and sensors</summary>
          <p style={{ marginTop: 8 }}><strong>Sensors:</strong> <span className="mono">{m.sensors_used.join(", ")}</span></p>
          <p className="mono muted" style={{ marginTop: 8, wordBreak: "break-word" }}>{m.feature_names.join(", ")}</p>
        </details>
      ))}
    </>
  );
}
