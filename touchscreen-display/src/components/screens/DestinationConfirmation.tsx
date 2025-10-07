"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";

interface DestinationConfirmationProps {
  locations?: string[];
  onRestart: () => void;
  targetPath?: string;
}

const DestinationConfirmation: React.FC<DestinationConfirmationProps> = ({
  locations = [],
  onRestart,
  targetPath = "/wristband",
}) => {
  const router = useRouter();
  const params = useSearchParams();
  const [submitting, setSubmitting] = useState(false);

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

  const handleSelectDestination = (selected: string) => {
    if (!selected) {
      alert("No destination selected. Please restart the scan.");
      return;
    }
    setSubmitting(true);
    try {
      const nextParams = new URLSearchParams(paramsString);
      ["route", "dest", "destination", "locations", "from", "to"].forEach((key) => {
        nextParams.delete(key);
      });

      nextParams.append("dest", selected);

      const query = nextParams.toString();
      router.push(query ? `${targetPath}?${query}` : targetPath);
    } catch (error) {
      console.error("Failed to prepare route", error);
      alert("Failed to prepare route. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh]">
      <Card className="w-full max-w-xl p-8 text-center">
        <h2 className="text-2xl font-semibold mb-6">Detected Destinations</h2>

        {destinations.length === 0 ? (
          <p>No destinations detected.</p>
        ) : (
          <div className="mb-8 flex flex-col gap-4">
            {destinations.map((location) => (
              <Button
                key={location}
                onClick={() => handleSelectDestination(location)}
                disabled={submitting}
                className="bg-hospital-teal text-white text-lg py-6"
              >
                {location}
              </Button>
            ))}
          </div>
        )}

        <div className="flex justify-center">
          <Button variant="ghost" onClick={onRestart} disabled={submitting}>
            Restart
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default DestinationConfirmation;
