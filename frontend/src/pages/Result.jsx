/**
 * pages/Result.jsx — Compliance scan result with score bar, field breakdown, and downloads.
 */
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import api from "../api/client";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";
import StampBadge from "../components/StampBadge";
import FieldCard from "../components/FieldCard";

function ScoreBar({ score, status }) {
  const color =
    status === "PASS"    ? "bg-[#16a34a]"  :
    status === "PARTIAL" ? "bg-amber-500"   :
                           "bg-[#C41E3A]";
  return (
    <div>
      <div className="flex justify-between items-end mb-1.5">
        <span className="mono-label text-muted-fg">Compliance Score</span>
        <span className="font-mono text-2xl font-bold text-ink-navy">{score}<span className="text-muted-fg text-sm">/100</span></span>
      </div>
      <div className="h-3 bg-border-main w-full">
        <div
          className={`h-full transition-all duration-700 ${color}`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

export default function Result() {
  const { id } = useParams();
  const [scan, setScan]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState("");

  useEffect(() => {
    api.get(`/api/scan/${id}`)
      .then(({ data }) => setScan(data))
      .catch(() => setError("Could not load scan result."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-ledger">
      <p className="mono-label text-muted-fg animate-pulse">Loading result…</p>
    </div>
  );

  if (error || !scan) return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-ledger gap-4">
      <p className="text-[#C41E3A]">{error || "Scan not found."}</p>
      <Link to="/check" className="btn-outline text-sm">← Back to Scanner</Link>
    </div>
  );

  const passCount   = scan.fields.filter((f) => f.status === "PASS").length;
  const failCount   = scan.fields.filter((f) => f.status === "FAIL").length;
  const reviewCount = scan.fields.filter((f) => f.status === "REVIEW").length;

  const handleDownloadTxt = () => {
    window.open(`http://localhost:8000/api/scan/${id}/report.txt`, "_blank");
  };
  const handleDownloadPdf = () => {
    window.open(`http://localhost:8000/api/scan/${id}/report.pdf`, "_blank");
  };

  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex-1 px-4 py-10">
        <div className="mx-auto max-w-3xl">

          {/* Back link */}
          <Link to="/check" className="mono-label text-muted-fg hover:text-ink-navy transition-colors text-xs">
            ← New Scan
          </Link>

          {/* Hero row */}
          <div className="mt-6 mb-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
            <div>
              <p className="mono-label text-seal-gold mb-1">{scan.rule_version}</p>
              <h1 className="text-2xl font-display font-semibold text-ink-navy leading-snug">
                {scan.product_name}
              </h1>
              <p className="text-xs text-muted-fg mt-1">
                {scan.category} · {scan.platform} · {scan.source_type} ·{" "}
                {new Date(scan.created_at).toLocaleString("en-IN")}
              </p>
            </div>
            <div className="shrink-0">
              <StampBadge status={scan.status} score={scan.score} />
            </div>
          </div>

          {/* Score bar */}
          <div className="border border-border-main bg-card-bg p-5 mb-4">
            <ScoreBar score={scan.score} status={scan.status} />
            <div className="flex gap-6 mt-4 text-sm">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-[#16a34a]" />
                <span className="text-muted-fg">{passCount} Pass</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-[#C41E3A]" />
                <span className="text-muted-fg">{failCount} Fail</span>
              </div>
              {reviewCount > 0 && (
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 bg-amber-500" />
                  <span className="text-muted-fg">{reviewCount} Review</span>
                </div>
              )}
            </div>
          </div>

          {/* Download row */}
          <div className="flex flex-wrap gap-3 mb-6">
            <button onClick={handleDownloadTxt} className="btn-outline text-xs px-4 py-2">
              ↓ Download .txt
            </button>
            <button onClick={handleDownloadPdf} className="btn-outline text-xs px-4 py-2">
              ↓ Download PDF
            </button>
            <button
              onClick={() => navigator.clipboard?.writeText(window.location.href)}
              className="btn-outline text-xs px-4 py-2"
            >
              🔗 Copy Link
            </button>
            <Link to="/check" className="btn-primary text-xs px-4 py-2 inline-block">
              + New Scan
            </Link>
          </div>

          {/* Field breakdown */}
          <div className="mb-6">
            <h2 className="font-display font-semibold text-ink-navy mb-3">Field Results</h2>
            <div className="space-y-1">
              {scan.fields.map((f, i) => (
                <FieldCard key={f.field_id} field={f} index={i} />
              ))}
            </div>
          </div>

          {/* Violations summary */}
          {scan.violations.length > 0 && (
            <div className="border border-[#C41E3A]/20 bg-[#C41E3A]/5 p-5">
              <h2 className="font-display font-semibold text-[#C41E3A] mb-3">
                {scan.violations.length} Violation{scan.violations.length !== 1 ? "s" : ""} Detected
              </h2>
              <ul className="space-y-3">
                {scan.violations.map((v) => (
                  <li key={v.field_id} className="text-sm">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`mono-label ${v.severity === "high" ? "text-[#C41E3A]" : "text-amber-700"}`}>
                        [{v.severity.toUpperCase()}]
                      </span>
                      <span className="font-medium text-ink-navy">{v.field_label}</span>
                      <span className="mono-label text-muted-fg">{v.legal_reference}</span>
                    </div>
                    <p className="text-muted-fg pl-1">{v.reason}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Scan meta */}
          <div className="mt-6 border-t border-border-main pt-4 text-xs text-muted-fg font-mono space-y-1">
            <div>Scan ID: {scan.id}</div>
            <div>Rule Set: {scan.rule_version}</div>
            <div>Scanned by: {scan.scanned_by}</div>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
