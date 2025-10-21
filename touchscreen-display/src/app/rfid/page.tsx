import React, { Suspense } from "react";
import RfidScreen from "@/components/screens/RfidScreen";

export default function RfidPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center">Loading RFID screen...</div>}
    >
      <RfidScreen />
    </Suspense>
  );
}
