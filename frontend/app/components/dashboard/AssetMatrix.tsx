/**
 * AssetMatrix — Server Component (outer shell)
 * Renders the 4-column asset grid wrapper server-side.
 * Each AssetCard is a CC imported into this SC shell.
 * This pattern keeps the grid structure in the initial HTML
 * while each price cell independently subscribes to live data.
 */

import AssetCard from "./AssetCard";
import { DEMO_PRICES } from "@/app/hooks/useAssetPrices";

export default function AssetMatrix() {
  return (
    <section className="col-span-12 p-0 specular-highlights relative">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 w-full">
        {DEMO_PRICES.map((asset, i) => (
          <AssetCard
            key={asset.symbol}
            index={i}
            initialSymbol={asset.symbol}
          />
        ))}
      </div>
    </section>
  );
}
