"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";

interface DestinationConfirmationProps {
  locations: string[];
  onRestart: () => void;
  targetPath?: string;
}

const CLINIC_INDEX_URL = "/2D_map/data/clinic_map_pair.json";
const PATHS_INDEX_URL = "/2D_map/data/path_pair.json";

type Segment = {
  file: string;
  labels: [string, string];
};

const DestinationConfirmation: React.FC<DestinationConfirmationProps> = ({
  locations,
  onRestart,
  targetPath = "/wristband",
}) => {
  const router = useRouter();
  const params = useSearchParams();
  const { send } = useWebSocket();
  const [submitting, setSubmitting] = useState(false);

  const [from, to] = useMemo(() => {
    const first = locations?.[0] ?? "";
    const second = locations?.[1] ?? "";
    return [first, second];
  }, [locations]);

  const lookupPath = (index: any, a: string, b: string): string[] | null => {
    if (!a || !b) {
      return null;
    }
    const keyOne = `${a}|${b}`;
    const keyTwo = `${b}|${a}`;
    if (Array.isArray(index?.[keyOne])) {
      return index[keyOne];
    }
    if (Array.isArray(index?.[keyTwo])) {
      return index[keyTwo];
    }
    if (Array.isArray(index?.[a]?.[b])) {
      return index[a][b];
    }
    if (Array.isArray(index?.[b]?.[a])) {
      return index[b][a];
    }
    return null;
  };

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      const nextParams = new URLSearchParams(params.toString());
      nextParams.delete("route");
      nextParams.delete("dest");
      nextParams.delete("locations");

      const destHighlights = locations.slice(0, 3).filter((loc) => loc && loc.trim().length > 0);
      destHighlights.forEach((loc) => nextParams.append("dest", loc));

      if (from && to) {
        let routeAdded = false;
        const [clinicIndex, pathIndex] = await Promise.all([
          fetch(CLINIC_INDEX_URL).then((response) => response.json()),
          fetch(PATHS_INDEX_URL).then((response) => response.json()),
        ]);

        const labels = lookupPath(pathIndex, from, to);
        if (!labels || labels.length < 2 || labels.length % 2 !== 0) {
          console.warn("No valid path sequence found for the selected pair.");
        } else {
          const segments: Segment[] = [];
          for (let i = 0; i < labels.length; i += 2) {
            const aLabel = labels[i];
            const bLabel = labels[i + 1];
            const aFile = clinicIndex[aLabel];
            const bFile = clinicIndex[bLabel];
            if (!aFile || !bFile) {
              console.warn(`Missing map file for ${!aFile ? aLabel : bLabel}.`);
              continue;
            }
            segments.push({ file: aFile, labels: [aLabel, bLabel] });
          }
          if (segments.length > 0) {
            nextParams.set("route", JSON.stringify(segments));
            routeAdded = true;
          }
        }

        nextParams.set("from", from);
        nextParams.set("to", to);

        send({ type: "action", action: "route", from, to });

        if (!routeAdded) {
          alert("Unable to compute the detailed route. We'll still highlight your destination on the map.");
        }
      } else {
        nextParams.delete("from");
        nextParams.delete("to");
      }

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

        {locations.length === 0 ? (
          <p>No destinations detected.</p>
        ) : (
          <ul className="mb-8 space-y-2">
            {locations.map((location) => (
              <li key={location} className="text-lg">
                {location}
              </li>
            ))}
          </ul>
        )}

        <div className="flex justify-center gap-4">
          <Button
            onClick={handleConfirm}
            disabled={locations.length === 0 || submitting}
            className="bg-hospital-teal text-white"
          >
            {submitting ? "Preparing..." : "Confirm"}
          </Button>
          <Button variant="ghost" onClick={onRestart} disabled={submitting}>
            Restart
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default DestinationConfirmation;
