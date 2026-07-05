/** @type {import('next').NextConfig} */

// The Python API backend (ml/runtime/dashboard.py). Override with BACKEND_URL.
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8080";

const nextConfig = {
  // Proxy every /api/* call to the Python backend so the browser stays
  // same-origin (no CORS) in both dev and prod.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;
