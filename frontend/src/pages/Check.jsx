/**
 * pages/Check.jsx — Multi-tab product compliance scanner (Text | URL | Image).
 *
 * EXISTING FEATURES: Paste Text, OCR Image, Run Compliance Scan — all unchanged.
 * UPGRADED: Product URL tab → full E-Commerce Intelligence Scanner with
 *   async job polling, step progress panel, and auto textarea population.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

const TABS = [
  { id: "text",  label: "Paste Text",  icon: "📋" },
  { id: "url",   label: "Product URL", icon: "🔗" },
  { id: "image", label: "Label Image", icon: "📸" },
];

const SAMPLE_TEXT = `Manufactured by: Hindustan Unilever Limited
Address: 165/166, Backbay Reclamation, Churchgate, Mumbai - 400 020, Maharashtra, India
Net Weight: 200g
MRP: Rs. 85.00 (Incl. of all taxes)
Mfg Date: Jan 2025
Best Before: 12 Months from manufacturing
Consumer Care: 1800 425 1000 | consumercare@hul.com
Country of Origin: India
FSSAI Lic No.: 10013022002115`;

// ── Progress Step Component ───────────────────────────────────────────────────
function ScanStep({ label, done, error }) {
  const icon = error
    ? "✗"
    : label.startsWith("✓")
    ? null
    : label.startsWith("⚠")
    ? null
    : done
    ? "✓"
    : "⟳";

  const color = error || label.startsWith("✗")
    ? "text-[#C41E3A]"
    : label.startsWith("⚠")
    ? "text-amber-700"
    : label.startsWith("✓") || done
    ? "text-[#16a34a]"
    : "text-ink-navy animate-pulse";

  return (
    <div className={`text-xs font-mono py-0.5 ${color}`}>
      {icon && <span className="mr-1">{icon}</span>}
      {label}
    </div>
  );
}

// ── Progress Panel ────────────────────────────────────────────────────────────
function ScanProgress({ steps, platform, status }) {
  return (
    <div className="border border-border-main bg-card-bg p-4 mt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="mono-label text-muted-fg text-xs">PRODUCT URL SCAN</p>
        {platform && platform !== "Detecting..." && (
          <span className="mono-label text-xs bg-ink-navy text-ink-light px-2 py-0.5">
            {platform}
          </span>
        )}
      </div>
      <div className="space-y-0.5 max-h-56 overflow-y-auto">
        {steps.map((step, i) => (
          <ScanStep
            key={i}
            label={step.label}
            done={step.done}
            error={!!step.error}
          />
        ))}
        {status === "processing" && steps.length === 0 && (
          <ScanStep label="Connecting..." done={false} />
        )}
      </div>
    </div>
  );
}

// ── OCR Image Card ─────────────────────────────────────────────────────────────
// Compliance signal pill definitions — maps signal key → display label
const SIGNAL_PILLS = [
  { key: "has_fssai",        label: "FSSAI",    color: "bg-green-100 text-green-800 border-green-300" },
  { key: "has_mrp",          label: "MRP",      color: "bg-blue-100  text-blue-800  border-blue-300"  },
  { key: "has_manufacturer", label: "Mfr.",     color: "bg-blue-100  text-blue-800  border-blue-300"  },
  { key: "has_net_qty",      label: "Net Qty",  color: "bg-blue-100  text-blue-800  border-blue-300"  },
  { key: "has_consumer_care",label: "Consumer", color: "bg-slate-100 text-slate-700 border-slate-300" },
  { key: "has_date_batch",   label: "Date/Lot", color: "bg-slate-100 text-slate-700 border-slate-300" },
  { key: "has_country",      label: "Origin",   color: "bg-slate-100 text-slate-700 border-slate-300" },
];

function OcrImageCard({ img, rank, onClick }) {
  const [failed, setFailed]       = useState(false);
  const [showReason, setShowReason] = useState(false);

  const score   = img.score   ?? null;
  const reason  = img.reason  ?? "";
  const signals = img.ocr_signals ?? {};

  // Active signal pills (only show what was actually detected)
  const activePills = SIGNAL_PILLS.filter(p => signals[p.key]);
  const isMarketingOnly = signals.is_marketing_only;

  return (
    <div className="group relative border border-border-main bg-ledger flex flex-col overflow-hidden
                    transition-all duration-200 hover:shadow-md hover:border-ink-navy/40 hover:-translate-y-0.5">

      {/* Clickable image area */}
      <div
        className="relative bg-[#f5f2ec] flex items-center justify-center cursor-pointer"
        style={{ aspectRatio: "1 / 1" }}
        onClick={() => !failed && onClick(img.url)}
        title={failed ? "Image unavailable" : `Click to enlarge — OCR Image ${String(rank).padStart(2, "0")}`}
      >
        {failed ? (
          <div className="flex flex-col items-center justify-center gap-1 px-2 py-4 text-center w-full h-full">
            <span className="text-2xl">📷</span>
            <p className="text-[10px] font-mono text-muted-fg leading-tight">IMAGE<br/>UNAVAILABLE</p>
          </div>
        ) : (
          <>
            <img
              src={img.url}
              alt={`OCR Image ${String(rank).padStart(2, "0")}`}
              onError={() => setFailed(true)}
              className="w-full h-full object-contain"
              loading="lazy"
            />
            {/* Hover overlay */}
            <div className="absolute inset-0 bg-ink-navy/0 group-hover:bg-ink-navy/60 transition-all duration-200
                            flex items-center justify-center opacity-0 group-hover:opacity-100">
              <span className="mono-label text-ink-light text-[10px] tracking-widest border border-ink-light/60 px-2 py-1">
                VIEW IMAGE
              </span>
            </div>
          </>
        )}
      </div>

      {/* Compliance signal pills */}
      {(activePills.length > 0 || isMarketingOnly) && (
        <div className="flex flex-wrap gap-0.5 px-2 pt-1.5">
          {activePills.map(p => (
            <span key={p.key}
              className={`inline-block text-[8px] font-mono font-semibold px-1 py-0.5 border rounded-sm ${p.color}`}>
              {p.label} ✓
            </span>
          ))}
          {isMarketingOnly && (
            <span className="inline-block text-[8px] font-mono font-semibold px-1 py-0.5 border rounded-sm
                             bg-red-50 text-red-700 border-red-300">
              MARKETING ✗
            </span>
          )}
        </div>
      )}

      {/* Footer: label + score + why-selected toggle */}
      <div className="px-2 pt-1.5 pb-1 border-t border-border-main bg-card-bg mt-auto">
        <div className="flex items-center justify-between">
          <p className="mono-label text-muted-fg text-[10px] tracking-wider">
            OCR IMAGE {String(rank).padStart(2, "0")}
          </p>
          {score !== null && (
            <span className="text-[10px] font-mono text-ink-navy font-semibold">
              {score > 0 ? "+" : ""}{score}
            </span>
          )}
        </div>

        {/* Collapsible "Why selected?" */}
        {reason && (
          <div className="mt-0.5">
            <button
              className="text-[9px] font-mono text-muted-fg hover:text-ink-navy transition-colors underline decoration-dotted"
              onClick={(e) => { e.stopPropagation(); setShowReason(r => !r); }}
            >
              {showReason ? "▲ hide" : "▾ why selected?"}
            </button>
            {showReason && (
              <p className="text-[9px] font-mono text-muted-fg mt-0.5 leading-tight break-words">
                {reason}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


// ── OCR Image Panel ────────────────────────────────────────────────────────────
function OcrImagePanel({ images, scanStatus, onOpenLightbox }) {
  if (!images || images.length === 0) return null;

  const isOcrRunning = scanStatus === "processing";

  return (
    <div className="border border-border-main bg-card-bg p-4 mt-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <p className="mono-label text-muted-fg text-xs">OCR SELECTED IMAGES</p>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-muted-fg">
            {images.length} image{images.length !== 1 ? "s" : ""}
          </span>
          {isOcrRunning && (
            <span className="mono-label text-[10px] text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5">
              ⟳ OCR RUNNING
            </span>
          )}
          {!isOcrRunning && (
            <span className="mono-label text-[10px] text-[#16a34a] bg-[#16a34a]/5 border border-[#16a34a]/30 px-1.5 py-0.5">
              ✓ OCR COMPLETE
            </span>
          )}
        </div>
      </div>

      {/* Image grid — 4 col desktop, 2 col tablet, 1 col mobile */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {images.map((img) => (
          <OcrImageCard
            key={img.rank}
            img={img}
            rank={img.rank}
            onClick={onOpenLightbox}
          />
        ))}
      </div>

      <p className="text-[10px] text-muted-fg font-mono mt-2">
        These are the exact images being analysed by OCR for compliance data extraction.
      </p>
    </div>
  );
}

// ── Lightbox ───────────────────────────────────────────────────────────────────
function Lightbox({ url, onClose }) {
  // Close on Escape key
  useEffect(() => {
    const handler = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!url) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-navy/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative max-w-4xl max-h-[90vh] mx-4 bg-ledger border border-border-main shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Lightbox header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border-main">
          <p className="mono-label text-muted-fg text-xs">PACKAGING IMAGE DETAIL</p>
          <button
            onClick={onClose}
            className="mono-label text-xs text-ink-navy hover:text-[#C41E3A] transition-colors px-2 py-1 border border-border-main hover:border-[#C41E3A]/40"
          >
            ✕ CLOSE
          </button>
        </div>
        {/* Image */}
        <div className="flex-1 overflow-auto p-4 flex items-center justify-center bg-[#f5f2ec]">
          <img
            src={url}
            alt="Packaging detail"
            className="max-w-full max-h-[75vh] object-contain"
          />
        </div>
        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-border-main">
          <p className="text-[10px] text-muted-fg font-mono">
            Click outside or press Esc to close · Inspect for manufacturer, FSSAI, MRP, net weight, etc.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function Check() {
  const navigate = useNavigate();

  // ── Existing state (unchanged) ─────────────────────────────────────────────
  const [tab, setTab]               = useState("text");
  const [text, setText]             = useState("");
  const [url, setUrl]               = useState("");
  const [imageFile, setImageFile]   = useState(null);
  const [productName, setProductName] = useState("");
  const [category, setCategory]     = useState("");
  const [platform, setPlatform]     = useState("");
  const [loading, setLoading]       = useState(false);
  const [status, setStatus]         = useState("");
  const [error, setError]           = useState("");
  const fileRef = useRef(null);

  // ── New URL scanner state ──────────────────────────────────────────────────
  const [scanId, setScanId]               = useState(null);
  const [scanSteps, setScanSteps]         = useState([]);
  const [scanStatus, setScanStatus]       = useState("");
  const [scanPlatform, setScanPlatform]   = useState("");
  const [fetchBtnLabel, setFetchBtnLabel] = useState("Fetch");
  const [ocrSelectedImages, setOcrSelectedImages] = useState([]); // ← single source of truth
  const [lightboxImage, setLightboxImage] = useState(null);       // ← enlarged preview
  const pollRef = useRef(null);

  // Clear poll on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // ── Auto-detect platform from URL as user types ───────────────────────────
  const detectPlatformFromUrl = (inputUrl) => {
    if (!inputUrl) return;
    try {
      const host = new URL(inputUrl).hostname.toLowerCase();
      const PLATFORM_MAP = [
        ["amazon",    "Amazon"],
        ["flipkart",  "Flipkart"],
        ["myntra",    "Myntra"],
        ["meesho",    "Meesho"],
        ["snapdeal",  "Snapdeal"],
        ["jiomart",   "JioMart"],
        ["bigbasket", "BigBasket"],
        ["blinkit",   "Blinkit"],
        ["zepto",     "Zepto"],
        ["nykaa",     "Nykaa"],
        ["healthkart","HealthKart"],
        ["ajio",      "Ajio"],
        ["tatacliq",  "TataCLiQ"],
        ["swiggy",    "Swiggy Instamart"],
        ["purplle",   "Purplle"],
      ];
      for (const [key, label] of PLATFORM_MAP) {
        if (host.includes(key)) {
          setPlatform(label);
          return;
        }
      }
    } catch (_) {}
  };

  // ── Poll progress until done ───────────────────────────────────────────────
  const startPolling = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get(`/api/url-scan/${id}/progress`);
        setScanSteps(data.steps || []);
        setScanStatus(data.status);
        setScanPlatform(data.platform || "");

        // ── Show OCR images as soon as selection completes (before OCR finishes)
        if (data.ocr_selected_images?.length > 0) {
          setOcrSelectedImages(data.ocr_selected_images);
        }

        if (data.status === "done") {
          clearInterval(pollRef.current);
          // Fetch full result
          const res = await api.get(`/api/url-scan/${id}/result`);
          const result = res.data;

          setText(result.formatted_text);

          // ── Auto-fill metadata fields ─────────────────────────────────
          if (result.product_name) setProductName(result.product_name);
          if (result.category)     setCategory(result.category);
          if (result.platform)     setPlatform(result.platform);

          setTab("text");
          setFetchBtnLabel("Fetch Again");
          setStatus("✓ Product data extracted — review the information below, then Run Compliance Scan.");
          setLoading(false);
        } else if (data.status === "error") {
          clearInterval(pollRef.current);
          setError(data.error || "Scan failed. Please try another URL or use Paste Text.");
          setFetchBtnLabel("Fetch");
          setLoading(false);
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setError("Connection lost while polling. Please try again.");
        setFetchBtnLabel("Fetch");
        setLoading(false);
      }
    }, 1500);
  }, []);

  // ── Upgraded Fetch handler ─────────────────────────────────────────────────
  const handleFetchUrl = async () => {
    const trimmedUrl = url.trim();
    if (!trimmedUrl) return;

    // Basic URL validation before sending
    try {
      const parsed = new URL(trimmedUrl);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        setError("Please enter a valid http:// or https:// product URL.");
        return;
      }
      const host = parsed.hostname.toLowerCase();
      if (host === "localhost" || host === "127.0.0.1" || host.startsWith("192.168.") ||
          host.startsWith("10.") || host.startsWith("172.")) {
        setError("Private/local network URLs are not allowed.");
        return;
      }
    } catch (_) {
      setError("Please enter a valid product URL (e.g. https://www.amazon.in/...)");
      return;
    }

    setError("");
    setStatus("");
    setScanSteps([]);
    setScanStatus("processing");
    setScanPlatform("Detecting...");
    setOcrSelectedImages([]);   // clear previous scan's images
    setLightboxImage(null);
    setLoading(true);
    setFetchBtnLabel("⟳ Fetching...");

    try {
      const { data } = await api.post("/api/url-scan", { url: trimmedUrl });
      setScanId(data.scan_id);
      setFetchBtnLabel("⟳ Analysing...");
      startPolling(data.scan_id);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to start URL scan. Please try again.");
      setFetchBtnLabel("Fetch");
      setLoading(false);
      setScanStatus("");
    }
  };

  // ── Existing OCR handler (unchanged) ──────────────────────────────────────
  const handleOcr = async () => {
    if (!imageFile) return;
    setError(""); setLoading(true); setStatus("Running OCR…");
    const formData = new FormData();
    formData.append("file", imageFile);
    try {
      const { data } = await api.post("/api/ocr", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setText(data.extracted_text);
      setTab("text");
      setStatus(`OCR complete — ${data.word_count} words extracted (${Math.round(data.confidence * 100)}% confidence). Review then Run Scan.`);
    } catch (e) {
      setError(e.response?.data?.detail || "OCR failed.");
    } finally {
      setLoading(false);
    }
  };

  // ── Existing scan handler (unchanged) ─────────────────────────────────────
  const handleScan = async () => {
    const finalText = text.trim();
    if (finalText.length < 10) {
      setError("Please provide at least 10 characters of product label text.");
      return;
    }
    setError(""); setLoading(true); setStatus("Running compliance analysis…");
    try {
      const { data } = await api.post("/api/scan", {
        text: finalText,
        source_type: tab.toUpperCase(),
        product_name: productName || undefined,
        category: category || undefined,
        platform: platform || undefined,
      });
      navigate(`/scan/result/${data.id}`);
    } catch (e) {
      setError(e.response?.data?.detail || "Scan failed. Please try again.");
      setLoading(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex-1 px-4 py-10">
        <div className="mx-auto max-w-3xl">

          {/* Page title — unchanged */}
          <div className="mb-8">
            <p className="mono-label text-seal-gold mb-1">Legal Metrology PCR 2011</p>
            <h1 className="text-3xl font-display font-semibold text-ink-navy">
              Check a Product
            </h1>
            <p className="text-sm text-muted-fg mt-2">
              Paste label text, enter a product URL, or upload a packaging photo to run the compliance scan.
            </p>
          </div>

          {/* Metadata fields — auto-filled from URL scan */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            {[
              { label: "Product Name", value: productName, set: setProductName, placeholder: "e.g. Surf Excel Matic", autoKey: "productName" },
              { label: "Category",     value: category,    set: setCategory,    placeholder: "e.g. Detergent",       autoKey: "category" },
              { label: "Platform",     value: platform,    set: setPlatform,    placeholder: "e.g. Amazon",          autoKey: "platform" },
            ].map((f) => (
              <div key={f.label}>
                <div className="flex items-center justify-between mb-1">
                  <label className="mono-label text-muted-fg">{f.label}</label>
                  {f.value && scanStatus === "done" && (
                    <span className="text-[10px] font-mono text-[#16a34a] bg-[#16a34a]/10 px-1.5 py-0.5 rounded-sm">
                      ✓ auto-filled
                    </span>
                  )}
                  {f.label === "Platform" && f.value && scanStatus !== "done" && (
                    <span className="text-[10px] font-mono text-seal-gold bg-seal-gold/10 px-1.5 py-0.5 rounded-sm">
                      ✓ detected
                    </span>
                  )}
                </div>
                <input
                  type="text"
                  value={f.value}
                  onChange={(e) => f.set(e.target.value)}
                  placeholder={f.placeholder}
                  className={`w-full border px-3 py-2 text-sm text-ink-navy placeholder:text-muted-fg focus:outline-none font-mono transition-colors ${
                    f.value && scanStatus === "done"
                      ? "border-[#16a34a]/50 bg-[#16a34a]/5 focus:border-[#16a34a]"
                      : f.label === "Platform" && f.value
                      ? "border-seal-gold/40 bg-seal-gold/5 focus:border-seal-gold"
                      : "border-border-main bg-card-bg focus:border-ink-navy"
                  }`}
                />
              </div>
            ))}
          </div>

          {/* Tab bar — unchanged */}
          <div className="flex border-b border-border-main mb-0">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => { setTab(t.id); setError(""); }}
                className={`px-5 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                  tab === t.id
                    ? "border-ink-navy text-ink-navy"
                    : "border-transparent text-muted-fg hover:text-ink-navy"
                }`}
              >
                {t.icon} {t.label}
              </button>
            ))}
          </div>

          {/* Tab panels */}
          <div className="border border-t-0 border-border-main bg-card-bg p-6 mb-4">

            {/* TEXT TAB — unchanged */}
            {tab === "text" && (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <label className="mono-label text-muted-fg">Label / Listing Text</label>
                  <button
                    onClick={() => setText(SAMPLE_TEXT)}
                    className="text-xs text-seal-gold hover:underline mono-label"
                  >
                    Load sample →
                  </button>
                </div>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={12}
                  placeholder="Paste the product description or packaging text here…"
                  className="w-full border border-border-main bg-ledger px-4 py-3 text-sm text-ink-navy placeholder:text-muted-fg font-mono focus:outline-none focus:border-ink-navy resize-y"
                />
                <p className="text-xs text-muted-fg">{text.length} characters</p>
              </div>
            )}

            {/* URL TAB — UPGRADED */}
            {tab === "url" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <label className="mono-label text-muted-fg block">Product Page URL</label>
                  {scanPlatform && scanPlatform !== "Detecting..." && (
                    <span className="mono-label text-xs text-seal-gold">
                      Platform Detected: {scanPlatform}
                    </span>
                  )}
                </div>

                <div className="flex gap-3">
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => {
                      setUrl(e.target.value);
                      detectPlatformFromUrl(e.target.value);
                    }}
                    onKeyDown={(e) => e.key === "Enter" && !loading && url && handleFetchUrl()}
                    placeholder="https://www.flipkart.com/... or https://www.amazon.in/..."
                    className="flex-1 border border-border-main bg-ledger px-3 py-2.5 text-sm text-ink-navy placeholder:text-muted-fg font-mono focus:outline-none focus:border-ink-navy"
                  />
                  <button
                    onClick={handleFetchUrl}
                    disabled={loading || !url.trim()}
                    className={`px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-60 min-w-[110px] text-center ${
                      fetchBtnLabel.startsWith("✓")
                        ? "bg-[#16a34a] text-white"
                        : "bg-ink-navy text-ink-light hover:bg-opacity-90"
                    }`}
                  >
                    {fetchBtnLabel}
                  </button>
                </div>

                {/* Supported platforms */}
                <p className="text-xs text-muted-fg">
                  Supports: Amazon · Flipkart · Meesho · Myntra · JioMart · BigBasket · Blinkit · Nykaa · Snapdeal · and more.
                </p>

                {/* Progress panel — shown during/after scan */}
                {(scanStatus === "processing" || scanSteps.length > 0) && (
                  <ScanProgress
                    steps={scanSteps}
                    platform={scanPlatform}
                    status={scanStatus}
                  />
                )}

                {/* ── OCR Image Preview Panel ──────────────────────────────────
                    Appears as soon as images are selected (before OCR finishes).
                    Displays the EXACT same images the OCR pipeline receives.    */}
                <OcrImagePanel
                  images={ocrSelectedImages}
                  scanStatus={scanStatus}
                  onOpenLightbox={setLightboxImage}
                />

                {/* Extracted text notice (only after fetch completes) */}
                {text && scanStatus === "done" && (
                  <div className="border border-[#16a34a]/30 bg-[#16a34a]/5 px-4 py-3 text-xs text-[#16a34a]">
                    ✓ Extracted data has been loaded into the Paste Text tab.
                    Click "Paste Text" above to review and edit before scanning.
                  </div>
                )}

                {/* Instructions */}
                {!loading && !scanSteps.length && (
                  <div className="text-xs text-muted-fg space-y-1 border-t border-border-main pt-3 mt-2">
                    <p className="font-medium text-ink-navy">How it works:</p>
                    <p>1. Paste any product URL from a supported marketplace above</p>
                    <p>2. Click <strong>Fetch</strong> — the system will automatically extract product information</p>
                    <p>3. The Paste Text tab will be populated with extracted data</p>
                    <p>4. Review the text, then click <strong>Run Compliance Scan</strong></p>
                  </div>
                )}
              </div>
            )}

            {/* IMAGE TAB — unchanged */}
            {tab === "image" && (
              <div className="space-y-4">
                <label className="mono-label text-muted-fg block">Upload Label / Packaging Image</label>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="border-2 border-dashed border-border-main bg-ledger/50 p-12 text-center cursor-pointer hover:border-ink-navy transition-colors"
                >
                  {imageFile ? (
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-ink-navy">{imageFile.name}</p>
                      <p className="text-xs text-muted-fg">{(imageFile.size / 1024).toFixed(1)} KB</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <p className="text-3xl">📸</p>
                      <p className="text-sm text-muted-fg">Click to upload or drag image here</p>
                      <p className="text-xs text-muted-fg">PNG, JPG, WEBP accepted</p>
                    </div>
                  )}
                </div>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => setImageFile(e.target.files?.[0] || null)}
                />
                {imageFile && (
                  <button
                    onClick={handleOcr}
                    disabled={loading}
                    className="bg-ink-navy text-ink-light px-6 py-2.5 text-sm font-medium disabled:opacity-60 hover:bg-opacity-90 transition-colors"
                  >
                    {loading ? "Processing OCR…" : "Extract Text via OCR"}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Status / error — unchanged */}
          {status && !error && (
            <div className="mb-4 border border-[#16a34a]/30 bg-[#16a34a]/5 px-4 py-2 text-sm text-[#16a34a]">
              {status}
            </div>
          )}
          {error && (
            <div className="mb-4 border border-[#C41E3A]/30 bg-[#C41E3A]/5 px-4 py-2 text-sm text-[#C41E3A]">
              {error}
            </div>
          )}

          {/* Run scan button — unchanged */}
          <button
            onClick={handleScan}
            disabled={loading || text.trim().length < 10}
            className="w-full bg-ink-navy text-ink-light py-4 text-sm font-medium tracking-wide hover:bg-opacity-90 transition-all disabled:opacity-60 disabled:cursor-not-allowed lift"
          >
            {loading && tab !== "url" ? (
              <span className="animate-pulse">Analysing compliance…</span>
            ) : (
              "▶  Run Compliance Scan"
            )}
          </button>
        </div>
      </main>
      <SiteFooter />

      {/* Lightbox — full-screen image preview, rendered at page root to overlay everything */}
      {lightboxImage && (
        <Lightbox url={lightboxImage} onClose={() => setLightboxImage(null)} />
      )}
    </div>
  );
}
