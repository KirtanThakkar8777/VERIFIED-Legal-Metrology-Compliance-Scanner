/**
 * pages/FontAnalysis.jsx — Rule 9 / Schedule II font size & PDP compliance analyser.
 */
import { useState, useRef } from "react";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";
import StatusBadge from "../components/StatusBadge";
import api from "../api/client";

// ── Schedule II reference table ──────────────────────────────────────────────
const SCHEDULE = [
  { label: "≤ 200 cm²",      min: 1, max: 200 },
  { label: "201 – 500 cm²",  min: 2, max: 500 },
  { label: "501 – 2500 cm²", min: 4, max: 2500 },
  { label: "> 2500 cm²",     min: 6, max: Infinity },
];

function scheduleRow(area) {
  return SCHEDULE.find((r) => area <= r.max) ?? SCHEDULE[SCHEDULE.length - 1];
}

// ── Tiny stat box ─────────────────────────────────────────────────────────────
function Stat({ label, value, color = "text-ink-navy" }) {
  return (
    <div className="border border-border-main bg-card-bg p-4 text-center">
      <p className="mono-label text-muted-fg mb-1">{label}</p>
      <p className={`text-xl font-mono font-bold ${color}`}>{value}</p>
    </div>
  );
}

export default function FontAnalysis() {
  const [imageFile, setImageFile]   = useState(null);
  const [imagePreview, setPreview]  = useState(null);
  const [area, setArea]             = useState(200);
  const [refWidth, setRefWidth]     = useState("");
  const [totalSurface, setTotal]    = useState("");
  const [pdpArea, setPdpArea]       = useState("");
  const [result, setResult]         = useState(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState("");
  const fileRef = useRef(null);

  const row = scheduleRow(area);

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setImageFile(f);
    setPreview(URL.createObjectURL(f));
    setResult(null);
    setError("");
  };

  const handleAnalyse = async () => {
    if (!imageFile) { setError("Please upload an image first."); return; }
    setError(""); setLoading(true); setResult(null);

    const form = new FormData();
    form.append("file", imageFile);
    form.append("package_area_cm2", area);
    if (refWidth)    form.append("reference_width_mm", refWidth);
    if (totalSurface) form.append("total_surface_cm2", totalSurface);
    if (pdpArea)     form.append("pdp_area_cm2", pdpArea);

    try {
      const { data } = await api.post("/api/font/analyse", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      setResult(data);
    } catch (e) {
      setError(e.response?.data?.detail || "Analysis failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (s) =>
    s === "PASS" ? "text-[#16a34a]" : s === "FAIL" ? "text-[#C41E3A]" : "text-amber-700";

  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex-1 px-4 py-10">
        <div className="mx-auto max-w-3xl">

          {/* Header */}
          <div className="mb-8">
            <p className="mono-label text-seal-gold mb-1">Rule 9 · Schedule II</p>
            <h1 className="text-3xl font-display font-semibold text-ink-navy">
              Font Size & PDP Analysis
            </h1>
            <p className="text-sm text-muted-fg mt-2">
              Upload a product label image to measure font heights and verify compliance
              with Schedule II minimum font size requirements.
            </p>
          </div>

          {/* Schedule II quick reference */}
          <div className="border border-border-main bg-card-bg p-5 mb-6">
            <p className="mono-label text-muted-fg mb-3">Schedule II — Minimum Font Heights</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {SCHEDULE.map((r) => (
                <div
                  key={r.label}
                  className={`border p-3 text-center transition-colors ${
                    r.max >= area && (SCHEDULE[SCHEDULE.indexOf(r) - 1]?.max ?? -1) < area
                      ? "border-seal-gold bg-seal-gold/5"
                      : "border-border-main"
                  }`}
                >
                  <p className="mono-label text-muted-fg text-[9px] mb-1">{r.label}</p>
                  <p className="text-lg font-mono font-bold text-ink-navy">{r.min} mm</p>
                </div>
              ))}
            </div>
          </div>

          {/* Input form */}
          <div className="border border-border-main bg-card-bg p-6 space-y-5 mb-6">

            {/* Image upload */}
            <div>
              <label className="mono-label text-muted-fg block mb-2">Label / Packaging Image</label>
              <div
                onClick={() => fileRef.current?.click()}
                className="border-2 border-dashed border-border-main bg-ledger/50 p-8 text-center cursor-pointer hover:border-ink-navy transition-colors"
              >
                {imagePreview ? (
                  <img
                    src={imagePreview}
                    alt="Label preview"
                    className="max-h-48 mx-auto object-contain"
                  />
                ) : (
                  <div className="space-y-2">
                    <p className="text-3xl">🏷️</p>
                    <p className="text-sm text-muted-fg">Click to upload label image</p>
                    <p className="text-xs text-muted-fg">PNG · JPG · WEBP</p>
                  </div>
                )}
              </div>
              <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
              {imageFile && (
                <p className="text-xs text-muted-fg mt-1">{imageFile.name} — {(imageFile.size / 1024).toFixed(1)} KB</p>
              )}
            </div>

            {/* Package area slider */}
            <div>
              <div className="flex justify-between mb-1">
                <label className="mono-label text-muted-fg">Package Display Area</label>
                <span className="mono-label text-seal-gold">{area} cm²</span>
              </div>
              <input
                type="range" min={10} max={5000} step={10}
                value={area}
                onChange={(e) => setArea(Number(e.target.value))}
                className="w-full accent-[#8b6914]"
              />
              <div className="flex justify-between text-xs text-muted-fg mt-1">
                <span>10 cm²</span>
                <span className="text-seal-gold font-medium">
                  Required: ≥ {row.min} mm ({row.label})
                </span>
                <span>5000 cm²</span>
              </div>
            </div>

            {/* Optional inputs */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="mono-label text-muted-fg mb-1 block">Label Width (mm)</label>
                <input
                  type="number" min="1" placeholder="e.g. 80"
                  value={refWidth}
                  onChange={(e) => setRefWidth(e.target.value)}
                  className="w-full border border-border-main bg-ledger px-3 py-2 text-sm text-ink-navy font-mono focus:outline-none focus:border-ink-navy"
                />
                <p className="text-xs text-muted-fg mt-0.5">For accurate px→mm scale</p>
              </div>
              <div>
                <label className="mono-label text-muted-fg mb-1 block">Total Surface (cm²)</label>
                <input
                  type="number" min="1" placeholder="e.g. 500"
                  value={totalSurface}
                  onChange={(e) => setTotal(e.target.value)}
                  className="w-full border border-border-main bg-ledger px-3 py-2 text-sm text-ink-navy font-mono focus:outline-none focus:border-ink-navy"
                />
                <p className="text-xs text-muted-fg mt-0.5">For PDP Rule 9 check</p>
              </div>
              <div>
                <label className="mono-label text-muted-fg mb-1 block">PDP Area (cm²)</label>
                <input
                  type="number" min="1" placeholder="e.g. 210"
                  value={pdpArea}
                  onChange={(e) => setPdpArea(e.target.value)}
                  className="w-full border border-border-main bg-ledger px-3 py-2 text-sm text-ink-navy font-mono focus:outline-none focus:border-ink-navy"
                />
                <p className="text-xs text-muted-fg mt-0.5">Principal display panel area</p>
              </div>
            </div>

            {error && (
              <div className="border border-[#C41E3A]/30 bg-[#C41E3A]/5 px-4 py-2 text-sm text-[#C41E3A]">
                {error}
              </div>
            )}

            <button
              onClick={handleAnalyse}
              disabled={!imageFile || loading}
              className="w-full bg-ink-navy text-ink-light py-3 text-sm font-medium tracking-wide hover:bg-opacity-90 transition-all disabled:opacity-60 disabled:cursor-not-allowed lift"
            >
              {loading ? (
                <span className="animate-pulse">Analysing font heights… (may take ~30s)</span>
              ) : (
                "▶  Analyse Font Compliance"
              )}
            </button>
          </div>

          {/* Results */}
          {result && (
            <div className="space-y-5 animate-settle">

              {/* Verdict banner */}
              <div className={`border-2 p-5 ${
                result.overall_status === "PASS"
                  ? "border-[#16a34a] bg-[#16a34a]/5"
                  : result.overall_status === "FAIL"
                  ? "border-[#C41E3A] bg-[#C41E3A]/5"
                  : "border-amber-500 bg-amber-50"
              }`}>
                <div className="flex items-center gap-3 mb-2">
                  <StatusBadge status={result.overall_status} />
                  <span className="mono-label text-muted-fg">Schedule II · Rule 9</span>
                </div>
                <p className={`text-sm font-medium ${statusColor(result.overall_status)}`}>
                  {result.verdict}
                </p>
              </div>

              {/* Key metrics */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat label="Words Detected"   value={result.word_count} />
                <Stat label="Smallest Font"    value={`${result.smallest_mm} mm`}
                  color={result.smallest_mm >= result.min_required_mm ? "text-[#16a34a]" : "text-[#C41E3A]"} />
                <Stat label="Average Font"     value={`${result.avg_mm} mm`} />
                <Stat label="Non-Compliant"    value={result.non_compliant_count}
                  color={result.non_compliant_count === 0 ? "text-[#16a34a]" : "text-[#C41E3A]"} />
              </div>

              {/* Scale info */}
              <div className="border border-border-main bg-card-bg px-4 py-3 text-xs text-muted-fg font-mono flex flex-wrap gap-4">
                <span>Min required: <strong className="text-ink-navy">{result.min_required_mm} mm</strong></span>
                <span>Package area: <strong className="text-ink-navy">{result.package_area_cm2} cm²</strong></span>
                <span>Scale: <strong className="text-ink-navy">{result.px_per_mm} px/mm</strong></span>
              </div>

              {/* PDP result */}
              {result.pdp && (
                <div className={`border p-4 ${
                  result.pdp.status === "PASS"
                    ? "border-[#16a34a]/40 bg-[#16a34a]/5"
                    : "border-[#C41E3A]/40 bg-[#C41E3A]/5"
                }`}>
                  <div className="flex items-center gap-3 mb-1">
                    <StatusBadge status={result.pdp.status} />
                    <span className="mono-label text-muted-fg">PDP · Rule 9</span>
                  </div>
                  <p className="text-sm text-ink-navy">{result.pdp.verdict}</p>
                  <p className="text-xs text-muted-fg mt-1">
                    PDP: {result.pdp.pdp_area_cm2} cm² of {result.pdp.total_surface_cm2} cm²
                    = {result.pdp.pdp_percentage}% (required ≥ 40%)
                  </p>
                </div>
              )}

              {/* Word measurements table */}
              {result.measurements.length > 0 && (
                <div>
                  <h2 className="font-display font-semibold text-ink-navy mb-3">
                    Word Measurements ({result.measurements.length})
                  </h2>
                  <div className="border border-border-main overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-ink-navy text-ink-light">
                          {["Text", "Height (px)", "Height (mm)", "Confidence", "Status"].map((h) => (
                            <th key={h} className="px-3 py-2 text-left mono-label font-normal">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.measurements.map((m, i) => {
                          const pass = m.height_mm >= result.min_required_mm;
                          return (
                            <tr key={i} className={`${i % 2 === 0 ? "bg-card-bg" : "bg-ledger"} ${!pass ? "bg-[#C41E3A]/5" : ""}`}>
                              <td className="px-3 py-2 font-mono text-ink-navy">{m.text}</td>
                              <td className="px-3 py-2 text-muted-fg">{m.height_px}</td>
                              <td className={`px-3 py-2 font-mono font-bold ${pass ? "text-[#16a34a]" : "text-[#C41E3A]"}`}>
                                {m.height_mm}
                              </td>
                              <td className="px-3 py-2 text-muted-fg">{Math.round(m.confidence * 100)}%</td>
                              <td className="px-3 py-2">
                                <StatusBadge status={pass ? "PASS" : "FAIL"} />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
