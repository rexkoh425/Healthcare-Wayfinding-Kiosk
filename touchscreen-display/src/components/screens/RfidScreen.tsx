"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SchoolIcon, type SchoolIconType } from "@/components/ui/SchoolIcons";
import { useRouter, useSearchParams } from "next/navigation";
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

function isSchoolIconType(
  value: string | undefined | null
): value is SchoolIconType {
  if (!value) {
    return false;
  }
  return (SCHOOL_ICON_TYPES as readonly string[]).includes(value.trim());
}

const RfidScreen: React.FC = () => {
  const router = useRouter();
  const { send } = useWebSocket();
  const searchParams = useSearchParams();
  const { send } = useWebSocket();

  const dest = searchParams.get("dest");
  const destinationLabel = useMemo(() => dest?.trim() ?? "", [dest]);
  const iconParam = searchParams.get("icon");
  const unitParam = searchParams.get("unitNumber") ?? searchParams.get("unit");

  // Fetch destination info (icon, unit number)
  useEffect(() => {
    if (!dest) return;
    const fetchDestinationInfo = async () => {
      try {
        const res = await fetch(
          `${baseUrl}/destinations/?name=${encodeURIComponent(dest)}`
        );
        if (!res.ok) throw new Error("Failed to fetch destination info");
        const data: { icon?: string; unitNumber?: string } = await res.json();
        setIcon(data.icon || null);
        setUnitNumber(data.unitNumber || null);
      } catch (err) {
        console.warn("Could not fetch destination info", err);
        setIcon(null);
        setUnitNumber(null);
      }
    };
    fetchDestinationInfo();
  }, [dest, baseUrl]);

  useEffect(() => {
    let cancelled = false;

    const handleTags = async () => {
      if (!destinationLabel) {
        setError("Missing destination.");
        setDispensing(false);
        return;
      }

    const isInstructionRecord = (item: unknown): item is InstructionRecord => {
      if (typeof item !== "object" || item === null) return false;
      const rec = item as Record<string, unknown>;
      return (
        typeof rec.location === "string" && typeof rec.directions === "string"
      );
    };

    const fetchAndSpeak = async () => {
      send({ type: "action", action: "hear" });
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

        const instructions = payload.filter(isInstructionRecord);

        const normalized = dest.trim().toLowerCase();
        const match = instructions.find(
          (item) =>
            item.location.trim().toLowerCase() === normalized &&
            item.directions.trim().length > 0
        );

        if (!match) {
          console.warn("No matching instructions found for destination:", dest);
          return;
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
            }
          );

          if (!updateResponse.ok) {
            throw new Error(`Users update error: ${updateResponse.status}`);
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
            "We could not verify your sticker. Please try again or ask for assistance."
          );
          setDispensing(false);
        }
      }
    };

    handleTags();

    return () => {
      cancelled = true;
    };
  }, [dest, send]);

  useEffect(() => {
    async function handleTags() {
      try {
        // 1️⃣ GET request
        const rfidUrl = resolveRfidReaderUrl();
        if (!rfidUrl) throw new Error("RFID reader URL is not configured.");
        console.log("Requesting RFID reader at:", rfidUrl);
        const espRes = await fetch(rfidUrl);
        if (!espRes.ok)
          throw new Error(`HTTP error from rfid! status: ${espRes.status}`);

        const tagData = await espRes.json();
        console.log("Received from RFID Reader:", tagData);

        // 2️⃣ POST request to user/backend
        const usersUrl = `${baseUrl}/users/`;
        console.log("Posting to Users", usersUrl);
        const postRes = await fetch(usersUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            rfidTagId: tagData.epc,
            destination: dest,
          }),
        });

        if (postRes.ok) {
          const postResult = await postRes.json();
          console.log("POST result:", postResult);
          setDispensing(false);
        } else if (postRes.status == 409) {
          setDispensing(false);
        } else {
          throw new Error(
            `HTTP error from users api! status: ${postRes.status}`
          );
        }
      } catch (err) {
        console.error(err);
      }
    }
    handleTags();
  }, [baseUrl, dest]);

  // useEffect(() => {
  //   // Only start the timer when the collection screen is visible (`dispensing` is false)
  //   if (!dispensing) {
  //     const inactivityTimer = setTimeout(() => {
  //       console.log("Timeout: User collect sticker. Navigating home.");
  //       // Navigate back to the main page after 15 seconds
  //       send({ type: "action", action: "idle" });
  //       router.push("/");
  //     }, 15000); // 15000 milliseconds = 15 seconds

  //     //Cleanup function to clear timer
  //     return () => {
  //       clearTimeout(inactivityTimer);
  //     };
  //   }
  // }, [dispensing, router]);

  const handleCollected = () => {
    // send action to server (touchscreen -> hologram)
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
                    {destinationLabel || "Loading destination..."}
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
              Please wait while we prepare your wayfinding sticker.
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
              Back
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
};

export default RfidScreen;
