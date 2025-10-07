// components/ui/Spinner.tsx
import React from "react";

type SpinnerProps = {
  size?: number;
  className?: string;
};

export default function Spinner({ size = 24, className = "" }: SpinnerProps) {
  return (
    <svg
      className={`animate-spin ${className}`}
      style={{ width: size, height: size }}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 11-8 8h4l-3 3-3-3h4z"
        fill="currentColor"
      />
    </svg>
  );
}
