/**
 * App.jsx — Router setup with protected dashboard route.
 */
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Home         from "./pages/Home";
import Login        from "./pages/Login";
import Check        from "./pages/Check";
import Result       from "./pages/Result";
import Dashboard    from "./pages/Dashboard";
import Rules        from "./pages/Rules";
import FontAnalysis from "./pages/FontAnalysis";

/** Redirect unauthenticated users to /login. */
function ProtectedRoute({ children }) {
  const token = localStorage.getItem("verified_token");
  return token ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/"              element={<Home />} />
        <Route path="/login"         element={<Login />} />
        <Route path="/check"         element={<Check />} />
        <Route path="/scan/result/:id" element={<Result />} />
        <Route path="/rules"           element={<Rules />} />
        <Route path="/font-analysis"   element={<FontAnalysis />} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
