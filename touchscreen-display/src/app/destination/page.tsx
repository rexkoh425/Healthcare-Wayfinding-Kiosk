"use client";

import { useSearchParams, useRouter } from "next/navigation";
import DestinationConfirmation from "@/components/screens/DestinationConfirmation";

export default function DestinationPage() {
  const params = useSearchParams();
  const router = useRouter();
  const locationsParam = params.get("locations") || "[]";
  const locations: string[] = JSON.parse(locationsParam);

  return (
    <DestinationConfirmation
      locations={locations}
      onRestart={() => router.push("/camera")}
    />
  );
}
