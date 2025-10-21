"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import useWebSocket from "@/lib/useWebSocket";
import { Mic, Volume2, Loader2 } from "lucide-react";

const SESSION_ID = "kiosk-touchscreen";

type Status = "idle" | "recording" | "processing" | "playing";

function resolveChatBase(): string {
  const env = process.env.NEXT_PUBLIC_CHATBOT_API_BASE;
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window === "undefined") {
    return "";
  }
  const protocol = window.location.protocol === "https:" ? "https" : "http";
  return `${protocol}://${window.location.hostname}:8001`;
}

interface LLMPayload {
  response_text?: string | null;
  locations?: unknown;
  intent?: string | null;
}

interface TalkResponse {
  transcript?: string | null;
  llm?: LLMPayload | null;
  audio_wav_b64?: string | null;
  [key: string]: unknown;
}

const ChatScreen: React.FC = () => {
  const router = useRouter();
  const { send } = useWebSocket();

  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    send({ type: "action", action: "talk" });
    return () => {
      send({ type: "action", action: "hear" });
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [send]);

  const apiBase = resolveChatBase();

  const isBusy = status === "processing" || status === "playing";

  const statusConfig = {
    idle: {
      label: "Hold to Talk",
      subtitle: "Press and hold the button below to ask your question",
      bgColor: "bg-gradient-to-br from-hospital-teal to-hospital-blue",
      borderColor: "border-hospital-teal",
      icon: Mic,
      iconColor: "text-white",
      pulseClass: "",
    },
    recording: {
      label: "Listening...",
      subtitle: "Release when you're done speaking",
      bgColor: "bg-gradient-to-br from-red-500 to-red-600",
      borderColor: "border-red-400",
      icon: Mic,
      iconColor: "text-white",
      pulseClass: "animate-pulse",
    },
    processing: {
      label: "Processing Your Question",
      subtitle: "Please wait while I think...",
      bgColor: "bg-gradient-to-br from-purple-700 to-purple-900",
      borderColor: "border-purple-400",
      icon: Loader2,
      iconColor: "text-white",
      pulseClass: "animate-spin",
    },
    playing: {
      label: "Playing Response",
      subtitle: "Listen carefully to the answer",
      bgColor: "bg-gradient-to-br from-green-500 to-green-600",
      borderColor: "border-green-400",
      icon: Volume2,
      iconColor: "text-white",
      pulseClass: "animate-pulse",
    },
  };

  const currentConfig = statusConfig[status];
  const Icon = currentConfig.icon;

  const cleanupStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    mediaRecorderRef.current = null;
    chunksRef.current = [];
  };

  function getErrorMessage(err: unknown, fallback = "Unknown error"): string {
    if (!err) return fallback;
    if (typeof err === "string") return err;
    if (typeof err === "object" && "message" in err) {
      const msg = (err as { message?: unknown }).message;
      if (typeof msg === "string") return msg;
    }
    return fallback;
  }

  const startRecording = async () => {
    if (status !== "idle" || isBusy) {
      return;
    }
    try {
      setError(null);
      setTranscript(null);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];
      streamRef.current = stream;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        setStatus("processing");
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        cleanupStream();

        const formData = new FormData();
        formData.append("audio", blob, "speech.webm");
        formData.append("session_id", SESSION_ID);
        formData.append("return_mode", "json");
        formData.append("language", "en");

        try {
          const response = await fetch(`${apiBase}/talk-voice`, {
            method: "POST",
            body: formData,
          });
          if (!response.ok) {
            throw new Error(`Backend error: ${response.status}`);
          }

          const raw = await response.text();
          let payload: TalkResponse | null = null;
          try {
            const parsed = JSON.parse(raw);
            if (typeof parsed === "object" && parsed !== null) {
              payload = parsed as TalkResponse;
            } else {
              throw new Error("Parsed payload is not an object");
            }
          } catch {
            throw new Error(`Invalid JSON payload: ${raw.slice(0, 200)}`);
          }

          send({ type: "action", action: "hear" });

          setTranscript(
            typeof payload?.transcript === "string" ? payload.transcript : null
          );

          // Send transcript to server for hologram subtitles
          if (
            typeof payload?.llm?.response_text === "string" &&
            payload.llm.response_text.trim().length > 0
          ) {
            send({ type: "subtitle", text: payload.llm.response_text.trim() });
          }

          const locations: string[] = Array.isArray(payload?.llm?.locations)
            ? (payload!.llm!.locations as unknown[]).filter(
                (item: unknown): item is string =>
                  typeof item === "string" && item.trim().length > 0
              )
            : [];
          const uniqueLocations = Array.from(
            new Set(locations.map((item) => item.trim()))
          ).slice(0, 3);
          const shouldNavigate =
            payload?.llm?.intent === "route" && uniqueLocations.length > 0;

          const b64 = payload?.audio_wav_b64;
          if (typeof b64 !== "string" || b64.length === 0) {
            throw new Error("Missing audio payload");
          }

          const cleaned = b64.replace(/\s+/g, "");
          const binary = window.atob(cleaned);
          const buffer = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i += 1) {
            buffer[i] = binary.charCodeAt(i);
          }
          const audioBlob = new Blob([buffer], { type: "audio/wav" });
          const audioUrl = URL.createObjectURL(audioBlob);
          const audio = new Audio(audioUrl);

          setStatus("playing");
          audio.onended = () => {
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
            if (shouldNavigate) {
              const params = new URLSearchParams({
                locations: JSON.stringify(uniqueLocations),
              });
              router.push(`/destination?${params.toString()}`);
            }
          };
          audio.onerror = () => {
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
            setError("Audio playback failed");
            if (shouldNavigate) {
              const params = new URLSearchParams({
                locations: JSON.stringify(uniqueLocations),
              });
              router.push(`/destination?${params.toString()}`);
            }
          };

          try {
            await audio.play();
          } catch (playError) {
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
            setError(
              getErrorMessage(playError, "Playback blocked by the browser")
            );
            if (shouldNavigate) {
              const params = new URLSearchParams({
                locations: JSON.stringify(uniqueLocations),
              });
              router.push(`/destination?${params.toString()}`);
            }
          }
        } catch (requestError) {
          console.error("Chat screen error", requestError);
          setStatus("idle");
          setError(
            getErrorMessage(
              requestError,
              "Failed to contact the chatbot service"
            )
          );
        }
      };

      recorder.start();
      setStatus("recording");
    } catch (mediaError) {
      cleanupStream();
      setStatus("idle");
      setError(getErrorMessage(mediaError, "Microphone access denied"));
    }
  };

  const stopRecording = () => {
    if (status === "recording" && mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
    }
  };

  const handleBack = () => {
    send({ type: "action", action: "idle" });
    router.push("/");
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-2xl p-8 shadow-2xl border-2 border-hospital-blue/20 bg-white/95 backdrop-blur">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-hospital-blue-gray mb-2">
            Wayfinding Assistant
          </h1>
          <p className="text-lg text-hospital-blue-gray/70">
            Ask me for directions to navigate the hospital
          </p>
        </div>

        {/* Status Indicator */}
        <div className="mb-8 text-center">
          <div
            className={`inline-flex items-center gap-3 px-6 py-3 rounded-full ${currentConfig.bgColor} shadow-lg transition-all duration-300`}
          >
            <Icon
              aria-hidden="true"
              focusable="false"
              className={`w-6 h-6 ${currentConfig.iconColor} ${currentConfig.pulseClass}`}
            />
            <span className="text-white font-semibold text-lg">
              {currentConfig.label}
            </span>
          </div>
          <p className="text-hospital-blue-gray/60 mt-3 text-base">
            {currentConfig.subtitle}
          </p>
        </div>

        {/* Main Talk Button */}
        <div className="flex flex-col items-center gap-6">
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              startRecording();
            }}
            onMouseUp={(e) => {
              e.preventDefault();
              stopRecording();
            }}
            onMouseLeave={() => {
              if (status === "recording") stopRecording();
            }}
            onTouchStart={(e) => {
              e.preventDefault();
              e.stopPropagation();
              startRecording();
            }}
            onTouchEnd={(e) => {
              e.preventDefault();
              e.stopPropagation();
              stopRecording();
            }}
            onTouchCancel={(e) => {
              e.preventDefault();
              e.stopPropagation();
              stopRecording();
            }}
            // prevent the browser’s “right-click” or “long-press” context menu
            onContextMenu={(e) => e.preventDefault()}
            // prevent long-press gesture detection on touch devices
            style={{ WebkitTouchCallout: "none", userSelect: "none" }}
            disabled={isBusy}
            className={`relative group transition-all duration-300 ${
              isBusy
                ? "opacity-50 cursor-not-allowed"
                : "hover:scale-105 active:scale-95"
            }`}
          >
            {/* Outer Ring */}
            <div
              className={`absolute inset-0 rounded-full ${currentConfig.borderColor} border-4 ${
                status === "recording" ? "animate-ping opacity-75" : ""
              }`}
            />

            {/* Button Circle */}
            <div
              className={`relative w-48 h-48 rounded-full ${currentConfig.bgColor} shadow-2xl flex items-center justify-center border-4 ${currentConfig.borderColor} transition-all duration-300`}
            >
              <Icon
                aria-hidden="true"
                focusable="false"
                className={`w-24 h-24 ${currentConfig.iconColor} ${currentConfig.pulseClass}`}
              />
            </div>

            {/* Ripple Effect on Recording */}
            {status === "recording" && (
              <>
                <div className="absolute inset-0 rounded-full bg-red-400 animate-ping opacity-25" />
                <div
                  className="absolute inset-0 rounded-full bg-red-400 animate-pulse opacity-25"
                  style={{ animationDelay: "0.3s" }}
                />
              </>
            )}
          </button>

          {/* Instruction Text */}
          <p className="text-hospital-blue-gray/80 text-center text-lg font-medium">
            {status === "idle"
              ? "Press & Hold to Speak"
              : status === "recording"
                ? "Release to Send"
                : ""}
          </p>
        </div>

        {/* Transcript Display */}
        {transcript && (
          <div className="mt-8 p-6 bg-hospital-blue/5 rounded-xl border-2 border-hospital-blue/20 animate-fade-in">
            <p className="text-sm font-semibold text-hospital-blue-gray/60 mb-2">
              You asked:
            </p>
            <p className="text-lg text-hospital-blue-gray italic">
              &quot;{transcript}&quot;
            </p>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="mt-8 p-6 bg-red-50 rounded-xl border-2 border-red-200 animate-fade-in">
            <p className="text-sm font-semibold text-red-600 mb-2">Error:</p>
            <p className="text-base text-red-700">{error}</p>
          </div>
        )}

        {/* Audio Waveform Visualisation (only during playing) */}
        {status === "playing" && (
          <div className="mt-8 flex justify-center items-center gap-2 h-16">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="w-2 bg-green-500 rounded-full animate-pulse"
                style={{
                  height: `${30 + Math.random() * 40}%`,
                  animationDelay: `${i * 0.1}s`,
                  animationDuration: "0.6s",
                }}
              />
            ))}
          </div>
        )}

        <div className="flex justify-between">
          <Button
            variant="ghost"
            onClick={handleBack}
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
          >
            Back
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default ChatScreen;
