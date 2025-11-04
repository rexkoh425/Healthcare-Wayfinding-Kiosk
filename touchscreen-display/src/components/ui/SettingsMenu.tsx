"use client";

import React, { useEffect, useRef } from "react";
import { Toggle } from "@/components/ui/toggle";

type Props = {
  open: boolean;
  onClose: () => void;
  scanMode: "camera" | "nfc";
  setScanMode: (m: "camera" | "nfc") => void;
  openerRef: React.RefObject<HTMLElement | null> | null;
};

export default function SettingsMenu({
  open,
  onClose,
  scanMode,
  setScanMode,
  openerRef,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const titleId = "settings-menu-title";

  // Click-outside handler
  useEffect(() => {
    if (!open) return;

    function onPointer(e: PointerEvent) {
      const el = containerRef.current;
      if (!el) return;
      // If click is outside the menu container
      if (!el.contains(e.target as Node)) {
        // ...but also not on the opener element
        if (
          !(
            openerRef &&
            openerRef.current &&
            (openerRef.current === e.target ||
              (openerRef.current instanceof HTMLElement &&
                openerRef.current.contains(e.target as Node)))
          )
        ) {
          onClose();
        }
      }
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  // Focus management: move focus into the dialog when opened, and return to opener on close
  useEffect(() => {
    if (!open) return;
    const el = containerRef.current;
    // Prefer the close button if present
    const firstFocusable = el?.querySelector<HTMLElement>(
      "button.close-btn, button, [tabindex]:not([tabindex='-1'])"
    );
    (firstFocusable || el)?.focus();
  }, [open]);

  useEffect(() => {
    if (open) return;
    // when closed, return focus to opener
    if (openerRef && openerRef.current) {
      try {
        (openerRef.current as HTMLElement).focus();
      } catch {}
    }
  }, [open, openerRef]);

  if (!open) return null;

  return (
    <div
      id="settings-menu"
      ref={containerRef}
      role="dialog"
      aria-labelledby={titleId}
      aria-modal="true"
      tabIndex={-1}
      className="text-hospital-blue-gray/70 fixed bottom-16 right-4 w-48 bg-white border rounded-lg shadow-lg p-4 z-50"
    >
      <div className="flex items-start justify-between">
        <h4 id={titleId} className="font-medium mb-2">
          Scan Method
        </h4>
        {/* Close button for accessibility and convenience */}
        <button
          type="button"
          className="close-btn ml-2 p-1 rounded hover:bg-slate-100"
          aria-label="Close settings"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      <div className="flex flex-col space-y-2">
        <Toggle
          pressed={scanMode === "camera"}
          onPressedChange={(pressed) => pressed && setScanMode("camera")}
          className="justify-between"
        >
          <span>Camera</span>
        </Toggle>

        <Toggle
          pressed={scanMode === "nfc"}
          onPressedChange={(pressed) => pressed && setScanMode("nfc")}
          className="justify-between"
        >
          <span>NFC</span>
        </Toggle>
      </div>
    </div>
  );
}
