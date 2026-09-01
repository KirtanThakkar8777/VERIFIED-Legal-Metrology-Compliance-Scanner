import { Link } from "react-router-dom";

export default function SiteFooter() {
  return (
    <footer className="border-t border-border-main bg-[#ede9df]">
      <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 sm:grid-cols-3">
        <div>
          <p className="mono-label text-muted-fg">Statutory basis</p>
          <ul className="mt-3 space-y-1.5 text-sm text-muted-fg">
            <li>Legal Metrology Act, 2009</li>
            <li>Packaged Commodities Rules, 2011 — Rule 6, Rule 18</li>
            <li>E-commerce declarations — Rule 6(10)</li>
          </ul>
        </div>
        <div>
          <p className="mono-label text-muted-fg">Context</p>
          <p className="mt-3 text-sm text-muted-fg">
            Reference tool built against publicly published rules of the Department of Consumer
            Affairs, Ministry of Consumer Affairs, Food &amp; Public Distribution. Not an official
            government service.
          </p>
        </div>
        <div>
          <p className="mono-label text-muted-fg">Contact</p>
          <ul className="mt-3 space-y-1.5 font-mono text-sm text-muted-fg">
            <li>report@verified.example</li>
            <li>+91 1800 000 000</li>
          </ul>
          <Link to="/rules" className="mono-label mt-4 inline-block text-ink-navy underline decoration-seal-gold">
            Read the 8 declarations
          </Link>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="border-t border-border-main">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-ink-navy text-ink-light flex items-center justify-center font-mono text-xs font-bold">
              VF
            </div>
            <p className="mono-label text-muted-fg">Compliance register</p>
          </div>
          <p className="mono-label text-muted-fg">Doc. ref VF/LM/2026-01</p>
        </div>
      </div>
    </footer>
  );
}
