@AGENTS.md

# Aegis V2.5 — Frontend Engineering Notes + Production Readiness Report

---

## PRODUCTION READINESS REPORT
**Status: CLEARED FOR DEPLOYMENT**
TypeScript: 0 errors · spec.md: all §1–§4 conditions met · Sentry: configured

### Deployment Checklist

| Item | Requirement | Status |
|---|---|---|
| TypeScript | 0 `tsc --noEmit` errors | ✓ PASS |
| spec.md §1 Colors | Hard-coded #FF0000 / #FFFFFF / #000000, zero fallbacks | ✓ PASS |
| spec.md §1 Font | Futura Heavy @font-face, production sans-serif fallback removed | ✓ PASS |
| spec.md §2 Layout | 1440px container, 180px nav text-align:right, 5-col grid | ✓ PASS |
| spec.md §3 Lookbook | 15vw / 1:5 / flex nowrap / 0px gap | ✓ PASS |
| spec.md §4.1 Image | object-fit:cover + bg:#F4F4F4 on load failure | ✓ PASS |
| spec.md §4.2 Grid | <1024→3col / <768→2col @media degradation | ✓ PASS |
| spec.md §4.3 Null | Empty 1px #000000 box on null/undefined imageUrl | ✓ PASS |
| Sentry Replay | Canvas noise suppressed (block + ignore + beforeAddRecordingEvent) | ✓ PASS |
| Sentry Source Maps | withSentryConfig + tunnelRoute | ✓ PASS |
| Env Vars | .env.local.example: Clerk + Sentry + PostHog + Vercel + Gateway | ✓ PASS |
| API Proxy | next.config.ts rewrites /api/* → NEXT_PUBLIC_GATEWAY_URL | ✓ PASS |
| Fonts on disk | `public/fonts/FuturaHeavy.woff2` required before deploy | ⚠ MANUAL |

### Pre-Deploy Actions Required
```bash
# 1. Place licensed Futura Heavy font files:
cp /path/to/FuturaHeavy.woff2         frontend/public/fonts/FuturaHeavy.woff2
cp /path/to/FuturaHeavyItalic.woff2   frontend/public/fonts/FuturaHeavyItalic.woff2

# 2. Create .env.local from example:
cp frontend/.env.local.example frontend/.env.local
# Fill in: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY,
#          NEXT_PUBLIC_SENTRY_DSN, SENTRY_AUTH_TOKEN,
#          NEXT_PUBLIC_POSTHOG_KEY, NEXT_PUBLIC_GATEWAY_URL

# 3. Verify WebP sequence is present:
ls -lh frontend/public/sequence/hero_webp | head -3
# Expected: 120 files, ~3.65 MB total

# 4. Final type check:
cd frontend && npx tsc --noEmit
```

### Vercel Deployment
```bash
# Push to GitHub → Vercel auto-detects Next.js
# Set env vars in Vercel Dashboard → Settings → Environment Variables
# Required on Vercel:
#   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY  (production key, NOT pk_test_)
#   CLERK_SECRET_KEY
#   NEXT_PUBLIC_SENTRY_DSN
#   SENTRY_AUTH_TOKEN
#   SENTRY_ORG
#   SENTRY_PROJECT
#   NEXT_PUBLIC_POSTHOG_KEY
#   NEXT_PUBLIC_POSTHOG_HOST
#   NEXT_PUBLIC_GATEWAY_URL            (deployed FastAPI URL)
```

---

## Infrastructure

### ffmpeg (v8.1 via Homebrew)
The standard Homebrew `ffmpeg` bottle ships **without `--enable-libwebp`** (encoder absent).
**Do NOT attempt `ffmpeg -c:v libwebp`** — it will fail with "Unknown encoder".
WebP encoding is handled by `scripts/optimize_assets.py` via Pillow.

### Asset Optimization Pipeline
```
scripts/optimize_assets.py
```
- Input  : `frontend/public/sequence/hero/*.png`     (120 frames, 84 MB)
- Output : `frontend/public/sequence/hero_webp/*.webp` (120 frames, 3.65 MB)
- Encoder : Pillow WebP, quality=75, method=6
- Result  : **95.7% size reduction**

Re-run when source video changes:
```bash
python3 scripts/optimize_assets.py
python3 scripts/optimize_assets.py --dry-run
```

### Frame Naming Convention
```
public/sequence/hero/         frame_001.png … frame_120.png   (source)
public/sequence/hero_webp/    frame_001.webp … frame_120.webp (optimised)
public/sequence/              0000.webp … 0088.webp           (legacy HUD)
```

---

## ScrollyCanvas
`app/components/ScrollyCanvas.tsx`

| Constant | Value | Notes |
|---|---|---|
| `FRAME_COUNT` | 120 | Hero sequence |
| `FRAMES_BASE` | `/sequence/hero_webp` | WebP path |
| `BATCH_SIZE` | 15 | OOM guard |
| `PARTICLE_THRESHOLD` | 0.65 | Scroll % to start disintegration |
| `SCROLL_HEIGHT` | 300vh | Scroll budget |

### GPU strategy
- `translateZ(0)` + `willChange: transform` → compositor layer
- `createImageBitmap()` → GPU-resident texture
- `drawImage(ImageBitmap)` → zero-copy blit
- rAF de-duplication: exactly 1 draw per display refresh

### Particle disintegration (scroll > 65%)
- Spawns `#FF0000` particles along the face-boundary circumference (cx=0.5, cy=0.35)
- `globalCompositeOperation = "screen"` → additive glow
- Particle decay: `life -= 0.018` per tick, max 200 particles in buffer

---

## Sentry Replay — Canvas Noise Budget
Canvas element (`aria-label="Hero scroll sequence"`) is **blocked** in Replay.

| Signal | Before | After |
|---|---|---|
| Canvas mutation events/sec | 30–120 | **0** |
| Replay event budget (canvas) | consumed | **preserved for UX** |
| User click / drawer interactions | captured | ✓ still captured |
| Source: `beforeAddRecordingEvent` | — | drops type=3 source=9 events |

---

## Authentication (Clerk)
`ClerkProvider` wraps the tree in `layout.tsx`.
Production keys: `pk_live_` / `sk_live_` (NOT `pk_test_`).

## TOON Format v1.0
`/api/v1/transactions/stream` emits SSE with `event: toon` type.
`useTransactionStream` returns `{ transactions, frames, isLive }`.
`frames: ToonFrame[]` drives particle fallback in ScrollyCanvas.
