"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import useWebSocket from "@/lib/useWebSocket";

export default function WristbandPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { send } = useWebSocket();

  useEffect(() => {
    send({ type: "action", action: "route-prep" });
    return () => {
      send({ type: "action", action: "idle" });
    };
  }, [send]);

  const handleContinue = () => {
    const query = params.toString();
    const next = query ? `/2D_map?${query}` : "/2D_map";
    router.push(next);
  };

  const handleRestart = () => {
    router.push("/camera");
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-b from-[#e0f7ff] to-white px-6">
      <Card className="w-full max-w-3xl space-y-6 p-10 text-center shadow-xl">
        <h1 className="text-3xl font-semibold text-hospital-blue-gray">
          Remember Your Wristband
        </h1>
        <p className="text-lg text-hospital-blue-gray/80">
          Please pick up a wristband from the dispenser and wear it for your entire visit so our staff can assist you quickly.
        </p>

        <div className="flex h-48 w-full items-center justify-center rounded-lg border-2 border-dashed border-hospital-teal/60 bg-hospital-teal/5 text-hospital-blue-gray/70">
          <span className="text-sm font-medium uppercase tracking-wide">
            Wristband action GIF placeholder
            <br />
            (Drop your animation asset here)
          </span>
        </div>

        <div className="space-y-3 text-left text-hospital-blue-gray/90">
          <p className="text-lg font-medium">Quick steps:</p>
          <ul className="list-disc space-y-2 pl-6 text-base">
            <li>Open the wristband box beside the kiosk.</li>
            <li>Take one wristband and fasten it securely on your wrist.</li>
            <li>Keep it on until a staff member removes it for you.</li>
          </ul>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
          <Button onClick={handleContinue} className="bg-hospital-teal px-6 py-3 text-white">
            Continue to Directions
          </Button>
          <Button variant="ghost" onClick={handleRestart} className="px-6 py-3">
            Restart Scan
          </Button>
        </div>
      </Card>
    </main>
  );
}
