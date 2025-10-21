"use client";

import { useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import DestinationConfirmation from "@/components/screens/DestinationConfirmation";

function resolveOcrBase(): string {
  const env = process.env.NEXT_PUBLIC_OCR_API_BASE;
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window === "undefined") {
    return "";
  }
  const protocol = window.location.protocol === "https:" ? "https" : "http";
  return `${protocol}://${window.location.hostname}:9000`;
}

function DestinationPageContent() {
  const params = useSearchParams();
  const locationsParam = params.get("locations") || "[]";
  const locations: string[] = JSON.parse(locationsParam);

  const handleRestart = useCallback(() => {
    const base = resolveOcrBase();
    if (!base) return;
    fetch(`${base}/latest_result/reset`, { method: "POST" }).catch((error) => {
      console.warn("Failed to reset latest OCR result on restart", error);
    });
  }, []);

  return (
    <DestinationConfirmation locations={locations} onRestart={handleRestart} />
  );
}

export default function DestinationPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center">Loading destination...</div>}
    >
      <DestinationPageContent />
    </Suspense>
  );
}
