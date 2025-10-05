import React from "react";
import { Button } from "@/components/ui/button";
import { Info } from "lucide-react";

interface Destination {
  id: number;
  name: string;
  direction: string;
}

interface DestinationButtonProps {
  destination: Destination;
  onClick: () => void;
}

const getDirectionalArrow = (direction: string) => {
  switch (direction.toLowerCase()) {
    case "up":
      return (
        <img
          src="/icons/upstair.svg"
          alt="Upstair Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    case "down":
      return (
        <img
          src="/icons/downstair.svg"
          alt="Downstair Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    case "straight":
      return (
        <img
          src="/icons/straight.svg"
          alt="Straight Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    case "left":
      return (
        <img
          src="/icons/left.svg"
          alt="Left Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    case "right":
      return (
        <img
          src="/icons/right.svg"
          alt="Right Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    case "back":
      return (
        <img
          src="/icons/back.svg"
          alt="Back Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
    default:
      return (
        <img
          src="/icons/straight.svg"
          alt="Straight Icon"
          className="w-8 h-8 hover:opacity-80"
        />
      );
  }
};

export const DestinationButton: React.FC<DestinationButtonProps> = ({
  destination,
  onClick,
}) => {
  return (
    <Button
      onClick={onClick}
      variant="outline"
      className="flex items-center justify-between p-4 text-hospital-blue-gray border-2 border-hospital-blue/30 hover:border-hospital-teal hover:bg-hospital-teal/5 rounded-xl kiosk-button min-h-[80px] w-full"
    >
      <div className="flex items-center space-x-3">
        {getDirectionalArrow(destination.direction)}
        <span className="text-lg font-semibold">{destination.name}</span>
      </div>
      <Info size={24} className="text-hospital-teal" />
    </Button>
  );
};
