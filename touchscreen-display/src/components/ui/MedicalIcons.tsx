import React from "react";
import {
  Hospitalized,
  Medicines,
  Ambulance,
  EarsNoseAndThroat,
  Stomach,
  Eye,
  GeneralSurgery,
  Tooth,
  Joints,
  Xray,
  ClinicalFe,
  Crutches,
  CriticalCare,
  AmbulatoryClinic,
  SocialWork,
  Kidneys,
} from "healthicons-react";

export type MedicalIconType =
  | "ward"
  | "pharmacy"
  | "ent"
  | "endoscopy"
  | "eye"
  | "surgery"
  | "dental"
  | "orthopedics"
  | "urgent-care"
  | "imaging"
  | "measurement"
  | "rehab"
  | "icu"
  | "outpatient"
  | "care"
  | "dialysis";

interface MedicalIconProps {
  type: MedicalIconType;
  className?: string;
}

export const MedicalIcon: React.FC<MedicalIconProps> = ({
  type,
  className = "",
}) => {
  const baseClasses = `w-8 h-8 fill-current ${className}`;

  switch (type) {
    case "ward":
      return <Hospitalized className={baseClasses} />;
    case "pharmacy":
      return <Medicines className={baseClasses} />;
    case "ent":
      return <EarsNoseAndThroat className={baseClasses} />;
    case "endoscopy":
      return <Stomach className={baseClasses} />;
    case "eye":
      return <Eye className={baseClasses} />;
    case "surgery":
      return <GeneralSurgery className={baseClasses} />;
    case "dental":
      return <Tooth className={baseClasses} />;
    case "orthopedics":
      return <Joints className={baseClasses} />;
    case "imaging":
      return <Xray className={baseClasses} />;
    case "urgent-care":
      return <Ambulance className={baseClasses} />;
    case "measurement":
      return <ClinicalFe className={baseClasses} />;
    case "rehab":
      return <Crutches className={baseClasses} />;
    case "icu":
      return <CriticalCare className={baseClasses} />;
    case "outpatient":
      return <AmbulatoryClinic className={baseClasses} />;
    case "care":
      return <SocialWork className={baseClasses} />;
    case "dialysis":
      return <Kidneys className={baseClasses} />;

    // Add more cases for other icon types as needed
    default:
      return null;
  }
};
