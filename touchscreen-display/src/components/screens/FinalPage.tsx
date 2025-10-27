'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";
import Image from "next/image";

interface InstructionRecord {
  location: string;
  directions: string;
  unit?: string;
  level?: string;
  file_path?: string;
}

const RFID_POLL_INTERVAL_MS = 1500;
const instructionsPath =
  process.env.NEXT_PUBLIC_INSTRUCTIONS_PATH ?? "/instructions-nus.json";

function resolveRfidReaderUrl(): string {
  const env = process.env.NEXT_PUBLIC_RFID_URL;
  if (env) {
    return env.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    return `${protocol}://${window.location.hostname}:5000`;
  }

  return "";
}

function isTagRemoved(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") {
    return false;
  }
  const record = payload as Record<string, unknown>;
  if (typeof record.removed === "boolean") {
    return record.removed;
  }
  const epc = record.epc;
  if (typeof epc === "string") {
    return epc.trim().length === 0;
  }
  return true;
}

const FinalPage: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { send } = useWebSocket();
  const { t } = useTranslation();

  const dest = searchParams.get("dest");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [directions, setDirections] = useState<string | null>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioFinished, setAudioFinished] = useState(false);
  const [tagRemoved, setTagRemoved] = useState(false);
  const [autoNavigated, setAutoNavigated] = useState(false);

  const destinationLabel = useMemo(() => dest?.trim() ?? "", [dest]);

  useEffect(() => {
    let cancelled = false;

    const fetchInstructions = async () => {
      if (!destinationLabel) {
        setError("Missing destination.");
        setLoading(false);
        return;
      }

      try {
        const response = await fetch(instructionsPath, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(
            `Failed to load instructions: ${response.status} ${instructionsPath}`,
          );
        }

        const payload: unknown = await response.json();
        if (!Array.isArray(payload)) {
          throw new Error("Invalid instructions payload");
        }

        const normalized = destinationLabel.toLowerCase();
        const instructions = payload.filter(
          (item): item is InstructionRecord =>
            typeof item?.location === "string" &&
            typeof item?.directions === "string",
        );

        const match = instructions.find(
          (item) => item.location.trim().toLowerCase() === normalized,
        );

        if (!match) {
          throw new Error("Destination not found in instructions.");
        }

        const text = match.directions.trim();
        const filePath = typeof match.file_path === "string" ? match.file_path.trim() : "";
        if (!filePath) {
          throw new Error("Missing audio file path for destination.");
        }

        if (cancelled) {
          return;
        }

        setDirections(text);
        send({ type: "subtitle", text });

        const resolvedSrc = filePath.startsWith("/") ? filePath : `/${filePath}`;
        setAudioSrc(resolvedSrc);
        setAudioFinished(false);
      } catch (err) {
        console.error("Failed to load instructions", err);
        if (!cancelled) {
          setError("We could not load the instructions audio. Please ask for assistance.");
          setAudioFinished(true);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchInstructions();

    return () => {
      cancelled = true;
    };
  }, [destinationLabel, send]);

  useEffect(() => {
    if (!audioSrc) {
      return;
    }

    const audio = new Audio(audioSrc);
    audioRef.current = audio;

    const cleanup = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      audio.pause();
      audio.src = "";
    };

    audio.onended = () => {
      setAudioFinished(true);
      cleanup();
    };
    audio.onerror = () => {
      setAudioFinished(true);
      cleanup();
    };

    audio.play().catch((err) => {
      console.error("Unable to play instructions audio", err);
      setAudioFinished(true);
      cleanup();
    });

    return cleanup;
  }, [audioSrc]);

  useEffect(() => {
    return () => {
      const current = audioRef.current;
      if (current) {
        current.pause();
        current.src = "";
        audioRef.current = null;
      }
    };
  }, []);

  const handleRepeat = useCallback(() => {
    if (!audioSrc || !directions) {
      return;
    }

    send({ type: "subtitle", text: directions });

    const audio = new Audio(audioSrc);
    audioRef.current = audio;
    setAudioFinished(false);

    const cleanup = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      audio.pause();
      audio.src = "";
    };

    audio.onended = () => {
      setAudioFinished(true);
      cleanup();
    };
    audio.onerror = () => {
      setAudioFinished(true);
      cleanup();
    };
    audio.play().catch((err) => {
      console.error("Unable to replay instructions audio", err);
      setAudioFinished(true);
      cleanup();
    });
  }, [audioSrc, directions, send]);

  const navigateHome = useCallback(() => {
    setAutoNavigated(true);
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    router.replace("/");
    router.refresh();
  }, [router, send]);

  useEffect(() => {
    if (tagRemoved || autoNavigated) {
      return;
    }

    const base = resolveRfidReaderUrl();
    if (!base) {
      console.warn("RFID reader URL unavailable; cannot monitor tag removal.");
      return undefined;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const response = await fetch(`${base}/tagRemoved`, { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        if (!cancelled && isTagRemoved(payload)) {
          setTagRemoved(true);
        }
      } catch (err) {
        console.warn("Failed to poll tag removal", err);
      }
    };

    poll();
    const intervalId = window.setInterval(poll, RFID_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [tagRemoved, autoNavigated]);

  useEffect(() => {
    if (audioFinished && tagRemoved && !autoNavigated) {
      navigateHome();
    }
  }, [audioFinished, tagRemoved, autoNavigated, navigateHome]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
          <p className="text-3xl font-bold text-hospital-blue-gray">
            Preparing your instructions...
          </p>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
          <p className="text-3xl font-bold text-hospital-blue-gray mb-4">{error}</p>
          <Button
            onClick={navigateHome}
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white"
          >
            {t("common.back")}
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        <div className="space-y-4">
          <p className="text-3xl font-bold text-hospital-blue-gray">
            Please collect your sticker.
          </p>
          <p className="text-3xl font-bold text-hospital-blue-gray">
            Stick it vertically on your pants before proceeding to {destinationLabel}.
          </p>
        </div>

        <div className="flex items-center justify-center w-80 p-4 rounded-xl mx-auto">
          <Image
            src="/rfid/wearGuide.jpg"
            alt="RFID Wear Guide"
            width={300}
            height={200}
            className="rounded-lg object-contain"
          />
        </div>

        <div className="flex justify-between mt-6">
          <Button
            onClick={handleRepeat}
            variant="ghost"
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10 text-2xl"
            disabled={!audioSrc}
          >
            🔊 Repeat Instructions
          </Button>
          <Button
            onClick={navigateHome}
            variant="ghost"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-8 text-2xl kiosk-button"
          >
            Collected
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default FinalPage;
