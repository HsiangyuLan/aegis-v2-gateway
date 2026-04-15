/**
 * GridPins — Server Component
 * Pure decorative corner and intersection pin dots rendered server-side.
 * No interactivity; CSS handles the glow entirely.
 */
export default function GridPins() {
  return (
    <div className="absolute inset-0 pointer-events-none z-0">
      {/* Four corners */}
      <div className="pin absolute left-[24px] top-[24px]" />
      <div className="pin absolute right-[24px] top-[24px]" />
      <div className="pin absolute left-[24px] bottom-[24px]" />
      <div className="pin absolute right-[24px] bottom-[24px]" />

      {/* Centre crosshair — 40% opacity */}
      <div className="pin absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-40" />

      {/* Golden-ratio intersection accents — 20% opacity */}
      <div className="pin absolute left-1/4 top-1/3 opacity-20" />
      <div className="pin absolute right-1/4 bottom-1/3 opacity-20" />
    </div>
  );
}
