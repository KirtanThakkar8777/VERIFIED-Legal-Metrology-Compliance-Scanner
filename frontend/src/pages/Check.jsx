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
  const [scanId, setScanId]         = useState(null);
  const [scanSteps, setScanSteps]   = useState([]);
  const [scanStatus, setScanStatus] = useState("");
  const [scanPlatform, setScanPlatform] = useState("");
  const [fetchBtnLabel, setFetchBtnLabel] = useState("Fetch");
  const pollRef = useRef(null);

  // Clear poll on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // ── Poll progress until done ───────────────────────────────────────────────
  const startPolling = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get(`/api/url-scan/${id}/progress`);
        setScanSteps(data.steps || []);
        setScanStatus(data.status);
        setScanPlatform(data.platform || "");

        if (data.status === "done") {
          clearInterval(pollRef.current);
          // Fetch result
          const res = await api.get(`/api/url-scan/${id}/result`);
          const result = res.data;

          setText(result.formatted_text);
          if (!productName) setProductName(result.product_name || "");
          if (!platform)   setPlatform(result.platform || "");

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
  }, [productName, platform]);

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

          {/* Optional metadata — unchanged */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            {[
              { label: "Product Name", value: productName, set: setProductName, placeholder: "e.g. Surf Excel Matic" },
              { label: "Category",     value: category,    set: setCategory,    placeholder: "e.g. Detergent" },
              { label: "Platform",     value: platform,    set: setPlatform,    placeholder: "e.g. Amazon" },
            ].map((f) => (
              <div key={f.label}>
                <label className="mono-label text-muted-fg mb-1 block">{f.label}</label>
                <input
                  type="text"
                  value={f.value}
                  onChange={(e) => f.set(e.target.value)}
                  placeholder={f.placeholder}
                  className="w-full border border-border-main bg-card-bg px-3 py-2 text-sm text-ink-navy placeholder:text-muted-fg focus:outline-none focus:border-ink-navy font-mono"
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
                    onChange={(e) => setUrl(e.target.value)}
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

                {/* Extracted text preview (only after fetch, before tab switch) */}
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
    </div>
  );
}
