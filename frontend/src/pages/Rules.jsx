/**
 * pages/Rules.jsx — Legal Metrology rules reference page.
 */
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

const RULES = [
  {
    id: "F01",
    ref: "Rule 6(1)(a)",
    label: "Manufacturer / Importer Name & Address",
    description:
      "Every pre-packaged commodity shall bear the name and complete address of the manufacturer, packer, or importer.",
    example: "Manufactured by: Hindustan Unilever Ltd., 165/166 Backbay Reclamation, Mumbai 400020",
    severity: "high",
  },
  {
    id: "F02",
    ref: "Rule 6(1)(b)",
    label: "Net Quantity",
    description:
      "The net quantity in terms of standard unit of weight, volume, measure, or number must be declared.",
    example: "Net Weight: 500g | Net Volume: 250 ml | Net Quantity: 10 tablets",
    severity: "high",
  },
  {
    id: "F03",
    ref: "Rule 6(1)(c)",
    label: "Month & Year of Manufacture",
    description:
      "Month and year of manufacture or packing. For imported goods, the month and year of import.",
    example: "Mfg. Date: Jan 2025 | Packed: 03/2025",
    severity: "high",
  },
  {
    id: "F04",
    ref: "Rule 6(1)(d)",
    label: "Best Before / Expiry Date",
    description:
      "Best before, use by, or expiry date must be declared for perishable and food commodities.",
    example: "Best Before: Dec 2025 | Use By: 12/2025 | Shelf Life: 24 months",
    severity: "high",
  },
  {
    id: "F05",
    ref: "Rule 6(1)(e)",
    label: "Maximum Retail Price (MRP)",
    description:
      "Maximum Retail Price inclusive of all taxes must be declared with ₹ or Rs. symbol.",
    example: "MRP: ₹85.00 (Incl. of all taxes) | MRP Rs. 120",
    severity: "high",
  },
  {
    id: "F06",
    ref: "Rule 6(1)(f)",
    label: "Consumer Care Contact",
    description:
      "Name and address of the person who can be contacted in case of consumer complaint, including phone/email.",
    example: "Consumer Care: 1800 425 1000 | care@brand.com",
    severity: "medium",
  },
  {
    id: "F07",
    ref: "Rule 6(1)(g)",
    label: "Country of Origin",
    description:
      "Country of origin is mandatory post the 2017 amendment. Must appear as 'Made in India' or equivalent.",
    example: "Country of Origin: India | Made in India",
    severity: "high",
  },
  {
    id: "F08",
    ref: "FSS Act 2006",
    label: "FSSAI Licence Number",
    description:
      "14-digit FSSAI licence number is mandatory for all food products sold in India.",
    example: "FSSAI Lic No.: 10013022002115",
    severity: "medium",
  },
];

const severityColor = (s) =>
  s === "high"
    ? "text-[#C41E3A] border-[#C41E3A]/30 bg-[#C41E3A]/5"
    : "text-amber-700 border-amber-400/30 bg-amber-50";

export default function Rules() {
  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex-1 px-4 py-10">
        <div className="mx-auto max-w-3xl">
          <div className="mb-8">
            <p className="mono-label text-seal-gold mb-1">Legal Reference</p>
            <h1 className="text-3xl font-display font-semibold text-ink-navy">
              PCR 2011 — Mandatory Fields
            </h1>
            <p className="text-sm text-muted-fg mt-2">
              Legal Metrology (Packaged Commodities) Rules 2011 require the following 8 disclosures
              on every pre-packaged commodity sold in India.
            </p>
          </div>

          <div className="space-y-4">
            {RULES.map((rule) => (
              <div key={rule.id} className="border border-border-main bg-card-bg p-5">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div className="flex items-center gap-3">
                    <span className="mono-label text-muted-fg">{rule.id}</span>
                    <h2 className="font-display font-semibold text-ink-navy">{rule.label}</h2>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`mono-label border px-2 py-0.5 text-[10px] ${severityColor(rule.severity)}`}>
                      {rule.severity}
                    </span>
                    <span className="mono-label text-seal-gold">{rule.ref}</span>
                  </div>
                </div>
                <p className="text-sm text-muted-fg mb-3">{rule.description}</p>
                <div className="bg-ledger border border-border-main px-4 py-2.5">
                  <p className="mono-label text-muted-fg text-[9px] mb-1">EXAMPLE</p>
                  <p className="text-xs font-mono text-ink-navy">{rule.example}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-8 border border-seal-gold/30 bg-seal-gold/5 p-5 text-sm text-ink-navy">
            <p className="font-display font-semibold mb-2">Legal Basis</p>
            <ul className="text-muted-fg space-y-1 text-xs font-mono">
              <li>• Legal Metrology (Packaged Commodities) Rules, 2011</li>
              <li>• Legal Metrology Act, 2009</li>
              <li>• Amendment Gazette: GSR 824(E) dated 08 Sep 2017 (Country of Origin)</li>
              <li>• Food Safety and Standards Act, 2006 (FSSAI)</li>
            </ul>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
