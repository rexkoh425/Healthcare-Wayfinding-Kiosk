'use client';

import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";

function resolveBackendBase(): string {
  const env = process.env.NEXT_PUBLIC_BASE_URL;
  if (env) {
    return env.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    return `${protocol}://${window.location.hostname}:8000`;
  }

  return "";
}

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

const RfidScreen: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const dest = searchParams.get("dest");
  const destinationLabel = useMemo(() => dest?.trim() ?? "", [dest]);

  const [dispensing, setDispensing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const handleTags = async () => {
      if (!destinationLabel) {
        setError("Missing destination.");
        setDispensing(false);
        return;
      }

      try {
        const rfidBase = resolveRfidReaderUrl();
        if (!rfidBase) {
          throw new Error("RFID reader URL is not configured.");
        }

        const rfidResponse = await fetch(`${rfidBase}/getTag`, {
          cache: "no-store",
        });
        if (!rfidResponse.ok) {
          throw new Error(`RFID reader error: ${rfidResponse.status}`);
        }

        const tagPayload = await rfidResponse.json();
        const tagId =
          typeof tagPayload?.epc === "string" ? tagPayload.epc.trim() : "";
        if (!tagId) {
          throw new Error("RFID tag ID missing in response.");
        }

        const backendBase = resolveBackendBase();
        if (!backendBase) {
          throw new Error("Backend URL is not configured.");
        }

        const createResponse = await fetch(`${backendBase}/users/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            rfidTagId: tagId,
            destination: destinationLabel,
          }),
        });

        if (createResponse.status === 409) {
          const updateResponse = await fetch(
            `${backendBase}/users/${encodeURIComponent(tagId)}/destination`,
            {
              method: "PATCH",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ destination: destinationLabel }),
            },
          );

          if (!updateResponse.ok) {
            throw new Error(
              `Users update error: ${updateResponse.status}`,
            );
          }
        } else if (!createResponse.ok) {
          throw new Error(`Users create error: ${createResponse.status}`);
        }

        if (cancelled) {
          return;
        }

        setDispensing(false);

        const query = destinationLabel
          ? `?dest=${encodeURIComponent(destinationLabel)}`
          : "";
        router.replace(`/final${query}`);
        router.refresh();
      } catch (err) {
        console.error("RFID handling failed", err);
        if (!cancelled) {
          setError(
            "We could not verify your sticker. Please try again or ask for assistance.",
          );
          setDispensing(false);
        }
      }
    };

    handleTags();

    return () => {
      cancelled = true;
    };
  }, [destinationLabel, router]);

  const handleBack = () => {
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    router.replace("/");
    router.refresh();
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        {dispensing && !error ? (
          <>
            <p className="text-3xl font-bold text-hospital-blue-gray">
              Dispensing Sticker...
            </p>
            {destinationLabel && (
              <p className="text-3xl font-bold text-hospital-blue-gray mt-2">
                {destinationLabel}
              </p>
            )}
          </>
        ) : (
          <>
            <p className="text-3xl font-bold text-hospital-blue-gray mb-4">
              {error ?? "Redirecting you to the final instructions..."}
            </p>
            {error && (
              <Button
                onClick={handleBack}
                variant="ghost"
                className="bg-hospital-teal hover:bg-hospital-teal/90 text-white kiosk-button"
              >
                {t("common.back")}
              </Button>
            )}
          </>
        )}
      </Card>
    </div>
  );
};

export default RfidScreen;
