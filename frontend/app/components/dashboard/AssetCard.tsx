"use client";

/**
 * AssetCard — Client Component
 * Displays a single asset's price, spread, and trend.
 * Subscribes to useAssetPrices; all four cards share one in-flight request
 * via the module-level cache in the hook.
 */

import { useAssetPrices } from "@/app/hooks/useAssetPrices";
import type { AssetTrend } from "@/app/types/dashboard";

const TREND_ICON: Record<AssetTrend, string> = {
  up:   "trending_up",
  flat: "trending_flat",
  down: "trending_down",
};

const TREND_COLOR: Record<AssetTrend, string> = {
  up:   "text-primary",
  flat: "text-stone-600",
  down: "text-error",
};

const BAR_COLOR: Record<AssetTrend, string> = {
  up:   "bg-primary",
  flat: "bg-stone-800",
  down: "bg-stone-800",
};

interface AssetCardProps {
  /** Index into the prices array (0=BTC, 1=ETH, 2=SOL, 3=LINK) */
  index: number;
  /** Initial/fallback values for SSR hydration */
  initialSymbol: string;
}

export default function AssetCard({ index, initialSymbol }: AssetCardProps) {
  const prices = useAssetPrices();
  const asset = prices[index];

  if (!asset) return null;

  const isActive = asset.trend === "up";

  return (
    <div className="p-8 specular-highlights relative" style={isActive ? { background: "rgba(14, 165, 233, 0.03)" } : undefined}>
      <div className="flex justify-between items-start mb-6">
        <div
          className={`text-[10px] font-bold tracking-widest uppercase secondary-label ${isActive ? "text-primary" : "text-stone-500"}`}
          style={{ fontFamily: "var(--font-headline)" }}
        >
          {asset.symbol}
        </div>
        <span className={`material-symbols-outlined text-sm ${TREND_COLOR[asset.trend]}`}>
          {TREND_ICON[asset.trend]}
        </span>
      </div>

      <div
        className="text-3xl tabular mb-2 soft-glow-data"
        style={{ fontFamily: "var(--font-headline)" }}
      >
        {asset.price.toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 2,
        })}
      </div>

      <div className="text-[10px] text-stone-500 font-mono secondary-label">
        SPREAD: {asset.spread.toFixed(4)}%
      </div>

      <div className={`mt-4 h-1 w-full ${BAR_COLOR[asset.trend]}`} />

      <div className="pin absolute bottom-0 right-0" />
    </div>
  );
}
