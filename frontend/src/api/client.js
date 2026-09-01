/**
 * api/client.js — Axios instance with JWT auth interceptor.
 */
import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000",
  headers: { "Content-Type": "application/json" },
});

// Attach token to every request if present
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("verified_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Intercept 401 → clear token and redirect to login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("verified_token");
      localStorage.removeItem("verified_user");
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

export default api;
