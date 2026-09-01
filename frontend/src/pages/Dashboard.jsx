/**
 * pages/Dashboard.jsx — Regulator analytics dashboard (protected route).
 */
import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import api from "../api/client";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";
import StatusBadge from "../components/StatusBadge";

// ── Stat card ──────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color = "text-ink-navy" }) {
  return (
    <div className="border border-border-main bg-card-bg p-5">
      <p className="mono-label text-muted-fg mb-2">{label}</p>
      <p className={`text-3xl font-mono font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-muted-fg mt-1">{sub}</p>}
    </div>
  );
}

// ── Section title ──────────────────────────────────────────────────────────────
function SectionTitle({ children }) {
  return <h2 className="font-display font-semibold text-ink-navy mb-4 mt-8">{children}</h2>;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const user = (() => {
    try { return JSON.parse(localStorage.getItem("verified_user") || "null"); }
    catch { return null; }
  })();

  const [summary, setSummary]       = useState(null);
  const [categories, setCategories] = useState([]);
  const [platforms, setPlatforms]   = useState([]);
  const [trends, setTrends]         = useState([]);
  const [violations, setViolations] = useState({ items: [], total: 0 });
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState("");
  const [sevFilter, setSevFilter]   = useState("");

  useEffect(() => {
    if (!user) { navigate("/login"); return; }
    const load = async () => {
      setLoading(true);
      const results = await Promise.allSettled([
        api.get("/api/dashboard/summary"),
        api.get("/api/dashboard/categories"),
        api.get("/api/dashboard/platforms"),
        api.get("/api/dashboard/trends?days=30"),
        api.get("/api/dashboard/violations?limit=20"),
      ]);

      const [s, c, p, t, v] = results;

      if (s.status === "fulfilled") setSummary(s.value.data);
      if (c.status === "fulfilled") setCategories(c.value.data);
      if (p.status === "fulfilled") setPlatforms(p.value.data);
      if (t.status === "fulfilled") setTrends(t.value.data);
      if (v.status === "fulfilled") setViolations(v.value.data);

      // Show error only if ALL failed
      const allFailed = results.every(r => r.status === "rejected");
      if (allFailed) setError("Failed to load dashboard data. Make sure you are logged in and the backend is running.");

      setLoading(false);
    };
    load();
  }, []);

  const loadViolations = async (sev = sevFilter) => {
    const params = sev ? `?severity=${sev}&limit=20` : "?limit=20";
    const { data } = await api.get(`/api/dashboard/violations${params}`);
    setViolations(data);
  };

  const handleLogout = () => {
    localStorage.removeItem("verified_token");
    localStorage.removeItem("verified_user");
    navigate("/login");
  };

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-ledger">
      <p className="mono-label text-muted-fg animate-pulse">Loading dashboard…</p>
    </div>
  );

  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex-1 px-4 py-10">
        <div className="mx-auto max-w-6xl">

          {/* Dashboard header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
            <div>
              <p className="mono-label text-seal-gold mb-1">Regulator Portal</p>
              <h1 className="text-3xl font-display font-semibold text-ink-navy">Dashboard</h1>
              {user && <p className="text-sm text-muted-fg mt-1">Welcome, {user.name}</p>}
            </div>
            <div className="flex gap-3">
              <Link to="/check" className="btn-primary text-xs px-4 py-2 inline-block">
                + New Scan
              </Link>
              <button onClick={handleLogout} className="btn-outline text-xs px-4 py-2">
                Logout
              </button>
            </div>
          </div>

          {error && (
            <div className="border border-[#C41E3A]/30 bg-[#C41E3A]/5 px-4 py-3 text-sm text-[#C41E3A] mb-6">
              {error}
            </div>
          )}

          {/* Summary stats */}
          {summary && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <StatCard label="Total Scans" value={summary.total_scans} />
              <StatCard label="Compliant" value={summary.pass_count} color="text-[#16a34a]" />
              <StatCard label="Violations" value={summary.fail_count} color="text-[#C41E3A]" />
              <StatCard label="Partial" value={summary.partial_count} color="text-amber-700" />
              <StatCard label="Avg Score" value={`${summary.avg_score}`} sub="out of 100" />
              <StatCard
                label="Compliance Rate"
                value={`${summary.compliance_rate}%`}
                color={summary.compliance_rate >= 70 ? "text-[#16a34a]" : "text-[#C41E3A]"}
              />
            </div>
          )}

          {/* Trends chart */}
          {trends.length > 0 && (
            <>
              <SectionTitle>Daily Scan Trend (Last 30 Days)</SectionTitle>
              <div className="border border-border-main bg-card-bg p-5">
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={trends}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#ddd8cc" />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#7a7060" }} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: "#7a7060" }} tickLine={false} />
                    <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #ddd8cc", background: "#faf9f5" }} />
                    <Line type="monotone" dataKey="scans" stroke="#1a1a2e" strokeWidth={2} dot={false} name="Scans" />
                    <Line type="monotone" dataKey="avg_score" stroke="#9a7c2e" strokeWidth={2} dot={false} name="Avg Score" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {/* Category + Platform charts side by side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
            {categories.length > 0 && (
              <div>
                <SectionTitle>By Category</SectionTitle>
                <div className="border border-border-main bg-card-bg p-5">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={categories.slice(0, 8)} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#ddd8cc" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "#7a7060" }} tickLine={false} />
                      <YAxis dataKey="category" type="category" width={120} tick={{ fontSize: 9, fill: "#7a7060" }} tickLine={false} />
                      <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #ddd8cc", background: "#faf9f5" }} />
                      <Bar dataKey="count" fill="#1a1a2e" name="Scans" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {platforms.length > 0 && (
              <div>
                <SectionTitle>By Platform</SectionTitle>
                <div className="border border-border-main bg-card-bg p-5">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={platforms.slice(0, 8)}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#ddd8cc" vertical={false} />
                      <XAxis dataKey="platform" tick={{ fontSize: 10, fill: "#7a7060" }} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: "#7a7060" }} tickLine={false} />
                      <Tooltip contentStyle={{ fontSize: 12, border: "1px solid #ddd8cc", background: "#faf9f5" }} />
                      <Bar dataKey="count" name="Scans">
                        {platforms.map((_, i) => (
                          <Cell key={i} fill={i % 2 === 0 ? "#1a1a2e" : "#9a7c2e"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>

          {/* Violations table */}
          <SectionTitle>Recent Violations</SectionTitle>
          <div className="mb-4 flex gap-3 items-center flex-wrap">
            <span className="mono-label text-muted-fg">Filter by severity:</span>
            {["", "high", "medium"].map((s) => (
              <button
                key={s}
                onClick={() => { setSevFilter(s); loadViolations(s); }}
                className={`mono-label px-3 py-1.5 border text-xs transition-colors ${
                  sevFilter === s
                    ? "bg-ink-navy text-ink-light border-ink-navy"
                    : "border-border-main text-muted-fg hover:border-ink-navy"
                }`}
              >
                {s || "All"}
              </button>
            ))}
            <span className="text-xs text-muted-fg ml-auto">{violations.total} total violations</span>
          </div>

          <div className="border border-border-main overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-ink-navy text-ink-light">
                  {["Product", "Platform", "Field", "Rule", "Severity", "Reason", "Date"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left mono-label text-xs font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {violations.items?.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-muted-fg text-sm">No violations found.</td>
                  </tr>
                )}
                {violations.items?.map((v, i) => (
                  <tr key={i} className={i % 2 === 0 ? "bg-card-bg" : "bg-ledger"}>
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/scan/result/${v.scan_id}`}
                        className="text-ink-navy hover:text-seal-gold transition-colors font-medium"
                      >
                        {v.product_name.slice(0, 25)}{v.product_name.length > 25 ? "…" : ""}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-muted-fg">{v.platform}</td>
                    <td className="px-4 py-2.5 text-ink-navy">{v.field_label}</td>
                    <td className="px-4 py-2.5 mono-label text-seal-gold text-xs">{v.legal_reference}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={v.severity === "high" ? "FAIL" : "REVIEW"} />
                    </td>
                    <td className="px-4 py-2.5 text-muted-fg max-w-xs">
                      {v.reason.slice(0, 60)}{v.reason.length > 60 ? "…" : ""}
                    </td>
                    <td className="px-4 py-2.5 text-muted-fg text-xs font-mono">
                      {new Date(v.created_at).toLocaleDateString("en-IN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bulk upload */}
          <SectionTitle>Bulk CSV Scan</SectionTitle>
          <BulkUpload />

        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

// ── Bulk upload component ──────────────────────────────────────────────────────
function BulkUpload() {
  const [file, setFile]       = useState(null);
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setError(""); setResult(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const { data } = await api.post("/api/bulk", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(data);
    } catch (e) {
      setError(e.response?.data?.detail || "Upload failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border border-border-main bg-card-bg p-6 space-y-4">
      <p className="text-sm text-muted-fg">
        Upload a CSV with columns: <code className="font-mono bg-ledger px-1">text</code>,{" "}
        <code className="font-mono bg-ledger px-1">product_name</code>,{" "}
        <code className="font-mono bg-ledger px-1">category</code>,{" "}
        <code className="font-mono bg-ledger px-1">platform</code> (last three optional, max 200 rows).
      </p>
      <div className="flex gap-3 flex-wrap">
        <input
          type="file"
          accept=".csv"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="text-sm text-muted-fg"
        />
        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="bg-ink-navy text-ink-light px-5 py-2 text-sm font-medium disabled:opacity-60 hover:bg-opacity-90 transition-colors"
        >
          {loading ? "Processing…" : "Upload & Scan"}
        </button>
      </div>
      {error && <p className="text-sm text-[#C41E3A]">{error}</p>}
      {result && (
        <div className="border border-[#16a34a]/30 bg-[#16a34a]/5 p-4 text-sm">
          <p className="font-medium text-[#16a34a]">
            ✓ Processed {result.processed} products
          </p>
          <div className="mt-2 space-y-1 max-h-40 overflow-auto">
            {result.results.map((r) => (
              <div key={r.scan_id} className="flex gap-4 font-mono text-xs text-ink-navy">
                <Link to={`/scan/result/${r.scan_id}`} className="hover:underline text-seal-gold">
                  {r.scan_id.slice(0, 8)}
                </Link>
                <span>{r.product_name.slice(0, 30)}</span>
                <span>{r.score}/100</span>
                <span className={r.status === "PASS" ? "text-[#16a34a]" : r.status === "FAIL" ? "text-[#C41E3A]" : "text-amber-700"}>
                  {r.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
