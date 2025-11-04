"use client";

import React, { useState } from "react";
import HomeScreen from "@/components/screens/HomeScreen";
import NusHomeScreen from "@/components/screens/NusHomeScreen";
import { Button } from "@/components/ui/button";
import SettingsMenu from "@/components/ui/SettingsMenu";
import { Settings } from "lucide-react";

const HomePage: React.FC = () => {
  const [scanMode, setScanMode] = useState<"camera" | "nfc">(() => {
    try {
      const v =
        typeof window !== "undefined"
          ? window.localStorage.getItem("scanMode")
          : null;
      return v === "nfc" ? "nfc" : "camera";
    } catch {
      return "camera";
    }
  });
  const [showSettings, setShowSettings] = useState(false);
  const openerRef = React.useRef<HTMLButtonElement | null>(null);

  // persist scan mode
  React.useEffect(() => {
    try {
      window.localStorage.setItem("scanMode", scanMode);
    } catch {}
  }, [scanMode]);

  return (
    <>
      {/* Settings Button */}
      <Button
        ref={openerRef}
        variant="outline"
        size="sm"
        onClick={() => setShowSettings((v) => !v)}
        className="fixed bottom-4 right-4 p-2 rounded-full shadow-lg bg-white hover:text-hospital-blue-gray hover:bg-hospital-blue/5 z-50"
        aria-haspopup="dialog"
        aria-expanded={showSettings}
        aria-controls="settings-menu"
        aria-label={showSettings ? "Close settings" : "Open settings"}
      >
        <Settings size={20} className="text-hospital-teal cursor-pointer" />
      </Button>

      {/* Settings Popup */}
      <SettingsMenu
        open={showSettings}
        onClose={() => setShowSettings(false)}
        scanMode={scanMode}
        setScanMode={setScanMode}
        openerRef={openerRef}
      />

      {/* Render the selected home screen */}
      {scanMode === "camera" ? <HomeScreen /> : <NusHomeScreen />}
    </>
  );
};

export default HomePage;
