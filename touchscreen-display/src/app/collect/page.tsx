import React, { Suspense } from "react";
import CollectSticker from "@/components/screens/CollectSticker";

export default function CollectRoute() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center">Loading collect sticker screen...</div>}
    >
      <CollectSticker />
    </Suspense>
  );
}
