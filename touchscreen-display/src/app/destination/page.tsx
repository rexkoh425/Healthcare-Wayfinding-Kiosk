"use client";

import { useSearchParams } from "next/navigation";
import DestinationConfirmation from "@/components/screens/DestinationConfirmation";

export default function DestinationPage() {
  const params = useSearchParams();
  const locationsParam = params.get("locations") || "[]";
  const locations: string[] = JSON.parse(locationsParam);

  return <DestinationConfirmation locations={locations} />;
}
