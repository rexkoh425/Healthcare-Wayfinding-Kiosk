"use client";

import { useCallback } from "react";
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

export default function DestinationPage() {
  const params = useSearchParams();
  const locationsParam = params.get("locations") || "[]";
  const locations: string[] = JSON.parse(locationsParam);

  const handleRestart = useCallback(() => {
    const base = resolveOcrBase();
    if (!base) {
      return;
    }
    fetch(`${base}/latest_result/reset`, { method: "POST" }).catch((error) => {
      console.warn("Failed to reset latest OCR result on restart", error);
    });
  }, []);

  return <DestinationConfirmation locations={locations} onRestart={handleRestart} />;
}
