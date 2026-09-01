/**
 * components/FieldCard.jsx — Expandable compliance field result card.
 */
import { useState } from "react";
import StatusBadge from "./StatusBadge";

export default function FieldCard({ field, index }) {
  const [open, setOpen] = useState(false);

  return (
    <div
      className="border border-border-main bg-card-bg animate-settle"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {/* Header row — always visible */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-ink-navy/5 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="mono-label text-muted-fg shrink-0">{field.field_id}</span>
          <span className="text-sm font-medium text-ink-navy truncate">{field.field_label}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="mono-label text-muted-fg hidden sm:block">{field.legal_reference}</span>
          <StatusBadge status={field.status} />
          <span className="text-muted-fg text-xs">{open ? "▲" : "▼"}</span>
        </div>
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="border-t border-border-main px-4 py-3 bg-ledger/40 space-y-2">
          <div className="mono-label text-muted-fg mb-1">{field.legal_reference}</div>

          {field.detected_value && (
            <div className="flex gap-2 text-sm">
              <span className="text-muted-fg shrink-0">Detected:</span>
              <span className="font-mono text-ink-navy">{field.detected_value}</span>
            </div>
          )}
          {field.normalized_value && field.normalized_value !== field.detected_value && (
            <div className="flex gap-2 text-sm">
              <span className="text-muted-fg shrink-0">Normalised:</span>
              <span className="font-mono text-seal-gold">{field.normalized_value}</span>
            </div>
          )}
          {field.evidence && (
            <div className="text-xs text-muted-fg bg-ledger p-2 border border-border-main font-mono break-all">
              {field.evidence}
            </div>
          )}
          {field.reason && (
            <div className="text-sm text-[#C41E3A]">⚠ {field.reason}</div>
          )}
          {field.confidence !== undefined && (
            <div className="text-xs text-muted-fg">
              Confidence: {Math.round(field.confidence * 100)}%
            </div>
          )}
        </div>
      )}
    </div>
  );
}
