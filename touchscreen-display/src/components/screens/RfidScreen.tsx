'use client';

import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SchoolIcon, type SchoolIconType } from "@/components/ui/SchoolIcons";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { AlertCircle, CheckCircle2 } from "lucide-react";
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

const SCHOOL_ICON_TYPES: readonly SchoolIconType[] = [
  "lecture",
  "bakery",
  "convenience-store",
  "lab",
  "classroom",
  "workshop",
  "building",
];

function isSchoolIconType(value: string | undefined | null): value is SchoolIconType {
  if (!value) {
    return false;
  }
  return (SCHOOL_ICON_TYPES as readonly string[]).includes(value.trim());
}

const RfidScreen: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const dest = searchParams.get("dest");
  const destinationLabel = useMemo(() => dest?.trim() ?? "", [dest]);
  const iconParam = searchParams.get("icon");
  const unitParam = searchParams.get("unitNumber") ?? searchParams.get("unit");

  const iconType = useMemo(
    () => {
      const trimmed = iconParam?.trim();
      return isSchoolIconType(trimmed) ? (trimmed as SchoolIconType) : null;
    },
    [iconParam],
  );

  const unitLabel = useMemo(() => unitParam?.trim() ?? "", [unitParam]);

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
        router.replace(`/collect${query}`);
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

  const isProcessing = dispensing && !error;
  const hasError = Boolean(error);

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in px-6">
      <Card className="w-[90vw] max-w-4xl p-12 text-center kiosk-card flex flex-col items-center">
        {isProcessing && (
          <>
            <div className="mb-12 flex flex-col items-center">
              <div className="inline-flex items-center justify-center w-20 h-20 mb-6 bg-hospital-teal/10 rounded-full animate-pulse-dot">
                <div className="w-10 h-10 bg-hospital-teal rounded-full" />
              </div>

              <h1 className="text-5xl font-bold text-hospital-blue-gray mb-4">
                Dispensing Sticker...
              </h1>

              {(destinationLabel || iconType || unitLabel) && (
                <div className="inline-flex items-center px-8 py-4 bg-hospital-blue/10 rounded-xl gap-8">
                  <p className="text-4xl font-semibold text-hospital-teal">
                    {destinationLabel ||
                      t("common.loading", { defaultValue: "Loading..." })}
                  </p>
                  {(iconType || unitLabel) && (
                    <div className="flex flex-col items-center justify-center text-hospital-blue-gray">
                      {iconType && (
                        <SchoolIcon
                          type={iconType}
                          className="w-16 h-16 mb-2 text-hospital-teal"
                        />
                      )}
                      {unitLabel && (
                        <div className="text-2xl font-semibold text-hospital-blue-gray mb-2">
                          {unitLabel}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-center gap-3 mb-12">
              {[0, 0.2, 0.4].map((delay) => (
                <div
                  key={delay}
                  className="w-3 h-3 bg-hospital-teal rounded-full animate-pulse-dot"
                  style={{ animationDelay: `${delay}s` }}
                />
              ))}
            </div>

            <p className="text-xl text-hospital-blue-gray/60 mb-12 max-w-2xl">
              Please hold your wristband steady while we prepare your wayfinding sticker.
            </p>

            <div className="flex justify-end w-full">
              <Button
                onClick={handleBack}
                variant="ghost"
                className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10 text-2xl"
              >
                Need Help
              </Button>
            </div>
          </>
        )}

        {!isProcessing && !hasError && (
          <div className="flex flex-col items-center space-y-6">
            <div className="inline-flex items-center justify-center w-20 h-20 bg-hospital-teal/10 rounded-full">
              <CheckCircle2 className="w-12 h-12 text-hospital-teal" />
            </div>
            <h2 className="text-4xl font-bold text-hospital-blue-gray">
              Sticker ready!
            </h2>
            <p className="text-2xl text-hospital-blue-gray/70">
              Redirecting you to your collection instructions...
            </p>
          </div>
        )}

        {hasError && (
          <div className="flex flex-col items-center space-y-10">
            <div className="inline-flex items-center justify-center w-20 h-20 bg-red-100 rounded-full">
              <AlertCircle className="w-12 h-12 text-red-500" />
            </div>
            <h2 className="text-4xl font-bold text-hospital-blue-gray leading-snug">
              {error}
            </h2>
            <p className="text-2xl text-hospital-blue-gray/60 max-w-2xl">
              Please try again or ask a staff member for assistance.
            </p>
            <Button
              onClick={handleBack}
              className="bg-hospital-teal hover:bg-hospital-teal/90 text-white text-xl px-10 py-6"
            >
              {t("common.back")}
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
};

export default RfidScreen;
