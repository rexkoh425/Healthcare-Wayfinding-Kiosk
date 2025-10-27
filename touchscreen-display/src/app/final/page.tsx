import React, { Suspense } from "react";
import FinalPage from "@/components/screens/FinalPage";

export default function FinalRoute() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center">Loading final instructions...</div>}
    >
      <FinalPage />
    </Suspense>
  );
}
