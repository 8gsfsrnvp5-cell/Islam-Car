import path from "node:path";
import type { NextConfig } from "next";

// Сервер API. Браузер обращается к /api/* на этом же домене, Next.js проксирует запрос.
const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const ROOT = path.join(__dirname, "../..");

const nextConfig: NextConfig = {
  transpilePackages: ["@islamic-car/shared"],
  turbopack: { root: ROOT },
  outputFileTracingRoot: ROOT,
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "same-origin" },
      ],
    }];
  },
};

export default nextConfig;
