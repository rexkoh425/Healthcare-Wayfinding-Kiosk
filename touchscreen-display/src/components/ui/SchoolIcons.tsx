import React from "react";
import Icon from "@mdi/react";
import {
  mdiHumanMaleBoard,
  mdiBaguette,
  mdiStore24Hour,
  mdiTools,
  mdiHeadCog,
  mdiChairSchool,
  mdiOfficeBuildingMarker,
} from "@mdi/js";

export type SchoolIconType =
  | "lecture"
  | "bakery"
  | "convenience-store"
  | "lab"
  | "classroom"
  | "workshop"
  | "building";

interface SchoolIconProps {
  type: SchoolIconType;
  className?: string;
}

export const SchoolIcon: React.FC<SchoolIconProps> = ({
  type,
  className = "",
}) => {
  const baseClasses = `w-8 h-8 fill-current ${className}`;

  switch (type) {
    case "lecture":
      return <Icon path={mdiHumanMaleBoard} size={4} className={baseClasses} />;
    case "bakery":
      return <Icon path={mdiBaguette} size={4} className={baseClasses} />;
    case "convenience-store":
      return <Icon path={mdiStore24Hour} size={4} className={baseClasses} />;
    case "lab":
      return <Icon path={mdiTools} size={4} className={baseClasses} />;
    case "classroom":
      return <Icon path={mdiHeadCog} size={4} className={baseClasses} />;
    case "workshop":
      return <Icon path={mdiChairSchool} size={4} className={baseClasses} />;
    case "building":
      return (
        <Icon path={mdiOfficeBuildingMarker} size={4} className={baseClasses} />
      );
    default:
      return null;
  }
};
