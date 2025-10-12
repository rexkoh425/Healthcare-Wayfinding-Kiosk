"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import useWebSocket from "@/lib/useWebSocket";

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

const ChatScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
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

  const label = (() => {
    switch (status) {
      case "recording":
        return "Release to send";
      case "processing":
        return "Processing...";
      case "playing":
        return "Playing response...";
      default:
        return "Hold to talk";
    }
  })();

  const cleanupStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    mediaRecorderRef.current = null;
    chunksRef.current = [];
  };

  const startRecording = async () => {
    if (status !== "idle" || isBusy) {
      return;
    }
    try {
      setError(null);
      setTranscript(null);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
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

        try {
          const response = await fetch(`${apiBase}/talk-voice`, {
            method: "POST",
            body: formData,
          });
          if (!response.ok) {
            throw new Error(`Backend error: ${response.status}`);
          }

          const raw = await response.text();
          let payload: any;
          try {
            payload = JSON.parse(raw);
          } catch (parseError) {
            throw new Error(`Invalid JSON payload: ${raw.slice(0, 200)}`);
          }

          send({ type: "action", action: "hear" });
          
          setTranscript(typeof payload?.transcript === "string" ? payload.transcript : null);

          // Send transcript to server for hologram subtitles
          if (typeof payload?.llm.response_text === "string" && payload.llm.response_text.trim().length > 0) {
            send({ type: "subtitle", text: payload.llm.response_text.trim() });
          }

          const locations: string[] = Array.isArray(payload?.llm?.locations)
            ? payload.llm.locations.filter((item: unknown): item is string => typeof item === "string" && item.trim().length > 0)
            : [];
          const uniqueLocations = Array.from(new Set(locations.map((item) => item.trim()))).slice(0, 3);
          const shouldNavigate = payload?.llm?.intent === "route" && uniqueLocations.length > 0;

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
              const params = new URLSearchParams({ locations: JSON.stringify(uniqueLocations) });
              router.push(`/destination?${params.toString()}`);
            }
          };
          audio.onerror = () => {
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
            setError("Audio playback failed");
            if (shouldNavigate) {
              const params = new URLSearchParams({ locations: JSON.stringify(uniqueLocations) });
              router.push(`/destination?${params.toString()}`);
            }
          };

          try {
            await audio.play();
          } catch (playError: any) {
            URL.revokeObjectURL(audioUrl);
            setStatus("idle");
            setError(playError?.message ?? "Playback blocked by the browser");
            if (shouldNavigate) {
              const params = new URLSearchParams({ locations: JSON.stringify(uniqueLocations) });
              router.push(`/destination?${params.toString()}`);
            }
          }
        } catch (requestError: any) {
          console.error("Chat screen error", requestError);
          setStatus("idle");
          setError(requestError?.message ?? "Failed to contact the chatbot service");
        }
      };

      recorder.start();
      setStatus("recording");
    } catch (mediaError: any) {
      cleanupStream();
      setStatus("idle");
      setError(mediaError?.message ?? "Microphone access denied");
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
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 bg-[#0b1020] px-4">
      <div className="flex flex-col items-center gap-4">
        <button
          type="button"
          onMouseDown={startRecording}
          onMouseUp={stopRecording}
          onMouseLeave={stopRecording}
          onTouchStart={(event) => {
            event.preventDefault();
            startRecording();
          }}
          onTouchEnd={(event) => {
            event.preventDefault();
            stopRecording();
          }}
          className={`text-lg font-medium text-white px-10 py-6 rounded-xl border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-hospital-teal ${
            status === "recording"
              ? "bg-[#882f2f] border-[#2a3a6b]"
              : status === "processing"
                ? "bg-[#5b3a88] border-[#2a3a6b]"
                : status === "playing"
                  ? "bg-[#2a6b3a] border-[#2a3a6b]"
                  : "bg-[#1b2a57] border-[#2a3a6b] hover:bg-[#24346f]"
          } ${isBusy ? "opacity-80" : ""}`}
          disabled={isBusy}
        >
          {label}
        </button>
        {transcript && (
          <p className="text-sky-200 text-center max-w-xs">
            You said: {transcript}
          </p>
        )}
        {error && (
          <p className="text-red-200 text-center max-w-xs">{error}</p>
        )}
      </div>
      <Button variant="secondary" onClick={handleBack} className="bg-white/10 text-white hover:bg-white/20">
        {t("common.back")}
      </Button>
    </main>
  );
};

export default ChatScreen;
