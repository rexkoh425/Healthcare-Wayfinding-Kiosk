'use client';

import React, { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useRouter, useSearchParams } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";
import Image from "next/image";

const RFID_POLL_INTERVAL_MS = 1500;

function resolveRfidReaderUrl(): string {
  const env = process.env.NEXT_PUBLIC_RFID_URL;
  if (env) {
    return env.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    return `${protocol}://${window.location.hostname}:5000`;
  }

  return "";
}

function isTagRemoved(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") {
    return false;
  }
  const record = payload as Record<string, unknown>;
  if (typeof record.removed === "boolean") {
    return record.removed;
  }
  const present = record.present;
  if (typeof present === "boolean") {
    return !present;
  }
  const epc = record.epc;
  if (typeof epc === "string") {
    return epc.trim().length === 0;
  }
  return true;
}

const CollectSticker: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { send } = useWebSocket();

  const dest = searchParams.get("dest");
  const destinationLabel = useMemo(() => dest?.trim() ?? "", [dest]);

  const [error, setError] = useState<string | null>(null);
  const [tagRemoved, setTagRemoved] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const base = resolveRfidReaderUrl();
    if (!base) {
      setError("RFID reader is unavailable. Please ask for assistance.");
      return undefined;
    }

    const poll = async () => {
      try {
        const response = await fetch(`${base}/tagRemoved`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`RFID poll error: ${response.status}`);
        }
        const payload = await response.json();
        if (!cancelled && isTagRemoved(payload)) {
          setTagRemoved(true);
        }
      } catch (err) {
        console.warn("Failed to poll tag removal", err);
      }
    };

    poll();
    const intervalId = window.setInterval(poll, RFID_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (!tagRemoved) {
      return;
    }
    const query = destinationLabel ? `?dest=${encodeURIComponent(destinationLabel)}` : "";
    router.replace(`/final${query}`);
    router.refresh();
  }, [tagRemoved, destinationLabel, router]);

  const handleNeedHelp = () => {
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    router.replace("/");
    router.refresh();
  };

  return (
    <div className="flex flex-col items-center justify-center h-[80vh] animate-fade-in px-6">
      <Card className="w-full max-w-2xl p-12 text-center kiosk-card space-y-8">
        <div className="space-y-4">
          <h1 className="text-3xl font-bold text-hospital-blue-gray">
            Please collect your sticker.
          </h1>
          <p className="text-2xl text-hospital-blue-gray/80">
            Stick it vertically on your pants before proceeding
            {destinationLabel ? ` to ${destinationLabel}.` : "."}
          </p>
        </div>

        <div className="flex justify-center">
          <Image
            src="/rfid/wearGuide.jpg"
            alt="RFID Wear Guide"
            width={320}
            height={480}
            className="rounded-lg object-contain shadow-md"
          />
        </div>

        {error && (
          <p className="text-xl text-red-600 font-semibold">{error}</p>
        )}

        <div className="flex justify-center">
          <Button
            onClick={handleNeedHelp}
            variant="ghost"
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10 text-xl"
          >
            Need Help
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default CollectSticker;
