import React, { useMemo } from "react";
import { DestinationButton } from "@/components/ui/destination-button";

interface Destination {
  id: number;
  name: string;
  direction: string;
}

interface DirectionalLayoutProps {
  destinations: Destination[];
  onDestinationClick: (id: number) => void;
}

export const DirectionalLayout: React.FC<DirectionalLayoutProps> = ({
  destinations,
  onDestinationClick,
}) => {
  // 1) group by lowercase direction
  const grouped = useMemo(() => {
    return destinations.reduce(
      (acc, dest) => {
        const dir = dest.direction.toLowerCase();
        if (!acc[dir]) acc[dir] = [];
        acc[dir].push(dest);
        return acc;
      },
      {} as Record<string, Destination[]>
    );
  }, [destinations]);

  // 2) fixed order of direction-rows
  const order = ["up", "straight", "left", "right", "back", "down"] as const;

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6">
      {order.map((dir) => {
        const items = grouped[dir] || [];
        if (items.length === 0) return null;

        return (
          <div key={dir} className={`grid grid-cols-1 gap-4`}>
            {items.map((dest) => (
              <DestinationButton
                key={dest.id}
                destination={dest}
                onClick={() => onDestinationClick(dest.id)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
};
