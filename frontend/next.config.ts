import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  // ── API Proxy: rewrite /api/* → FastAPI data gateway ──────────────────────
  // Production: set NEXT_PUBLIC_GATEWAY_URL to deployed api_server URL.
  // Local dev: http://localhost:8001
  async rewrites() {
    const gateway =
      process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8001";
    return [
      {
        source:      "/api/:path*",
        destination: `${gateway}/api/:path*`,
      },
    ];
  },

  images: {
    remotePatterns: [],
  },

  compiler: {
    removeConsole:
      process.env.NODE_ENV === "production"
        ? { exclude: ["error", "warn"] }
        : false,
  },
};

// ── Sentry Next.js Build Plugin ───────────────────────────────────────────────
// Uploads source maps on every production build; sets up Vercel Cron monitors.
// Requires: SENTRY_AUTH_TOKEN + SENTRY_ORG + SENTRY_PROJECT in environment.
export default withSentryConfig(nextConfig, {
  org:     process.env.SENTRY_ORG     ?? "your-org-slug",
  project: process.env.SENTRY_PROJECT ?? "aegis-v2-portfolio",

  silent: true,
  widenClientFileUpload: true,

  // Tunnel Sentry events through Next.js to bypass ad-blockers
  tunnelRoute: "/monitoring-tunnel",

  disableLogger: true,
  automaticVercelMonitors: true,
});
