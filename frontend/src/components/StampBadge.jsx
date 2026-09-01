/**
 * components/StampBadge.jsx — Animated compliance verdict stamp (PASS / FAIL / PARTIAL).
 */
export default function StampBadge({ status, score }) {
  const cfg = {
    PASS:    { color: "text-[#16a34a]",  border: "border-[#16a34a]",  bg: "bg-[#16a34a]/5",  label: "COMPLIANT"    },
    FAIL:    { color: "text-[#C41E3A]",  border: "border-[#C41E3A]",  bg: "bg-[#C41E3A]/5",  label: "NON-COMPLIANT" },
    PARTIAL: { color: "text-amber-700",   border: "border-amber-600",   bg: "bg-amber-50",      label: "PARTIAL"      },
  };
  const c = cfg[status] ?? cfg.FAIL;

  return (
    <div
      className={`stamp-impact inline-flex flex-col items-center justify-center border-4 ${c.border} ${c.bg} px-8 py-5 rotate-[-3.5deg]`}
    >
      <span className={`font-mono text-2xl font-black tracking-widest uppercase ${c.color}`}>
        {c.label}
      </span>
      <span className={`mono-label mt-1 ${c.color} opacity-70`}>
        Score: {score}/100
      </span>
    </div>
  );
}
