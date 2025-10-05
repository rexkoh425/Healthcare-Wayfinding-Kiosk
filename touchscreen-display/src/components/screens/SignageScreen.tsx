import React, { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Info, Settings } from "lucide-react";
import { DirectionalLayout } from "@/components/ui/directional-layout";
import { Toggle } from "@/components/ui/toggle";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";

type ScanMode = "camera" | "nfc";

interface Stat {
  id: number;
  name: string;
  direction: string;
}

function resolveBackendBase(): string {
  const env = process.env.NEXT_PUBLIC_BACKEND_API_BASE;
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window === "undefined") {
    return "";
  }
  const protocol = window.location.protocol === "https:" ? "https" : "http";
  return `${protocol}://${window.location.hostname}:8000`;
}

const SignageScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const [scanMode, setScanMode] = useState<ScanMode>("camera");
  const [showSettings, setShowSettings] = useState(false);
  const [hourlyStats, setHourlyStats] = useState<Stat[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<Stat[]>([]);

  // keep kiosk idle while on the signage screen
  useEffect(() => {
    send({ type: "action", action: "idle" });
  }, [send]);

  // restore scan mode preference
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const saved = window.localStorage.getItem("scanMode");
    if (saved === "nfc" || saved === "camera") {
      setScanMode(saved);
    }
  }, []);

  // persist scan mode preference
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("scanMode", scanMode);
  }, [scanMode]);

  useEffect(() => {
    let isMounted = true;
    let intervalId: number | undefined;

    async function fetchStats() {
      const base = resolveBackendBase();
      if (!base) {
        return;
      }
      try {
        const [hourlyRes, weeklyRes] = await Promise.all([
          fetch(`${base}/stats/hourly`, { cache: "no-store" }),
          fetch(`${base}/stats/weekly_top4`, { cache: "no-store" }),
        ]);

        if (!hourlyRes.ok || !weeklyRes.ok) {
          throw new Error(`Stats request failed: ${hourlyRes.status}/${weeklyRes.status}`);
        }

        const [hourlyData, weeklyData] = await Promise.all([
          hourlyRes.json(),
          weeklyRes.json(),
        ]);

        if (isMounted) {
          setHourlyStats(Array.isArray(hourlyData) ? hourlyData : []);
          setWeeklyStats(Array.isArray(weeklyData) ? weeklyData : []);
        }
      } catch (error) {
        console.error("Failed to fetch stats", error);
      }
    }

    fetchStats();
    if (typeof window !== "undefined") {
      intervalId = window.setInterval(fetchStats, 1000 * 60 * 60);
    }

    return () => {
      isMounted = false;
      if (typeof window !== "undefined" && intervalId) {
        window.clearInterval(intervalId);
      }
    };
  }, []);

  const fallbackHourly: Stat[] = [
    { id: 1, name: "E2A Studio 3", direction: "up" },
    { id: 2, name: "Innovation and Design Hub", direction: "right" },
    { id: 3, name: "Fab Lab", direction: "left" },
    { id: 4, name: "Community Garden", direction: "straight" },
  ];

  const fallbackWeekly: Stat[] = [
    { id: 1, name: "Techno Edge", direction: "straight" },
    { id: 2, name: "LT7", direction: "left" },
    { id: 3, name: "Starbucks", direction: "straight" },
    { id: 4, name: "Cheers", direction: "down" },
  ];

  const displayHourly = hourlyStats.length === 4 ? hourlyStats : fallbackHourly;
  const displayWeekly = weeklyStats.length === 4 ? weeklyStats : fallbackWeekly;
  const allDestinations = [...displayHourly, ...displayWeekly];

  const handleDestinationClick = () => {
    router.push("/");
  };

  const handleScan = () => {
    router.push(`/${scanMode}`);
  };

  const handleTalk = () => {
    send({ type: "action", action: "talk" });
    router.push("/LLM");
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-hospital-blue-gray mb-2">
            Welcome to Scan and Go
          </h2>
          <div className="flex flex-col md:flex-row items-center justify-center md:space-x-2 space-y-3 md:space-y-0 mb-6">
            <p className="text-hospital-blue-gray/70 text-xl">
              {t("signage.descriptionOne")}
            </p>
            <Info size={32} className="text-hospital-teal" />
            <p className="text-hospital-blue-gray/70 text-xl">
              {t("signage.descriptionTwo")}
            </p>
          </div>

          <DirectionalLayout
            destinations={allDestinations}
            onDestinationClick={handleDestinationClick}
          />
        </div>

        <div className="flex flex-col space-y-4">
          <Button
            onClick={handleScan}
            size="lg"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-6 text-lg kiosk-button"
          >
            {scanMode === "camera" ? t("signage.scanButton") : t("signage.nfc")}
          </Button>

          <Button
            onClick={handleTalk}
            size="lg"
            className="bg-hospital-blue-gray hover:bg-hospital-blue-gray/90 text-white py-6 text-lg kiosk-button"
          >
            {t("signage.talkButton")}
          </Button>
        </div>
      </Card>

      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowSettings((value) => !value)}
        className="fixed bottom-4 right-4 p-2 rounded-full shadow-lg bg-white hover:text-hospital-blue-gray hover:bg-hospital-blue/5"
      >
        <Settings size={20} className="text-hospital-teal" />
      </Button>

      {showSettings && (
        <div className="text-hospital-blue-gray/70 fixed bottom-16 right-4 w-48 bg-white border rounded-lg shadow-lg p-4 z-50">
          <h4 className="font-medium mb-2">Scan Method</h4>
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
      )}
    </div>
  );
};

export default SignageScreen;
