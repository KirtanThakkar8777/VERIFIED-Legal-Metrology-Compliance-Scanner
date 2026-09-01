import { Link, useLocation, useNavigate } from "react-router-dom";

export default function SiteHeader() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const isLoggedIn = Boolean(localStorage.getItem("verified_token"));

  const NAV = [
    { to: "/check",         label: "Check a product" },
    { to: "/font-analysis", label: "Font Analysis" },
    { to: "/rules",         label: "How it works" },
    ...(isLoggedIn
      ? [{ to: "/dashboard", label: "Dashboard" }]
      : [{ to: "/login",    label: "Regulator login" }]
    ),
  ];

  const handleLogout = () => {
    localStorage.removeItem("verified_token");
    localStorage.removeItem("verified_user");
    navigate("/login");
  };

  return (
    <header className="sticky top-0 z-40 border-b border-border-main bg-ledger/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3">
        {/* Logo / wordmark */}
        <Link to="/" className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 bg-ink-navy text-ink-light font-mono font-bold text-sm">
            VF
          </div>
          <span className="hidden sm:block font-display font-semibold text-ink-navy tracking-tight">
            VERIFIED
          </span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-6 md:flex">
          {NAV.map((n) => (
            <Link
              key={n.to}
              to={n.to}
              className={`mono-label transition-colors hover:text-ink-navy ${
                pathname === n.to ? "text-ink-navy" : "text-muted-fg"
              }`}
            >
              {n.label}
            </Link>
          ))}
          {isLoggedIn && (
            <button
              onClick={handleLogout}
              className="mono-label text-muted-fg hover:text-ink-navy transition-colors"
            >
              Logout
            </button>
          )}
        </nav>

        {/* Mobile CTA */}
        <Link
          to="/check"
          className="lift bg-ink-navy px-3.5 py-2 text-xs font-medium text-ink-light md:hidden"
        >
          Check
        </Link>
      </div>
    </header>
  );
}
