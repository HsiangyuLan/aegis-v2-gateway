"use client";

/**
 * ScrollyCanvas — Portfolio Hero: GPU-accelerated scroll-driven frame renderer
 * ==============================================================================
 * Renders the hero WebP sequence (120 frames @ 1280×720) on an HTML5 Canvas.
 * Scroll progress drives both frame selection AND a CSS rotateY transform,
 * creating a depth-perspective "look-toward-camera" effect.
 *
 * Particle Disintegration
 * ───────────────────────
 * When scrollYProgress exceeds PARTICLE_THRESHOLD (0.65), the system spawns
 * disintegration particles at the "face boundary" zone — a circular region
 * centred on (0.5, 0.35) in normalised canvas coordinates, which is where the
 * subject's face sits in the Whisk-generated hero video.
 *
 * Disintegration particles:
 *  - Spawned from random points along the face-boundary circumference
 *  - Drift outward with Gaussian velocity noise
 *  - Life decays exponentially (life -= 0.02 per frame)
 *  - Rendered with globalCompositeOperation "screen" for additive glow
 *  - Colour: #FF0000 (spec §1 brand red) with alpha tied to particle life
 *  - Radius: 1–3px, scales with life
 *
 * GPU Strategy
 * ─────────────
 * 1. canvas.style.transform = "translateZ(0)" → compositor layer promotion
 * 2. createImageBitmap() → GPU-resident texture off main thread
 * 3. drawImage(ImageBitmap) → zero-copy GPU blit
 * 4. DPR-aware canvas sizing (canvas.width = CANVAS_W × devicePixelRatio)
 * 5. rAF de-duplication via cancelAnimationFrame on every scroll tick
 * 6. Rotation via motion.div CSS transform — no canvas reflow
 *
 * Preloading: batch of BATCH_SIZE=15, yields rAF between batches (OOM guard).
 * First batch completes → frame 0 rendered immediately.
 */

import {
  useRef,
  useEffect,
  useState,
  useCallback,
} from "react";
import {
  useScroll,
  useTransform,
  useMotionValueEvent,
  motion,
  type MotionValue,
} from "framer-motion";
import { useTransactionStream } from "@/app/hooks/useTransactionStream";
import type { ToonFrame } from "@/app/types/dashboard";

// ─── Constants ────────────────────────────────────────────────────────────────

const FRAME_COUNT       = 120;
const FRAMES_BASE       = "/sequence/hero_webp";
const BATCH_SIZE        = 15;
const SCROLL_HEIGHT     = "300vh";
const CANVAS_W          = 1280;
const CANVAS_H          = 720;

/** Scroll progress threshold to begin particle disintegration */
const PARTICLE_THRESHOLD = 0.65;
/** Maximum particle spawn rate per rAF tick at full trigger */
const MAX_SPAWN_PER_TICK = 4;
/** Maximum simultaneous particles in buffer */
const MAX_PARTICLES = 200;

/** Face boundary: normalised centre + radius in canvas-space pixels */
const FACE_CENTER_NX = 0.50;
const FACE_CENTER_NY = 0.35;
const FACE_RADIUS_PX = 90;

// ─── Types ────────────────────────────────────────────────────────────────────

interface Particle {
  x:     number;   // canvas-space pixels
  y:     number;
  vx:    number;
  vy:    number;
  life:  number;   // 0.0–1.0, decays per tick
  r:     number;   // base radius px
  color: string;   // hex
}

// ─── URL builder ─────────────────────────────────────────────────────────────

function frameUrl(zeroIdx: number): string {
  return `${FRAMES_BASE}/frame_${String(zeroIdx + 1).padStart(3, "0")}.webp`;
}

// ─── Preload ──────────────────────────────────────────────────────────────────

async function decodeFrame(idx: number): Promise<ImageBitmap | null> {
  try {
    const resp = await fetch(frameUrl(idx), { cache: "force-cache" });
    if (!resp.ok) return null;
    return await createImageBitmap(await resp.blob(), {
      imageOrientation: "none",
      premultiplyAlpha: "none",
      colorSpaceConversion: "none",
    });
  } catch { return null; }
}

