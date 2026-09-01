import { Link } from "react-router-dom";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

const STAGES = [
  {
    step: "01",
    rule: "Rule 6(10)",
    title: "Submit the listing",
    body: "Paste a product URL, upload a packaging photo, or type the declarations shown on the label. Marketplaces must display the same declarations the pack carries.",
  },
  {
    step: "02",
    rule: "Rule 6(1)(a)\u2013(g), 6(6)",
    title: "Inspect 8 declarations",
    body: "Each declaration is checked separately and cited. A missing month of packing is recorded against Rule 6(1)(d); a missing origin against Rule 6(6).",
  },
  {
    step: "03",
    rule: "Rule 18",
    title: "Issue the report",
    body: "You get a stamped scorecard: what is declared, what is absent, and the plain-language reason each absence matters to a buyer.",
  },
];

const FIELDS = [
  { id: "F01", rule: "Rule 6(1)(e)", label: "MRP inclusive of all taxes", severity: "high" },
  { id: "F02", rule: "Rule 6(1)(b)", label: "Net quantity in standard units", severity: "high" },
  { id: "F03", rule: "Rule 6(1)(a)", label: "Manufacturer / packer / importer", severity: "high" },
  { id: "F04", rule: "Rule 6(1)(d)", label: "Month and year of manufacture", severity: "high" },
  { id: "F05", rule: "Rule 6(1)(f)", label: "Consumer care details", severity: "medium" },
  { id: "F06", rule: "Rule 6(6)", label: "Country of origin", severity: "high" },
  { id: "F07", rule: "Rule 6(1)(g)", label: "Unit sale price", severity: "medium" },
  { id: "F08", rule: "Rule 6(1)(c)", label: "Generic name of commodity", severity: "medium" },
];

const STATS = [
  { value: "8", label: "Mandatory declarations checked" },
  { value: "3", label: "Input modes — URL, image, text" },
  { value: "100%", label: "Rule-cited violations" },
  { value: "PDF", label: "Exportable compliance report" },
];

export default function Home() {
  return (
    <div className="min-h-screen">
      <SiteHeader />

      {/* ── Hero ── */}
      <section className="graph-paper border-b border-border-main">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 lg:grid-cols-[1.1fr_1fr] lg:py-24">
          <div className="animate-settle">
            <p className="rule-code">Legal Metrology (Packaged Commodities) Rules, 2011</p>
            <h1 className="mt-5 text-4xl font-bold leading-tight text-ink-navy sm:text-5xl lg:text-6xl">
              Every listing should tell the truth about what&apos;s inside.
            </h1>
            <p className="mt-5 max-w-xl text-base text-muted-fg sm:text-lg">
              Eight declarations are mandatory on every packaged commodity sold online.{" "}
              <strong className="text-ink-navy">VERIFIED</strong> checks a label or listing
              against all eight and stamps the result — declaration by declaration, rule by rule.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/check" className="btn-primary">
                Check a product
              </Link>
              <Link to="/dashboard" className="btn-outline">
                Regulator dashboard
              </Link>
            </div>
          </div>

          {/* Demo field card */}
          <div className="animate-settle border-2 border-ink-navy bg-card-bg shadow-lift" style={{ animationDelay: "220ms" }}>
            <div className="border-b border-border-main px-5 py-4 flex items-center justify-between">
              <div>
                <p className="mono-label text-muted-fg">Sample compliance check</p>
                <p className="mt-1 text-sm font-semibold text-ink-navy">Sattva Cold-Pressed Groundnut Oil</p>
              </div>
              <div className="text-right">
                <p className="font-mono text-3xl font-bold text-verified-green">88%</p>
                <p className="mono-label text-muted-fg">PARTIAL</p>
              </div>
            </div>
            <ul className="divide-y divide-border-main">
              {FIELDS.map((f) => {
                const pass = ["F01","F02","F03","F06"].includes(f.id);
                return (
                  <li key={f.id} className="flex items-center justify-between px-5 py-3 gap-3">
                    <div className="min-w-0">
                      <p className="rule-code">{f.rule}</p>
                      <p className="text-xs text-graphite mt-0.5 truncate">{f.label}</p>
                    </div>
                    <span className={`shrink-0 font-mono text-xs font-bold px-2 py-0.5 border ${
                      pass
                        ? "border-green-300 bg-green-50 text-verified-green"
                        : "border-red-300 bg-red-50 text-violation-red"
                    }`}>
                      {pass ? "✓ PASS" : "✗ FAIL"}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="mx-auto max-w-6xl px-5 py-20">
        <p className="rule-code text-seal-gold">Inspection procedure</p>
        <h2 className="mt-3 text-3xl font-bold text-ink-navy sm:text-4xl">Three stages, one record</h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {STAGES.map((s) => (
            <article key={s.step} className="lift h-full border border-border-main bg-card-bg p-6">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-3xl font-semibold text-seal-gold">{s.step}</span>
                <span className="rule-code border border-seal-gold/40 px-2 py-0.5 text-seal-gold">{s.rule}</span>
              </div>
              <div className="seal-divider my-4" />
              <h3 className="text-xl font-semibold text-ink-navy">{s.title}</h3>
              <p className="mt-2 text-sm text-muted-fg">{s.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ── Stats strip ── */}
      <section className="border-y border-border-main bg-ink-navy text-ink-light">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label}>
              <p className="font-mono text-4xl font-bold text-ink-light">{s.value}</p>
              <p className="mono-label mt-2 text-ink-light/70">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Two audiences ── */}
      <section className="mx-auto max-w-6xl px-5 py-20">
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="lift flex h-full flex-col border border-seal-gold/50 bg-card-bg p-8">
            <p className="rule-code text-seal-gold">For consumers</p>
            <h2 className="mt-3 text-2xl font-bold text-ink-navy sm:text-3xl">Know before you buy</h2>
            <p className="mt-3 text-sm text-muted-fg">
              Check one listing in about ten seconds. See which declarations are absent and what that
              means for you — no jargon, no score without a reason.
            </p>
            <ul className="mt-5 space-y-2 text-sm text-graphite">
              <li>✓ Per-field pass or fail with the rule cited</li>
              <li>✓ Plain-language explanation of every violation</li>
              <li>✓ Shareable report reference for complaints</li>
            </ul>
            <Link to="/check" className="mono-label mt-auto pt-6 text-ink-navy underline decoration-seal-gold">
              Check a listing →
            </Link>
          </div>
          <div className="lift flex h-full flex-col bg-ink-navy p-8 text-ink-light">
            <p className="rule-code text-seal-gold">For regulators</p>
            <h2 className="mt-3 text-2xl font-bold sm:text-3xl">Monitor compliance at scale</h2>
            <p className="mt-3 text-sm text-ink-light/75">
              Aggregate compliance by platform and category, sort violations by severity, and track
              whether compliance improves month over month.
            </p>
            <ul className="mt-5 space-y-2 text-sm text-ink-light/90">
              <li>✓ Compliance rate by category and platform</li>
              <li>✓ Sortable violations register with listing IDs</li>
              <li>✓ PDF/CSV export for enforcement records</li>
            </ul>
            <Link to="/dashboard" className="mono-label mt-auto pt-6 text-seal-gold underline">
              Open the dashboard →
            </Link>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
