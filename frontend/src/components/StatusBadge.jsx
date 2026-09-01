/**
 * components/StatusBadge.jsx — PASS / FAIL / REVIEW / N/A badge chip.
 */
export default function StatusBadge({ status }) {
  const cfg = {
    PASS:   { bg: "bg-[#16a34a]/10",   text: "text-[#16a34a]",  border: "border-[#16a34a]/30",  label: "✓ PASS"   },
    FAIL:   { bg: "bg-[#C41E3A]/10",   text: "text-[#C41E3A]",  border: "border-[#C41E3A]/30",  label: "✗ FAIL"   },
    REVIEW: { bg: "bg-amber-500/10",    text: "text-amber-700",   border: "border-amber-400/40",  label: "⚠ REVIEW" },
    "N/A":  { bg: "bg-gray-100",        text: "text-gray-500",    border: "border-gray-300",       label: "— N/A"    },
  };
  const c = cfg[status] ?? cfg["N/A"];
  return (
    <span
      className={`mono-label inline-block border px-2 py-0.5 text-[10px] ${c.bg} ${c.text} ${c.border}`}
    >
      {c.label}
    </span>
  );
}
