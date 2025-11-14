"use client";

import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useRouter, useSearchParams } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";
import { Hand, RotateCcw } from "lucide-react";

interface InstructionRecord {
  location: string;
  directions: string;
  unit?: string;
  level?: string;
  file_path?: string;
}

const instructionsPath =
  // process.env.NEXT_PUBLIC_INSTRUCTIONS_PATH ?? "/instructions-ah.json";
  // process.env.NEXT_PUBLIC_INSTRUCTIONS_PATH ?? "/instructions-nus.json";
  process.env.NEXT_PUBLIC_INSTRUCTIONS_PATH ?? "/instructions-showcase.json";

const FinalPage: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { send } = useWebSocket();

  const dest = searchParams.get("dest");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [directions, setDirections] = useState<string | null>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hasNavigatedRef = useRef(false);

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
            `Failed to load instructions: ${response.status} ${instructionsPath}`
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
            typeof item?.directions === "string"
        );

        const match = instructions.find(
          (item) => item.location.trim().toLowerCase() === normalized
        );

        if (!match) {
          throw new Error("Destination not found in instructions.");
        }

        const text = match.directions.trim();
        const filePath =
          typeof match.file_path === "string" ? match.file_path.trim() : "";
        if (!filePath) {
          throw new Error("Missing audio file path for destination.");
        }

        if (cancelled) {
          return;
        }

        setDirections(text);
        send({ type: "subtitle", text });

        const resolvedSrc = filePath.startsWith("/")
          ? filePath
          : `/${filePath}`;
        setAudioSrc(resolvedSrc);
      } catch (err) {
        console.error("Failed to load instructions", err);
        if (!cancelled) {
          setError(
            "We could not load the instructions audio. Please ask for assistance."
          );
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

  const navigateHome = useCallback(() => {
    if (hasNavigatedRef.current) {
      return;
    }
    hasNavigatedRef.current = true;
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    router.replace("/");
    router.refresh();
  }, [router, send]);

  const stopAudio = useCallback(() => {
    const current = audioRef.current;
    if (current) {
      current.pause();
      current.src = "";
      audioRef.current = null;
    }
  }, []);

  const startAudio = useCallback(() => {
    if (!audioSrc) {
      return;
    }

    stopAudio();

    const audio = new Audio(audioSrc);
    audioRef.current = audio;

    const handlePlaybackFailure = (err?: unknown) => {
      console.error("Unable to play instructions audio", err);
      stopAudio();
      setError(
        "We could not load the instructions audio. Please ask for assistance."
      );
    };

    audio.onended = () => {
      stopAudio();
      navigateHome();
    };
    audio.onerror = (event) => {
      handlePlaybackFailure(event);
    };

    audio.play().catch((err) => {
      handlePlaybackFailure(err);
    });
  }, [audioSrc, navigateHome, stopAudio]);

  useEffect(() => {
    if (!audioSrc) {
      return undefined;
    }

    startAudio();
    return stopAudio;
  }, [audioSrc, startAudio, stopAudio]);

  useEffect(() => {
    return stopAudio;
  }, [stopAudio]);

  const handleReplay = useCallback(() => {
    startAudio();
  }, [startAudio]);

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
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card space-y-6">
          <p className="text-3xl font-bold text-hospital-blue-gray">{error}</p>
          <Button
            onClick={navigateHome}
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white"
          >
            Back
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card space-y-6">
        <div className="flex flex-col items-center space-y-4">
          <div className="bg-hospital-teal/10 rounded-full p-6">
            <Hand className="w-16 h-16 text-hospital-teal rotate-90" />
          </div>
          <h1 className="text-3xl font-bold text-hospital-blue-gray">
            Please pay attention to the hologram.
          </h1>
          <p className="text-2xl text-hospital-blue-gray/80">
            Your directions are on the way
            {destinationLabel ? ` to ${destinationLabel}` : ""}.
          </p>
          <Button
            onClick={handleReplay}
            variant="outline"
            disabled={!audioSrc}
            className="text-xl px-8 py-6 flex items-center gap-2"
          >
            <RotateCcw className="h-6 w-6" />
            Replay directions audio
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default FinalPage;
