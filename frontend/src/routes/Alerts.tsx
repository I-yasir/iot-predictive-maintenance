import { useSearchParams } from "react-router-dom";
import { useAckAlert, useAlerts } from "../api/queries";
import { StateChip } from "../components/StateChip";
import { ErrorCard, Loading } from "../components/States";
import { Link } from "react-router-dom";
import { absTime, fmtRul } from "../lib/format";
import { PageHead, useActionsDisabled } from "./Shell";

export function Alerts() {
  const [p, setP] = useSearchParams();
  const params = { state: p.get("state") ?? undefined, asset: p.get("asset") ?? undefined, ack: p.get("ack") ?? undefined, limit: "500" };
  const q = useAlerts(params);
  const ack = useAckAlert();
  const disabled = useActionsDisabled();
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(p);
    if (v) n.set(k, v);
    else n.delete(k);
    setP(n, { replace: true });
  };
  return (
    <>
      <PageHead title="Alerts" />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }} role="search">
        <label>New state
          <select value={params.state ?? ""} onChange={(e) => set("state", e.target.value)}>
            <option value="">All</option><option value="CRITICAL">Critical</option><option value="WARNING">Warning</option><option value="HEALTHY">Healthy</option>
            <option value="OFFLINE">Offline</option><option value="DEGRADED_DATA">Data issue</option>
          </select>
        </label>
        <label>Asset<input value={params.asset ?? ""} onChange={(e) => set("asset", e.target.value)} placeholder="exact asset ID" /></label>
        <label>Acknowledged
          <select value={params.ack ?? ""} onChange={(e) => set("ack", e.target.value)}>
            <option value="">Any</option><option value="false">Not yet</option><option value="true">Yes</option>
          </select>
        </label>
      </div>
      {q.isPending ? <Loading rows={1} h={300} /> : q.isError ? <ErrorCard message={(q.error as Error).message} onRetry={() => void q.refetch()} /> : !q.data.items.length ? (
        <div className="card"><p className="muted">No alerts match.</p></div>
      ) : (
        <div className="card table-wrap" style={{ maxHeight: "70vh", padding: 0 }}>
          <table>
            <caption className="sr-only">Alert log</caption>
            <thead><tr><th scope="col">Time</th><th scope="col">Asset</th><th scope="col" className="r">Cycle</th><th scope="col">Transition</th><th scope="col" className="r">RUL</th><th scope="col">Reason</th><th scope="col">Acknowledged</th></tr></thead>
            <tbody>
              {q.data.items.map((a) => (
                <tr key={a.alert_id}>
                  <td>{absTime(a.created_at)}</td>
                  <td className="mono"><Link to={`/assets/${encodeURIComponent(a.asset_id)}?cycle=${a.cycle}`}>{a.asset_id}</Link></td>
                  <td className="r">{a.cycle}</td>
                  <td><StateChip state={a.from_state} /> → <StateChip state={a.to_state} /></td>
                  <td className="r">{fmtRul(a.rul_pred)}</td>
                  <td className="muted">{a.reason ?? ""}</td>
                  <td>{a.acknowledged_at ? <span className="muted">{a.acknowledged_by} · {absTime(a.acknowledged_at)}</span> : <button disabled={disabled} onClick={() => ack.mutate(a.alert_id)}>Acknowledge</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
