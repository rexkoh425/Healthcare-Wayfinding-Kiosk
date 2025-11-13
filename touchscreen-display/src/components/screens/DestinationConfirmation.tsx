"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";
import { Check, MapPin } from "lucide-react";

interface DestinationConfirmationProps {
  locations?: string[];
  onRestart?: () => void;
  targetPath?: string;
}

const DestinationConfirmation: React.FC<DestinationConfirmationProps> = ({
  locations = [],
  onRestart,
  targetPath = "/rfid",
}) => {
  const router = useRouter();
  const params = useSearchParams();
  const { send } = useWebSocket();
  const [submitting, setSubmitting] = useState(false);
  const [selectedDestination, setSelectedDestination] = useState("");

  const paramsString = params.toString();

  const destinations = useMemo(() => {
    const collected: string[] = [];
    const search = new URLSearchParams(paramsString);

    search.forEach((value, key) => {
      if (key === "destination" || key === "dest") {
        const trimmed = value.trim();
        if (trimmed.length > 0) {
          collected.push(trimmed);
        }
      }
    });

    if (collected.length === 0) {
      const raw = search.get("locations");
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          if (typeof parsed === "string") {
            const trimmed = parsed.trim();
            if (trimmed.length > 0) {
              collected.push(trimmed);
            }
          } else if (Array.isArray(parsed)) {
            for (const item of parsed) {
              if (typeof item === "string") {
                const trimmed = item.trim();
                if (trimmed.length > 0) {
                  collected.push(trimmed);
                }
              }
            }
          }
        } catch (error) {
          console.warn("Unable to parse locations query param", error);
        }
      }
    }

    if (collected.length === 0 && locations.length > 0) {
      for (const loc of locations) {
        if (typeof loc === "string" && loc.trim().length > 0) {
          collected.push(loc.trim());
        }
      }
    }

    // Dedupe while preserving order
    const seen = new Set<string>();
    const deduped = collected.filter((item) => {
      if (seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    });
    return deduped.slice(0, 3);
  }, [locations, paramsString]);

  useEffect(() => {
    // If exactly one destination is available, auto-select it.
    if (destinations.length === 1) {
      setSelectedDestination(destinations[0]);
      return;
    }

    setSelectedDestination((prev) => {
      if (destinations.length === 0) {
        return "";
      }
      if (prev && destinations.includes(prev)) {
        return prev;
      }
      return "";
    });
  }, [destinations]);

  const handleDestinationClick = (destination: string) => {
    if (submitting) return;
    setSelectedDestination(destination);
  };

  const handleConfirm = () => {
    if (!selectedDestination || submitting) {
      return;
    }

    setSubmitting(true);

    try {
      const nextParams = new URLSearchParams(paramsString);
      ["route", "dest", "destination", "locations", "from", "to"].forEach(
        (key) => {
          nextParams.delete(key);
        }
      );

      nextParams.append("dest", selectedDestination);
      const query = nextParams.toString();
      send({ type: "action", action: "hear" });
      router.push(query ? `${targetPath}?${query}` : targetPath);
    } catch (error) {
      console.error("Failed to prepare route", error);
      alert("Failed to prepare route. Please try again.");
      setSubmitting(false);
    }
  };

  const handleRestart = () => {
    send({ type: "action", action: "idle" });
    if (submitting) {
      return;
    }
    onRestart?.();
    router.replace("/");
    router.refresh();
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        {/* Header Section */}
        <div className="mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-hospital-teal/10 mb-4">
            <MapPin
              className="w-8 h-8 text-hospital-teal"
              aria-hidden="true"
              focusable="false"
            />
          </div>
          <h1 className="text-4xl font-bold text-hospital-blue-gray mb-3">
            Confirm Your Destination
          </h1>
          <p className="text-lg text-hospital-blue-gray/70">
            Please select your destination below
          </p>
        </div>

        {destinations.length === 0 ? (
          <div className="py-12">
            <p className="text-xl text-hospital-blue-gray/60">
              No destinations detected. Please try again.
            </p>
          </div>
        ) : (
          <>
            {/* Destination Selection */}
            <div className="mb-8 space-y-4">
              {destinations.map((location) => {
                const isSelected = location === selectedDestination;
                return (
                  <button
                    key={location}
                    type="button"
                    onClick={() => handleDestinationClick(location)}
                    disabled={submitting}
                    className={`
                      relative w-full rounded-xl border-[3px] px-8 py-6 text-xl font-semibold
                      transition-all duration-200 transform
                      ${
                        isSelected
                          ? "border-hospital-teal bg-hospital-teal text-white shadow-lg scale-[1.02]"
                          : "border-hospital-blue/30 bg-white text-hospital-blue-gray hover:border-hospital-teal hover:bg-hospital-teal/5 hover:scale-[1.01]"
                      }
                      ${submitting ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
                      disabled:opacity-50
                    `}
                  >
                    <div className="flex items-center justify-between">
                      <span className="flex-1 text-left">{location}</span>
                      {isSelected && (
                        <div className="flex-shrink-0 ml-4">
                          <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center">
                            <Check
                              className="w-5 h-5 text-hospital-teal"
                              strokeWidth={3}
                              aria-hidden="true"
                              focusable="false"
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Helper Text */}
            {selectedDestination && !submitting && (
              <div className="mb-6 p-4 rounded-lg bg-hospital-teal/10 border border-hospital-teal/30">
                <p className="text-hospital-teal font-medium">
                  ✓ {selectedDestination} selected. Tap &quot;Continue&quot; to
                  proceed.
                </p>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex gap-4 justify-center mt-8">
              <Button
                variant="ghost"
                onClick={handleRestart}
                disabled={submitting}
                className="text-lg px-8 py-6 h-auto text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
              >
                Start Over
              </Button>
              <Button
                onClick={handleConfirm}
                disabled={!selectedDestination || submitting}
                className={`
                  text-lg px-12 py-6 h-auto font-semibold
                  ${
                    selectedDestination && !submitting
                      ? "bg-hospital-teal hover:bg-hospital-teal/90 text-white shadow-lg hover:shadow-xl transform hover:scale-[1.02]"
                      : "bg-gray-300 text-gray-500 cursor-not-allowed"
                  }
                  transition-all duration-200
                `}
              >
                {submitting ? "Processing..." : "Continue →"}
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
};

export default DestinationConfirmation;