async function preloadInBatches(
  onBatchDone: (loaded: number) => void
): Promise<(ImageBitmap | null)[]> {
  const bitmaps: (ImageBitmap | null)[] = new Array(FRAME_COUNT).fill(null);
  for (let s = 0; s < FRAME_COUNT; s += BATCH_SIZE) {
    const end = Math.min(s + BATCH_SIZE, FRAME_COUNT);
    const results = await Promise.allSettled(
      Array.from({ length: end - s }, (_, i) => decodeFrame(s + i))
    );
    results.forEach((r, j) => {
      bitmaps[s + j] = r.status === "fulfilled" ? (r.value ?? null) : null;
    });
    onBatchDone(end);
    if (end < FRAME_COUNT) {
      await new Promise<void>((res) => requestAnimationFrame(() => res()));
    }
  }
  return bitmaps;
}

// ─── Draw Routines ────────────────────────────────────────────────────────────

function drawImageFrame(
  ctx: CanvasRenderingContext2D,
  bitmap: ImageBitmap,
  cw: number,
  ch: number
): void {
  const scale = Math.min(cw / bitmap.width, ch / bitmap.height);
  const dw = bitmap.width * scale;
  const dh = bitmap.height * scale;
  ctx.clearRect(0, 0, cw, ch);
  ctx.drawImage(bitmap, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
}

function drawToonFallback(
  ctx: CanvasRenderingContext2D,
  frames: ToonFrame[],
  currentIdx: number,
  cw: number,
  ch: number
): void {
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, cw, ch);
  if (frames.length === 0) return;

  const prev = ctx.globalCompositeOperation;
  ctx.globalCompositeOperation = "multiply";
  const win = frames.slice(Math.max(0, frames.length - 60));
  win.forEach((f, ri) => {
    const age = (ri + 1) / win.length;
    const px = f.hints.x * cw;
    const py = f.hints.y * ch;
    const hex = f.hints.color.replace("#", "");
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    ctx.beginPath();
    ctx.arc(px, py, f.hints.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${r},${g},${b},${f.hints.alpha * age * 0.7})`;
    ctx.fill();
  });
  ctx.globalCompositeOperation = prev;

  // HUD watermark
  ctx.fillStyle = "rgba(0,0,0,0.15)";
  ctx.font = "11px Inter, monospace";
  ctx.fillText(`HERO_LOADING  f=${currentIdx}`, 16, 20);
}

function drawDisintegrationParticles(
  ctx: CanvasRenderingContext2D,
  particles: Particle[]
): void {
  if (particles.length === 0) return;
  const prev = ctx.globalCompositeOperation;
  ctx.globalCompositeOperation = "screen";
  for (const p of particles) {
    if (p.life <= 0) continue;
    const hex = p.color.replace("#", "");
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    const radius = p.r * p.life;
    ctx.beginPath();
    ctx.arc(p.x, p.y, Math.max(0.5, radius), 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${r},${g},${b},${p.life * 0.85})`;
    ctx.fill();
  }
  ctx.globalCompositeOperation = prev;
}

// ─── Particle spawner ─────────────────────────────────────────────────────────

function spawnParticles(
  buffer: Particle[],
  cw: number,
  ch: number,
  intensity: number  // 0–1
): void {
  const count = Math.round(intensity * MAX_SPAWN_PER_TICK);
  const cx = FACE_CENTER_NX * cw;
  const cy = FACE_CENTER_NY * ch;

  for (let i = 0; i < count; i++) {
    if (buffer.length >= MAX_PARTICLES) break;
    // Spawn along the face-boundary circumference
    const angle = Math.random() * Math.PI * 2;
    const jitter = (Math.random() - 0.5) * 20;
    const spawnR = FACE_RADIUS_PX + jitter;
    const x = cx + Math.cos(angle) * spawnR;
    const y = cy + Math.sin(angle) * spawnR;
    const speed = 0.5 + Math.random() * 2.5;
    buffer.push({
      x,
      y,
      vx: Math.cos(angle) * speed + (Math.random() - 0.5) * 1.5,
      vy: Math.sin(angle) * speed + (Math.random() - 0.5) * 1.5,
      life: 0.7 + Math.random() * 0.3,
      r:    1.0 + Math.random() * 2.5,
      color: "#FF0000",  // spec §1 brand red
    });
  }
}

function tickParticles(buffer: Particle[]): void {
  for (let i = buffer.length - 1; i >= 0; i--) {
    const p = buffer[i];
    p.x    += p.vx;
    p.y    += p.vy;
    p.vx   *= 0.97;   // drag
    p.vy   *= 0.97;
    p.life -= 0.018;
    if (p.life <= 0) buffer.splice(i, 1);
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

interface ScrollyCanvasProps {
  className?: string;
}

export default function ScrollyCanvas({ className = "" }: ScrollyCanvasProps) {
  const { frames: toonFrames } = useTransactionStream();

  const containerRef  = useRef<HTMLDivElement>(null);
  const canvasRef     = useRef<HTMLCanvasElement>(null);
  const bitmapsRef    = useRef<(ImageBitmap | null)[]>([]);
  const frameIdxRef   = useRef<number>(0);
  const rafRef        = useRef<number>(0);
  const toonRef       = useRef<ToonFrame[]>(toonFrames);
  const particlesRef  = useRef<Particle[]>([]);
  const scrollProgRef = useRef<number>(0);

  const [loadedFrames, setLoadedFrames] = useState(0);
  const [preloadDone,  setPreloadDone]  = useState(false);

  useEffect(() => { toonRef.current = toonFrames; }, [toonFrames]);

  // ── Scroll tracking ───────────────────────────────────────────────────────
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"],
  });

  // Frame index: 0 → FRAME_COUNT-1
  const frameMotion: MotionValue<number> = useTransform(
    scrollYProgress,
    [0, 1],
    [0, FRAME_COUNT - 1]
  );

  // rotateY: scroll 30%–90% → 0°–14° (look-toward-camera depth illusion)
  const rotateY: MotionValue<number> = useTransform(
    scrollYProgress,
    [0.0, 0.4, 0.9],
    [0,   8,   14]
  );

  // ── Draw ──────────────────────────────────────────────────────────────────
  const drawCurrentFrame = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    const idx    = frameIdxRef.current;
    const bitmap = bitmapsRef.current[idx] ?? null;
    const cw     = canvas.width;
    const ch     = canvas.height;

    if (bitmap) {
      drawImageFrame(ctx, bitmap, cw, ch);
    } else {
      drawToonFallback(ctx, toonRef.current, idx, cw, ch);
    }

    // Particle disintegration layer
    const sp = scrollProgRef.current;
    if (sp >= PARTICLE_THRESHOLD) {
      const intensity = (sp - PARTICLE_THRESHOLD) / (1 - PARTICLE_THRESHOLD);
      spawnParticles(particlesRef.current, cw, ch, intensity);
    }
    tickParticles(particlesRef.current);
    drawDisintegrationParticles(ctx, particlesRef.current);
  }, []);

  // ── On frame scroll change ─────────────────────────────────────────────────
  useMotionValueEvent(frameMotion, "change", (latest) => {
    const idx = Math.round(Math.min(Math.max(latest, 0), FRAME_COUNT - 1));
    if (idx !== frameIdxRef.current) {
      frameIdxRef.current = idx;
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(drawCurrentFrame);
    }
  });

  // Track scroll progress for particle intensity
  useMotionValueEvent(scrollYProgress, "change", (v) => {
    scrollProgRef.current = v;
  });

  // ── Mount: canvas setup + preload ─────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width  = CANVAS_W * dpr;
    canvas.height = CANVAS_H * dpr;
    canvas.style.maxWidth = "100%";
    canvas.style.height   = "auto";

    const ctx = canvas.getContext("2d", { alpha: false });
    if (ctx) ctx.scale(dpr, dpr);

    // GPU compositor layer promotion
    canvas.style.transform      = "translateZ(0)";
    canvas.style.willChange     = "transform";
    canvas.style.imageRendering = "auto";

    drawCurrentFrame();

    let cancelled = false;
    preloadInBatches((loaded) => {
      if (cancelled) return;
      if (loaded === BATCH_SIZE && bitmapsRef.current[0]) {
        frameIdxRef.current = 0;
        requestAnimationFrame(drawCurrentFrame);
      }
      setLoadedFrames(loaded);
      if (loaded >= FRAME_COUNT) setPreloadDone(true);
    }).then((bitmaps) => {
      if (!cancelled) {
        bitmapsRef.current = bitmaps;
        setLoadedFrames(FRAME_COUNT);
        setPreloadDone(true);
        cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(drawCurrentFrame);
      }
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      bitmapsRef.current.forEach((bm) => bm?.close());
      bitmapsRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Redraw on TOON data (fallback mode)
  useEffect(() => {
    if (!bitmapsRef.current[frameIdxRef.current]) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(drawCurrentFrame);
    }
  }, [toonFrames, drawCurrentFrame]);

  const progressPct = Math.round((loadedFrames / FRAME_COUNT) * 100);

  return (
    <div
      ref={containerRef}
      className={`relative w-full ${className}`}
      style={{ height: SCROLL_HEIGHT }}
    >
      <div
        className="sticky top-0 overflow-hidden scrolly-canvas-container"
        style={{
          width: "100%",
          height: "100vh",
          backgroundColor: "#FFFFFF",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {/*
         * rotateY applied to wrapper — CSS transform stays on compositor thread.
         * perspective needed for visible 3D depth effect.
         */}
        <motion.div
          style={{
            rotateY,
            perspective: 1200,
            perspectiveOrigin: "50% 50%",
            transformStyle: "preserve-3d",
            width: "100%",
            maxWidth: `${CANVAS_W}px`,
          }}
        >
          <canvas
            ref={canvasRef}
            className="block"
            style={{
              border: "1px solid #000000",   /* §4 1px industrial incision */
              pointerEvents: "none",         /* pass scroll events to native page scroller */
            }}
            aria-label="Hero scroll sequence"
          />
        </motion.div>

        {/* Loading overlay */}
        {!preloadDone && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              backgroundColor: `rgba(255,255,255,${0.9 - progressPct * 0.009})`,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              pointerEvents: "none",
            }}
          >
            <div
              style={{
                width: "160px",
                height: "1px",
                backgroundColor: "#000000",
                position: "relative",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  left: 0,
                  width: `${progressPct}%`,
                  backgroundColor: "#FF0000",
                  transition: "width 0.15s linear",
                }}
              />
            </div>
            <p
              style={{
                fontFamily: "var(--font-body, Inter, monospace)",
                fontWeight: 700,
                fontSize: "9px",
                letterSpacing: "0.18em",
                color: "#000000",
                textTransform: "uppercase",
                marginTop: "10px",
              }}
            >
              {loadedFrames} / {FRAME_COUNT}
            </p>
          </div>
        )}

        {/* Bottom frame counter */}
        <div
          style={{
            position: "absolute",
            bottom: "16px",
            left: "var(--nav-offset, 200px)",
            pointerEvents: "none",
          }}
          aria-hidden="true"
        >
          <span
            style={{
              fontFamily: "var(--font-body, Inter, monospace)",
              fontWeight: 700,
              fontSize: "9px",
              letterSpacing: "0.16em",
              color: "#000000",
              opacity: 0.3,
              textTransform: "uppercase",
            }}
          >
            {String(frameIdxRef.current + 1).padStart(3, "0")} / {String(FRAME_COUNT).padStart(3, "0")}
          </span>
        </div>
      </div>
    </div>
  );
}
