"use client";

import React, { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SmartphoneNfc, Loader2, AlertCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";

function resolveNfcUrl(): string {
  const env = process.env.NEXT_PUBLIC_RFID_URL;
  if (env) return env;

  if (typeof window !== "undefined") {
    // const protocol = window.location.protocol === "https:" ? "https" : "http";
    const protocol = "https";
    const host = window.location.hostname;
    return `${protocol}://${host}:5001`;
  }

  return "";
}

const NfcScreen: React.FC = () => {
  const router = useRouter();
  const { send } = useWebSocket();

  const [loading, setLoading] = useState(false); // set loading to true when processing tap
  const [error, setError] = useState<string | null>(null);

  const handleTap = async () => {
    setLoading(true);

    try {
      // Example: fetch destination from nfc card after tap
      const nfc_api = resolveNfcUrl();
      const res = await fetch(nfc_api);

      if (!res.ok) {
        throw new Error("Failed to read card. Please try again.");
      }

      const data = await res.json();
      const destinations = data.destinations; // e.g., ["Active Learning Room"]

      if (!destinations || destinations.length === 0) {
        throw new Error("No destination found on card.");
      }

      send({ type: "action", action: "hear" });
      // If only one destination:
      router.push(`/rfid?dest=${encodeURIComponent(destinations[0])}`);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message || "Failed to read card. Please try again.");
      } else {
        setError("Failed to read card. Please try again.");
      }
      setLoading(false);
    }
  };

  const handleBack = () => {
    send({ type: "action", action: "idle" });
    router.replace("/");
  };

  // Automatically attempt to read card when screen loads
  useEffect(() => {
    handleTap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col items-center justify-center h-[80vh] animate-fade-in">
      <Card className="w-full max-w-2xl p-12 text-center">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-foreground mb-4">
            Tap Your Card
          </h1>
          <p className="text-muted-foreground text-2xl">
            Place your matric card on the NFC reader to continue
          </p>
        </div>

        {/* NFC Icon - Large and Animated */}
        <div className="flex justify-center mb-8">
          <div className={`relative ${loading ? "" : "animate-pulse"}`}>
            {!loading && (
              <>
                <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
                <div className="absolute inset-0 rounded-full bg-primary/10 animate-pulse" />
              </>
            )}
            <div className="relative bg-gradient-to-br from-primary to-primary/70 p-12 rounded-full shadow-lg">
              {loading ? (
                <Loader2 className="h-32 w-32 text-primary-foreground animate-spin" />
              ) : (
                <SmartphoneNfc className="h-32 w-32 text-primary-foreground" />
              )}
            </div>
          </div>
        </div>

        {/* Status Message */}
        <div className="min-h-[80px] mb-8">
          {loading ? (
            <div className="space-y-3 animate-fade-in">
              <p className="text-3xl font-semibold text-foreground">
                Reading Card...
              </p>
              <p className="text-xl text-muted-foreground">
                Please keep your card on the reader
              </p>
            </div>
          ) : error ? (
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center justify-center gap-2 text-destructive">
                <AlertCircle className="h-8 w-8" />
                <p className="text-3xl font-semibold">Error</p>
              </div>
              <p className="text-xl text-muted-foreground">{error}</p>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-3xl font-semibold text-foreground">
                Ready to Scan
              </p>
            </div>
          )}
        </div>

        {/* Retry if error */}
        {error && (
          <Button
            onClick={handleTap}
            variant="outline"
            size="lg"
            className="w-full py-6 text-2xl border-2"
          >
            Try Again
          </Button>
        )}

        <div className="flex justify-between mt-6">
          <Button
            onClick={handleBack}
            variant="ghost"
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
          >
            Back
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default NfcScreen;
