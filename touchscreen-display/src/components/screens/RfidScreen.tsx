import React, { useEffect, useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";
import { MedicalIcon, MedicalIconType } from "@/components/ui/MedicalIcons";
import Image from "next/image";

const VIDEO_PATH = "/rfid/collectionGuide.mp4";
const BBOX_POLL_INTERVAL_MS = 500;

function resolveBackendBase(): string {
  // Optional: use environment variable first
  const env = process.env.NEXT_PUBLIC_BASE_URL;
  if (env) return env.replace(/\/$/, "");

  // Fallback: browser environment
  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    const host = window.location.hostname;
    return `${protocol}://${host}`;
  }

  // Server-side fallback
  return "";
}

function resolveRfidReaderUrl(): string {
  const env = process.env.NEXT_PUBLIC_RFID_URL;
  if (env) return env;

  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    const host = window.location.hostname;
    return `${protocol}://${host}:5000`;
  }

  return "";
}

function resolveTtsBase(): string {
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

function resolveOcrBase(): string {
  const env = process.env.NEXT_PUBLIC_OCR_API_BASE;
  if (env) {
    return env.replace(/\/$/, "");
  }
  if (typeof window === "undefined") {
    return "";
  }
  const protocol = window.location.protocol === "https:" ? "https" : "http";
  return `${protocol}://${window.location.hostname}:9000`;
}

interface InstructionRecord {
  location: string;
  directions: string;
  unit?: string;
  level?: string;
}

const RfidScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
  const { send } = useWebSocket();
  const searchParams = useSearchParams();

  const [dispensing, setDispensing] = useState(true);
  const [icon, setIcon] = useState<string | null>(null);
  const [unitNumber, setUnitNumber] = useState<string | null>(null);
  const [lastDirections, setLastDirections] = useState<string | null>(null);
  const [lastAudioB64, setLastAudioB64] = useState<string | null>(null);
  const audioRef = useRef<{ audio: HTMLAudioElement; url: string } | null>(
    null
  );
  const [streamUrl, setStreamUrl] = useState<string>("");
  const ocrBaseRef = useRef<string>("");
  const detectionSeenRef = useRef<boolean>(false);
  const collectedOnceRef = useRef<boolean>(false);
  const streamImgRef = useRef<HTMLImageElement | null>(null);

  const dest = searchParams.get("dest");
  const baseUrl = resolveBackendBase();

  useEffect(() => {
    if (dispensing) {
      detectionSeenRef.current = false;
      collectedOnceRef.current = false;
    }
  }, [dispensing]);

  // Fetch destination info (icon, unit number)
  useEffect(() => {
    if (!dest) return;
    const fetchDestinationInfo = async () => {
      try {
        const res = await fetch(
          `${baseUrl}/destinations/?name=${encodeURIComponent(dest)}`
        );
        if (!res.ok) throw new Error("Failed to fetch destination info");
        const data = await res.json();
        setIcon(data.icon || null);
        setUnitNumber(data.unitNumber || null);
      } catch (err) {
        console.warn("Could not fetch destination info", err);
        setIcon(null);
        setUnitNumber(null);
      }
    };
    fetchDestinationInfo();
  }, [dest]);

  // Prefetch instructions and audio for later playback
  useEffect(() => {
    if (!dest) return;
    let isCancelled = false;

    const fetchInstructions = async () => {
      try {
        const response = await fetch("/instructions.json", {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`Failed to load instructions: ${response.status}`);
        }

        const payload = await response.json();
        if (!Array.isArray(payload)) {
          throw new Error("Invalid instructions payload");
        }

        const instructions = payload.filter(
          (item: any): item is InstructionRecord =>
            typeof item?.location === "string" &&
            typeof item?.directions === "string"
        );

        const normalized = dest.trim().toLowerCase();
        const match = instructions.find(
          (item) =>
            item.location.trim().toLowerCase() === normalized &&
            item.directions.trim().length > 0
        );

        if (!match) {
          console.warn("No matching instructions found for destination:", dest);
          if (!isCancelled) {
            setLastDirections(null);
            setLastAudioB64(null);
          }
          return;
        }
        if (isCancelled) return;

        const directions: string = match.directions.trim();
        setLastDirections(directions);

        const apiBase = resolveTtsBase();
        if (!apiBase) {
          console.warn("Unable to resolve TTS base URL");
          setLastAudioB64(null);
          return;
        }

        const ttsResponse = await fetch(`${apiBase}/speak`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            text: directions,
            return_mode: "json",
          }),
        });

        if (!ttsResponse.ok) {
          throw new Error(`TTS request failed: ${ttsResponse.status}`);
        }

        const ttsPayload = await ttsResponse.json();
        const b64 =
          typeof ttsPayload?.audio_wav_b64 === "string"
            ? ttsPayload.audio_wav_b64.replace(/\s+/g, "")
            : "";
        if (!b64) {
          throw new Error("Missing audio payload from TTS response");
        }
        if (isCancelled) return;
        setLastAudioB64(b64);
      } catch (error) {
        if (!isCancelled) {
          setLastDirections(null);
          setLastAudioB64(null);
          console.error("Failed to prepare instructions audio", error);
        }
      }
    };

    fetchInstructions();

    return () => {
      isCancelled = true;
    };
  }, [dest]);

  useEffect(() => {
    if (!dest) return;

    async function handleTags() {
      try {
        const rfidUrl = resolveRfidReaderUrl();
        if (!rfidUrl) throw new Error("RFID reader URL is not configured.");

        console.log("Sending destination confirmation to RFID:", dest);
        const confirmRes = await fetch(rfidUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            action: "destinationConfirmation",
            destination: dest,
          }),
        });
        if (!confirmRes.ok) {
          throw new Error(
            `Failed to confirm destination with RFID: ${confirmRes.status}`
          );
        }

        console.log("Requesting RFID reader at:", rfidUrl);
        const espRes = await fetch(rfidUrl);
        if (!espRes.ok) {
          throw new Error(`HTTP error from rfid! status: ${espRes.status}`);
        }

        const tagData = await espRes.json();
        console.log("Received from RFID Reader:", tagData);

        const usersUrl = `${baseUrl}/users/`;
        console.log("Posting to Users", usersUrl);
        const postRes = await fetch(usersUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            rfidTagId: tagData.epc,
            destination: dest,
          }),
        });

        if (postRes.ok) {
          const postResult = await postRes.json();
          console.log("POST result:", postResult);
          setDispensing(false);
        } else if (postRes.status === 409) {
          setDispensing(false);
        } else {
          throw new Error(
            `HTTP error from users api! status: ${postRes.status}`
          );
        }
      } catch (err) {
        console.error("RFID handling error:", err);
      }
    }

    handleTags();
  }, [baseUrl, dest]);

  // useEffect(() => {
  //   // Only start the timer when the collection screen is visible (`dispensing` is false)
  //   if (!dispensing) {
  //     const inactivityTimer = setTimeout(() => {
  //       console.log("Timeout: User collect sticker. Navigating home.");
  //       // Navigate back to the main page after 15 seconds
  //       send({ type: "action", action: "idle" });
  //       router.push("/");
  //     }, 15000); // 15000 milliseconds = 15 seconds

  //     //Cleanup function to clear timer
  //     return () => {
  //       clearTimeout(inactivityTimer);
  //     };
  //   }
  // }, [dispensing, router]);

  const playTts = useCallback(
    async (text: string, cachedAudio?: string | null) => {
      const trimmed = text?.trim();
      if (!trimmed || typeof window === "undefined") {
        return;
      }

      const existing = audioRef.current;
      if (existing) {
        existing.audio.pause();
        existing.audio.src = "";
        URL.revokeObjectURL(existing.url);
        audioRef.current = null;
      }

      let b64 =
        cachedAudio && cachedAudio.trim().length > 0
          ? cachedAudio.replace(/\s+/g, "")
          : null;

      if (!b64) {
        const ttsBase = resolveTtsBase();
        if (!ttsBase) {
          console.warn("Unable to resolve TTS base URL for playback");
          return;
        }
        try {
          const response = await fetch(`${ttsBase}/speak`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              text: trimmed,
              return_mode: "json",
            }),
          });
          if (!response.ok) {
            throw new Error(`TTS request failed: ${response.status}`);
          }
          const payload = await response.json();
          b64 =
            typeof payload?.audio_wav_b64 === "string"
              ? payload.audio_wav_b64.replace(/\s+/g, "")
              : "";
          if (!b64) {
            throw new Error("Missing audio payload from TTS response");
          }
          setLastAudioB64(b64);
        } catch (error) {
          console.warn("Failed to fetch TTS audio", error);
          return;
        }
      }

      if (!b64) {
        return;
      }

      try {
        const binary = window.atob(b64);
        const buffer = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) {
          buffer[i] = binary.charCodeAt(i);
        }
        const blob = new Blob([buffer], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);

        await new Promise<void>((resolvePromise, rejectPromise) => {
          const audio = new Audio(url);
          audioRef.current = { audio, url };

          const cleanup = () => {
            if (audioRef.current?.audio === audio) {
              audioRef.current = null;
            }
            URL.revokeObjectURL(url);
          };

          audio.onended = () => {
            cleanup();
            resolvePromise();
          };
          audio.onerror = () => {
            cleanup();
            rejectPromise(new Error("Audio playback failed"));
          };

          const playAttempt = audio.play();
          if (playAttempt) {
            playAttempt.catch((err) => {
              cleanup();
              rejectPromise(err);
            });
          }
        }).catch((err) => {
          console.warn("TTS audio playback interrupted", err);
        });
      } catch (error) {
        console.warn("Failed to play TTS audio", error);
      }
    },
    []
  );

  const handleCollected = useCallback(async () => {
    if (collectedOnceRef.current) {
      return;
    }
    collectedOnceRef.current = true;
    setStreamUrl("");
    const base = ocrBaseRef.current;
    if (base) {
      fetch(`${base}/detector_mode`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ mode: "default" }),
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
        })
        .catch((error) => {
          console.warn("Failed to reset detector mode after collection", error);
        });
      ocrBaseRef.current = "";
    }

    const instructionsText = lastDirections?.trim();

    if (instructionsText) {
      try {
        send({ type: "action", action: "hear" });
      } catch (err) {
        console.warn("Failed to send hear action", err);
      }
      try {
        send({ type: "subtitle", text: instructionsText });
      } catch (err) {
        console.warn("Failed to send instructions subtitle", err);
      }
      await playTts(instructionsText, lastAudioB64);
    } else {
      const fallback = t("rfid.stickerCollectedFallback", {
        defaultValue: "Sticker collected. Thank you.",
      });
      if (fallback) {
        try {
          send({ type: "subtitle", text: fallback });
        } catch (err) {
          console.warn("Failed to send fallback subtitle", err);
        }
        await playTts(fallback);
      }
    }

    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    router.replace("/");
    router.refresh();
  }, [lastAudioB64, lastDirections, playTts, router, send, setStreamUrl, t]);

  useEffect(() => {
    if (dispensing) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }

    const ocrBase = resolveOcrBase();
    if (!ocrBase) {
      console.warn("OCR service base URL unavailable; skipping sticker verification.");
      return;
    }

    ocrBaseRef.current = ocrBase;
    detectionSeenRef.current = false;
    const streamEndpoint = `${ocrBase}/stream.mjpg`;

    const setDetectorMode = async (mode: "default" | "sticker") => {
      try {
        const response = await fetch(`${ocrBase}/detector_mode`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ mode }),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
      } catch (error) {
        console.warn(`Failed to switch detector mode to ${mode}`, error);
      }
    };

    void setDetectorMode("sticker");
    setStreamUrl(streamEndpoint);

    let cancelled = false;
    let inFlight = false;
    const controller = new AbortController();
    let intervalId: number | null = null;

    const poll = async () => {
      if (cancelled || collectedOnceRef.current || inFlight) {
        return;
      }
      inFlight = true;
      try {
        const response = await fetch(`${ocrBase}/bbox_status`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        const detected = Boolean(payload?.detected);
        if (detected) {
          detectionSeenRef.current = true;
        } else if (detectionSeenRef.current) {
          handleCollected().catch((error) => {
            console.warn("Auto collected handler failed", error);
          });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          console.warn("Failed to poll sticker detection status", error);
        }
      } finally {
        inFlight = false;
      }
    };

    poll();
    intervalId = window.setInterval(poll, BBOX_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
      void setDetectorMode("default");
      ocrBaseRef.current = "";
      const imgEl = streamImgRef.current;
      if (imgEl) {
        imgEl.src = "";
        imgEl.removeAttribute("src");
      }
      setStreamUrl("");
    };
  }, [dispensing, handleCollected]);

  // Repeat handler
  const handleRepeat = useCallback(() => {
    if (!lastDirections) return;

    try {
      send({ type: "subtitle", text: lastDirections });
    } catch (err) {
      console.warn("Failed to resend subtitle", err);
    }
    void playTts(lastDirections, lastAudioB64);
  }, [lastDirections, lastAudioB64, playTts, send]);

  const backgroundStreamElement = streamUrl ? (
    <img
      ref={streamImgRef}
      src={streamUrl}
      alt=""
      className="hidden"
      aria-hidden="true"
    />
  ) : null;

  if (dispensing) {
    return (
      <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
        {backgroundStreamElement}
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
          {/* Header Section */}
          <div className="mb-12">
            <div className="inline-flex items-center justify-center w-20 h-20 mb-6 bg-hospital-teal/10 rounded-full animate-pulse-dot">
              <div className="w-10 h-10 bg-hospital-teal rounded-full"></div>
            </div>

            <h1 className="text-5xl font-bold text-hospital-blue-gray mb-4">
              Dispensing Sticker...
            </h1>

            <div className="inline-flex items-center px-8 py-4 bg-hospital-blue/10 rounded-xl gap-8">
              {/* Destination Name */}
              <p className="text-4xl font-semibold text-hospital-teal">
                {dest}
              </p>
              {/* Medical Icon and Unit Number */}
              <div className="flex flex-col items-center justify-center">
                {icon && (
                  <MedicalIcon
                    type={icon as MedicalIconType}
                    className="w-16 h-16 mb-2"
                  />
                )}
                {unitNumber && (
                  <div className="text-2xl font-semibold text-hospital-blue-gray mb-2">
                    {unitNumber}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Loading Animation */}
          <div className="flex items-center justify-center gap-3 mb-12">
            {[0, 0.2, 0.4].map((delay) => (
              <div
                key={delay}
                className="w-3 h-3 bg-hospital-teal rounded-full animate-pulse-dot"
                style={{ animationDelay: `${delay}s` }}
              ></div>
            ))}
          </div>

          <p className="text-xl text-hospital-blue-gray/60 mb-12">
            Please wait while we prepare your wayfinding sticker
          </p>

          <div className="flex justify-between">
            <Button
              onClick={handleRepeat}
              variant="ghost"
              className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
              disabled={!lastDirections}
            >
              🔊 Repeat Instructions
            </Button>
          </div>
        </Card>
      </div>
    );
  } else {
    return (
      <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
        {backgroundStreamElement}
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
          <div className="mb-8">
            <div className="inline-flex items-center justify-center w-20 h-20 mb-6 bg-green-500/10 rounded-full">
              <svg
                className="w-10 h-10 text-green-500"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={3}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>

            <h1 className="text-3xl font-bold text-hospital-blue-gray mb-4">
              Sticker Ready!
            </h1>
            <p className="text-2xl text-hospital-blue-gray/80 font-medium">
              Please collect your sticker & stick it vertically on your pants
            </p>
          </div>

          <div className="flex items-center justify-center w-80 gap-8 p-4 rounded-xl mx-auto">
            <div className="w-1/2 overflow-hidden rounded-lg bg-black">
              <video
                src={VIDEO_PATH}
                className="w-full h-full object-cover rounded-lg rotate-180"
                autoPlay
                loop
                muted
                playsInline // Ensures it plays on mobile devices
                width={300}
                height={200}
              ></video>
            </div>

            <Image
              src="/rfid/wearGuide.jpg" // put your jpg inside /public folder
              alt="RFID Wear Guide"
              width={300}
              height={200}
              className="rounded-lg object-contain w-1/2 h-auto"
            />
          </div>

          <div className="flex justify-between">
            <Button
              onClick={handleRepeat}
              variant="ghost"
              className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
              disabled={!lastDirections}
            >
              🔊 Repeat Instructions
            </Button>
            <Button
              onClick={() => {
                void handleCollected();
              }}
              variant="ghost"
              className=" bg-hospital-teal hover:bg-hospital-teal/90 text-white kiosk-button"
            >
              Collected
            </Button>
          </div>
        </Card>
      </div>
    );
  }
};

export default RfidScreen;
