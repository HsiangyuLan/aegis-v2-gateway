/**
 * Sentry Client Instrumentation — Production Configuration
 * ==========================================================
 * Loaded by @sentry/nextjs automatically when instrumentation.client.ts
 * is present alongside instrumentation.ts.
 *
 * ScrollyCanvas Replay Noise Suppression
 * ────────────────────────────────────────
 * ScrollyCanvas draws 120 WebP frames at up to 60fps via rAF.
 * Without filtering, Sentry Replay would serialise every canvas paint
 * mutation → 30–120 events/sec → flood the Replay event buffer → obscure
 * real user interaction events (clicks, drawer opens).
 *
 * Solution (Sentry v10 API):
 *   block: ['canvas[aria-label="Hero scroll sequence"]']
 *     → Sentry replaces the canvas with a solid placeholder block in the
 *       recording. Zero canvas serialisation. Scroll position, clicks,
 *       and drawer interactions are still fully captured.
 *
 *   beforeAddRecordingEvent (inside replayIntegration):
 *     → Drop IncrementalSnapshot events whose source is CanvasMutation
 *       (type 3, source 9) as a belt-and-suspenders filter.
 *
 *   ignoreClass: 'scrolly-canvas-container'
 *     → The sticky wrapper div emits scroll events at 60fps; we only
 *       want the final scroll position, not every intermediate update.
 */

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "development",

  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,

  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,

  integrations: [
    Sentry.replayIntegration({
      // ── GDPR ────────────────────────────────────────────────────────────
      maskAllText: true,
      blockAllMedia: false,

      // ── §ScrollyCanvas noise suppression (Sentry v10 API) ───────────────
      // block: array of CSS selectors whose elements are replaced with a
      // solid placeholder — no canvas pixel data is ever serialised.
      block: ['canvas[aria-label="Hero scroll sequence"]'],

      // ignore: elements whose DOM mutations are not recorded.
      // The sticky container fires scroll events at ~60fps; we capture
      // only the final resting position via normal scroll tracking.
      ignore: ['.scrolly-canvas-container'],

      // ── Belt-and-suspenders: filter CanvasMutation events ─────────────
      // Drops IncrementalSnapshot (type 3) + CanvasMutation source (9)
      // at the event stream level to guarantee zero canvas noise.
      beforeAddRecordingEvent(event) {
        if (
          event &&
          typeof event === "object" &&
          "type" in event &&
          (event as { type: number }).type === 3 &&
          "data" in event &&
          (event as { data?: { source?: number } }).data?.source === 9
        ) {
          return null;
        }
        return event;
      },

      networkDetailAllowUrls: [/\/api\/v1\//, /posthog\.com/],
    }),

    Sentry.browserTracingIntegration({
      instrumentNavigation: true,
      instrumentPageLoad: true,
    }),
  ],

  initialScope: {
    tags: {
      component: "portfolio-client",
      version:   "2.5.0",
      build:     process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA ?? "local",
    },
  },

  ignoreErrors: [
    "ResizeObserver loop limit exceeded",
    "Non-Error promise rejection captured",
    "The source image cannot be decoded",
  ],

  beforeSend(event) {
    if (process.env.NODE_ENV === "development") return null;
    return event;
  },
});
