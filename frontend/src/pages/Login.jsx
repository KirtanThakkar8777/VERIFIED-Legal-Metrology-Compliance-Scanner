/**
 * pages/Login.jsx — Regulator login page.
 */
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import api from "../api/client";
import SiteHeader from "../components/SiteHeader";
import SiteFooter from "../components/SiteFooter";

export default function Login() {
  const navigate = useNavigate();
  const [form, setForm]     = useState({ email: "", password: "" });
  const [error, setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const handleChange = (e) =>
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/api/auth/login", form);
      localStorage.setItem("verified_token", data.access_token);
      localStorage.setItem("verified_user", JSON.stringify(data.user));
      navigate("/dashboard");
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-ledger">
      <SiteHeader />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <div className="w-full max-w-md">
          {/* Title */}
          <div className="mb-8 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 bg-ink-navy text-ink-light font-mono font-bold text-lg mb-4">
              VF
            </div>
            <h1 className="text-2xl font-display font-semibold text-ink-navy">Regulator Login</h1>
            <p className="mono-label text-muted-fg mt-1">Legal Metrology Enforcement Portal</p>
          </div>

          {/* Card */}
          <div className="border border-border-main bg-card-bg p-8">
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="mono-label text-muted-fg mb-1.5 block">Email address</label>
                <input
                  type="email"
                  name="email"
                  required
                  value={form.email}
                  onChange={handleChange}
                  placeholder="officer@lm.gov.in"
                  className="w-full border border-border-main bg-ledger px-3 py-2.5 text-sm text-ink-navy placeholder:text-muted-fg focus:outline-none focus:border-ink-navy transition-colors font-mono"
                />
              </div>
              <div>
                <label className="mono-label text-muted-fg mb-1.5 block">Password</label>
                <input
                  type="password"
                  name="password"
                  required
                  value={form.password}
                  onChange={handleChange}
                  placeholder="••••••••"
                  className="w-full border border-border-main bg-ledger px-3 py-2.5 text-sm text-ink-navy placeholder:text-muted-fg focus:outline-none focus:border-ink-navy transition-colors font-mono"
                />
              </div>

              {error && (
                <div className="border border-[#C41E3A]/30 bg-[#C41E3A]/5 px-4 py-2.5 text-sm text-[#C41E3A]">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-ink-navy text-ink-light py-3 text-sm font-medium tracking-wide hover:bg-opacity-90 transition-all disabled:opacity-60 disabled:cursor-not-allowed lift"
              >
                {loading ? "Verifying..." : "Login to Dashboard"}
              </button>
            </form>

            <div className="seal-divider my-6" />

            <p className="text-center text-xs text-muted-fg">
              Don't have an account?{" "}
              <span className="text-seal-gold">Contact your administrator</span>
              {" · "}
              <Link to="/" className="hover:text-ink-navy transition-colors">← Home</Link>
            </p>
          </div>

          {/* Default credentials hint */}
          <div className="mt-4 border border-seal-gold/40 bg-seal-gold/5 px-4 py-3 text-xs space-y-1">
            <p className="mono-label text-seal-gold mb-1.5">DEFAULT CREDENTIALS</p>
            <div className="flex gap-2">
              <span className="text-muted-fg w-16 shrink-0">Email:</span>
              <code
                className="font-mono text-ink-navy cursor-pointer hover:text-seal-gold"
                onClick={() => setForm(f => ({ ...f, email: "admin@verified.in" }))}
                title="Click to fill"
              >
                admin@verified.in
              </code>
            </div>
            <div className="flex gap-2">
              <span className="text-muted-fg w-16 shrink-0">Password:</span>
              <code
                className="font-mono text-ink-navy cursor-pointer hover:text-seal-gold"
                onClick={() => setForm(f => ({ ...f, password: "Admin@123" }))}
                title="Click to fill"
              >
                Admin@123
              </code>
            </div>
            <p className="text-muted-fg mt-1 pt-1 border-t border-border-main">
              Click email/password above to auto-fill, or use{" "}
              <code className="bg-ledger px-1">POST /api/auth/register</code> to create new accounts.
            </p>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
