/**
 * Next.js Instrumentation Hook
 * =============================
 * Loaded by Next.js automatically when `experimental.instrumentationHook` is
 * enabled in next.config.ts (or by default in Next.js 15+).
 *
 * Sentry is initialised here — once on the server, once on the client edge —
 * so there is no double-initialisation risk from layout.tsx imports.
 *
 * Required environment variables (.env.local):
 *   NEXT_PUBLIC_SENTRY_DSN=https://xxx@sentry.io/...
 *   SENTRY_AUTH_TOKEN=...   (for source-map upload in CI)
 *   SENTRY_ORG=your-org
 *   SENTRY_PROJECT=aegis-v2
 */

export async function register(): Promise<void> {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

  if (process.env.NEXT_RUNTIME === "nodejs") {
    // ── Server-side Sentry init ───────────────────────────────────────────
    const { init, rewriteFramesIntegration } = await import("@sentry/nextjs");

    init({
      dsn,
      environment: process.env.NODE_ENV ?? "development",
      tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
      integrations: [
        rewriteFramesIntegration(),
      ],
      // Tag every event with the Aegis component it came from
      initialScope: {
        tags: {
          component: "aegis-v2-server",
          version: "2.5.0",
        },
      },
      // Do not capture localhost noise in development
      beforeSend(event) {
        if (process.env.NODE_ENV === "development") return null;
        return event;
      },
    });
  }

  if (process.env.NEXT_RUNTIME === "edge") {
    // ── Edge runtime Sentry init ──────────────────────────────────────────
    const { init } = await import("@sentry/nextjs");

    init({
      dsn,
      environment: process.env.NODE_ENV ?? "development",
      tracesSampleRate: 0.05,   // edge has higher volume; sample aggressively
      initialScope: {
        tags: {
          component: "aegis-v2-edge",
          version: "2.5.0",
        },
      },
    });
  }
}

export const onRequestError = async (
  err: unknown,
  request: { path: string; method: string },
  context: { routeType: string }
): Promise<void> => {
  /**
   * Called by Next.js on every server-side request error.
   * Forwards to Sentry with request context attached.
   */
  const { captureException, withScope } = await import("@sentry/nextjs");

  withScope((scope) => {
    scope.setTag("route_type", context.routeType);
    scope.setExtra("request_path", request.path);
    scope.setExtra("request_method", request.method);
    captureException(err);
  });
};
