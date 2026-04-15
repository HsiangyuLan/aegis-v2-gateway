/**
 * ScanlineOverlay — Server Component
 * Full-canvas CRT scan-line texture layer. Pure CSS, z-index 20,
 * pointer-events: none so it never blocks clicks beneath it.
 */
export default function ScanlineOverlay() {
  return (
    <div
      className="absolute inset-0 scanline-overlay z-20"
      aria-hidden="true"
    />
  );
}
