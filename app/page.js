"use client";

import { useEffect, useState } from "react";

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const number = new Intl.NumberFormat("en-US");

function api(path, key, options = {}) {
  return fetch(`/api${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${key}`, ...(options.headers || {}) },
  }).then(async (response) => {
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Request failed");
    return response.json();
  });
}

function Metric({ label, value }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong></article>;
}

export default function Home() {
  const [key, setKey] = useState("");
  const [storedKey, setStoredKey] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [boxes, setBoxes] = useState([]);
  const [profitability, setProfitability] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [backup, setBackup] = useState(null);
  const [migrationMessage, setMigrationMessage] = useState("");

  const load = async (apiKey, search = "") => {
    setLoading(true); setError("");
    try {
      const [summary, boxResult, profitResult] = await Promise.all([
        api("/dashboard", apiKey),
        api(`/boxes?page_size=25&query=${encodeURIComponent(search)}`, apiKey),
        api("/profitability", apiKey),
      ]);
      setDashboard(summary); setBoxes(boxResult.items); setProfitability(profitResult.items);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    const existing = sessionStorage.getItem("nexa-password");
    if (existing) { setStoredKey(existing); load(existing); }
  }, []);

  const unlock = (event) => {
    event.preventDefault();
    sessionStorage.setItem("nexa-password", key);
    setStoredKey(key); load(key);
  };

  const restoreBackup = async (event) => {
    event.preventDefault();
    if (!backup) return;
    setLoading(true); setError(""); setMigrationMessage("");
    try {
      const form = new FormData(); form.append("file", backup);
      const result = await api("/admin/migrate-sqlite", storedKey, { method: "POST", body: form });
      setMigrationMessage(`Restore complete: ${Object.values(result.migrated).reduce((sum, value) => sum + value, 0).toLocaleString()} rows copied.`);
      await load(storedKey);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  if (!storedKey) return <main className="gate"><section className="gate-card"><p className="eyebrow">LOGIWIX LLC / ENRETAG LLC</p><h1>NeXa</h1><p>Enter the workspace password. It is retained only for this browser tab and is never bundled into the site.</p><form onSubmit={unlock}><label>Password<input autoFocus type="password" value={key} onChange={(e) => setKey(e.target.value)} required /></label><button>Open workspace</button></form>{error && <p className="error">{error}</p>}</section></main>;

  return <main className="shell">
    <header><div><p className="eyebrow">FINANCE & CUSTOMS ANALYZER</p><h1>NeXa</h1></div><button className="quiet" onClick={() => { sessionStorage.removeItem("nexa-password"); setStoredKey(""); }}>Lock</button></header>
    {error && <p className="error">{error}</p>}
    {loading && <p className="loading">Refreshing…</p>}
    {dashboard && <section className="metrics"><Metric label="Boxes" value={number.format(dashboard.box_count)} /><Metric label="Actual revenue" value={money.format(dashboard.revenue)} /><Metric label="Actual profit" value={money.format(dashboard.profit)} /><Metric label="FedEx pending" value={number.format(dashboard.fedex.pending_count)} /></section>}
    {dashboard?.box_count === 0 && <section className="panel restore"><div><p className="eyebrow">ONE-TIME SETUP</p><h2>Restore existing NeXa data</h2><p>Upload the compressed backup created from <code>data/finance_customs.db</code>. This action runs only against an empty database.</p></div><form onSubmit={restoreBackup}><input aria-label="SQLite backup" type="file" accept=".gz" onChange={(e) => setBackup(e.target.files?.[0] || null)} required /><button disabled={loading}>Restore backup</button></form>{migrationMessage && <p className="success">{migrationMessage}</p>}</section>}
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">OPERATIONS</p><h2>Boxes</h2></div><input aria-label="Search boxes" placeholder="Search tracking, customer, country…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(storedKey, query)} /></div><div className="table-wrap"><table><thead><tr><th>Tracking ID</th><th>Customer</th><th>Country</th><th>Ship date</th><th>Revenue</th><th>FedEx cost</th><th>Profit</th><th>Status</th></tr></thead><tbody>{boxes.map((box) => <tr key={box.id}><td>{box.tracking_id || "—"}</td><td>{box.customer_code || "—"}</td><td>{box.country || "—"}</td><td>{box.ship_date || "—"}</td><td>{money.format(box.revenue || 0)}</td><td>{money.format(box.actual_fedex_cost || 0)}</td><td>{money.format(box.actual_profit || 0)}</td><td><span className={box.fedex_status === "Actual" ? "badge good" : "badge"}>{box.fedex_status}</span></td></tr>)}</tbody></table></div></section>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">REPORTING</p><h2>Customer profitability</h2></div></div><div className="table-wrap"><table><thead><tr><th>Customer</th><th>Boxes</th><th>Revenue</th><th>FedEx cost</th><th>Profit</th><th>Margin</th></tr></thead><tbody>{profitability.map((row) => <tr key={row.customer_code}><td>{row.customer_code}</td><td>{row.boxes}</td><td>{money.format(row.revenue || 0)}</td><td>{money.format(row.fedex_cost || 0)}</td><td>{money.format(row.profit || 0)}</td><td>{row.margin_percent == null ? "—" : `${(row.margin_percent * 100).toFixed(1)}%`}</td></tr>)}</tbody></table></div></section>
  </main>;
}
