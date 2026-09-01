/**
 * pages/Check.jsx — Multi-tab product compliance scanner (Text | URL | Image).
 */
import { useState, useRef } from "react";
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

export default function Check() {
  const navigate = useNavigate();
  const [tab, setTab]         = useState("text");
  const [text, setText]       = useState("");
  const [url, setUrl]         = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [productName, setProductName] = useState("");
  const [category, setCategory]       = useState("");
  const [platform, setPlatform]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [status, setStatus]     = useState(""); // status message
  const [error, setError]       = useState("");
  const fileRef = useRef(null);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleFetchUrl = async () => {
    if (!url.trim()) return;
    setError(""); setLoading(true); setStatus("Fetching product page…");
    try {
      const { data } = await api.post("/api/fetch-url", { url });
      setText(data.extracted_text);
      if (!productName) setProductName(data.product_name);
      if (!platform)   setPlatform(data.marketplace);
      setTab("text");
      setStatus("Text extracted — review then Run Scan.");
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to fetch URL.");
    } finally {
      setLoading(false);
    }
  };

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
          {/* Page title */}
          <div className="mb-8">
            <p className="mono-label text-seal-gold mb-1">Legal Metrology PCR 2011</p>
            <h1 className="text-3xl font-display font-semibold text-ink-navy">
              Check a Product
            </h1>
            <p className="text-sm text-muted-fg mt-2">
              Paste label text, enter a product URL, or upload a packaging photo to run the compliance scan.
            </p>
          </div>

          {/* Optional metadata */}
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

          {/* Tab bar */}
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
            {/* TEXT TAB */}
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

            {/* URL TAB */}
            {tab === "url" && (
              <div className="space-y-4">
                <label className="mono-label text-muted-fg block">Product Page URL</label>
                <div className="flex gap-3">
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.amazon.in/dp/..."
                    className="flex-1 border border-border-main bg-ledger px-3 py-2.5 text-sm text-ink-navy placeholder:text-muted-fg font-mono focus:outline-none focus:border-ink-navy"
                  />
                  <button
                    onClick={handleFetchUrl}
                    disabled={loading || !url}
                    className="bg-ink-navy text-ink-light px-5 py-2.5 text-sm font-medium disabled:opacity-60 hover:bg-opacity-90 transition-colors"
                  >
                    Fetch
                  </button>
                </div>
                <p className="text-xs text-muted-fg">
                  Supports: Amazon.in, Flipkart, Meesho, Myntra, BigBasket, and most product pages.
                </p>
                {text && (
                  <div className="border border-border-main bg-ledger p-3 text-xs text-muted-fg font-mono max-h-48 overflow-auto">
                    {text.slice(0, 600)}…
                  </div>
                )}
              </div>
            )}

            {/* IMAGE TAB */}
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

          {/* Status / error */}
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

          {/* Run scan button */}
          <button
            onClick={handleScan}
            disabled={loading || text.trim().length < 10}
            className="w-full bg-ink-navy text-ink-light py-4 text-sm font-medium tracking-wide hover:bg-opacity-90 transition-all disabled:opacity-60 disabled:cursor-not-allowed lift"
          >
            {loading ? (
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
