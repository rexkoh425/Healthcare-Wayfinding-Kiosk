import React from "react";
import { Route, Toilet, Cookie } from "lucide-react";

export type ShowcaseIconType = "route" | "toilet" | "food";

interface ShowcaseIconProps {
  type: ShowcaseIconType;
  className?: string;
}

export const ShowcaseIcon: React.FC<ShowcaseIconProps> = ({
  type,
  className = "",
}) => {
  const baseClasses = `w-8 h-8 stroke-current ${className}`;

  switch (type) {
    case "route":
      return <Route className={baseClasses} />;
    case "toilet":
      return <Toilet className={baseClasses} />;
    case "food":
      return <Cookie className={baseClasses} />;
    default:
      return null;
  }
};
