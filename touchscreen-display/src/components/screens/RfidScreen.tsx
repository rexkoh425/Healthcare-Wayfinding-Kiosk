import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";
import { MedicalIcon, MedicalIconType } from "@/components/ui/MedicalIcons";
import Image from "next/image";

const VIDEO_PATH = "/rfid/collectionGuide.mp4";

function resolveRfidBase(): string {
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
interface InstructionRecord {
    location: string;
    directions: string;
    code?: string;
    level?: string;
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


const RfidScreen: React.FC = () => {
    const router = useRouter();
    const { t } = useTranslation();
    const { send } = useWebSocket();
    const searchParams = useSearchParams();
    const [dispensing, setDispensing] = useState(true);
    const audioRef = useRef<{ audio: HTMLAudioElement; url: string } | null>(null);

    const dest = searchParams.get("dest");
    const baseUrl = resolveRfidBase();

    useEffect(() => {
        if (!dest) {
            return;
        }

        let isCancelled = false;

        const fetchAndSpeak = async () => {
            try {
                const response = await fetch("/instructions.json", { cache: "no-store" });
                if (!response.ok) {
                    throw new Error(`Failed to load instructions: ${response.status}`);
                }

                const payload = await response.json();
                if (!Array.isArray(payload)) {
                    throw new Error("Invalid instructions payload");
                }

                const instructions = payload.filter(
                    (item: any): item is InstructionRecord =>
                        typeof item?.location === "string" && typeof item?.directions === "string",
                );

                const normalized = dest.trim().toLowerCase();
                const match = instructions.find((item) => item.location.trim().toLowerCase() === normalized && item.directions.trim().length > 0);

                if (!match) {
                    console.warn("No matching instructions found for destination:", dest);
                    return;
                }

                if (isCancelled) {
                    return;
                }

                const directions: string = match.directions.trim();
                const apiBase = resolveTtsBase();
                if (!apiBase) {
                    console.warn("Unable to resolve TTS base URL");
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
                const b64 = typeof ttsPayload?.audio_wav_b64 === "string" ? ttsPayload.audio_wav_b64.replace(/\s+/g, "") : "";
                if (!b64) {
                    throw new Error("Missing audio payload from TTS response");
                }

                if (isCancelled) {
                    return;
                }

                const binary = window.atob(b64);
                const buffer = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i += 1) {
                    buffer[i] = binary.charCodeAt(i);
                }
                const blob = new Blob([buffer], { type: "audio/wav" });
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                audioRef.current = { audio, url };

                const cleanup = () => {
                    if (audioRef.current?.audio === audio) {
                        audioRef.current = null;
                    }
                    URL.revokeObjectURL(url);
                };

                audio.onended = cleanup;
                audio.onerror = cleanup;

                try {
                    await audio.play();
                } catch (playError) {
                    cleanup();
                    throw playError;
                }
            } catch (error) {
                console.error("Failed to fetch and play instructions audio", error);
            }
        };

        fetchAndSpeak();

        return () => {
            isCancelled = true;
            const current = audioRef.current;
            if (current) {
                current.audio.pause();
                current.audio.src = "";
                URL.revokeObjectURL(current.url);
                audioRef.current = null;
            }
        };
    }, [dest]);

    useEffect(() => {
        async function handleTags() {
            try {
                // 1️⃣ GET request
                const rfidUrl = resolveRfidReaderUrl();
                if (!rfidUrl) throw new Error("RFID reader URL is not configured.");
                console.log("Requesting RFID reader at:", rfidUrl);
                const espRes = await fetch(rfidUrl);
                if (!espRes.ok) throw new Error(`HTTP error from rfid! status: ${espRes.status}`);

                const tagData = await espRes.json();
                console.log("Received from RFID Reader:", tagData);

                // 2️⃣ POST request to user/backend
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
                    })
                });

                if (postRes.ok) {
                    const postResult = await postRes.json();
                    console.log("POST result:", postResult);
                    setDispensing(false);
                } else if (postRes.status == 409){
                    setDispensing(false);
                } else {
                    throw new Error(`HTTP error from users api! status: ${postRes.status}`);
                }
            } catch (err) {
                console.error(err);
            }
        }
        handleTags();
    }, []);

    useEffect(() => {
        // Only start the timer when the collection screen is visible (`dispensing` is false)
        if (!dispensing) {
            const inactivityTimer = setTimeout(() => {
                console.log('Timeout: User collect sticker. Navigating home.');
                // Navigate back to the main page after 15 seconds
                router.push('/');
            }, 15000); // 15000 milliseconds = 15 seconds

            //Cleanup function to clear timer 
            return () => {
                clearTimeout(inactivityTimer);
            };
        }
    }, [dispensing, router]); 

  // when user clicks the Back Button
  const handleBack = () => {
    // send action to server (touchscreen -> hologram)
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }

    // then navigate
    router.replace("/");
    router.refresh();
  };

  const handleCollected = () => {
    // send action to server (touchscreen -> hologram)
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    // then navigate
    router.replace("/");
    router.refresh();
  };

  if (dispensing) {
    return (
        <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
            <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
                <div>
                    <p className="text-3xl font-bold text-hospital-blue-gray">Dispensing Sticker...</p>
                    <p className="text-3xl font-bold text-hospital-blue-gray">{dest}</p>
                    {/* Container for Medical Icon and Unit Number */}
                    <div className="flex-shrink-0 mx-6 flex flex-col items-center">
                        {/* Medical Icon
                        <div className="bg-iconBg rounded-full p-4">
                        <MedicalIcon
                            type={dest.iconType}
                        /> */}
                    </div>
                </div>

                <div className="flex justify-between">
                <Button
                    onClick={handleBack}
                    variant="ghost"
                    className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
                >
                    {t("common.back")}
                </Button>
                </div>
            </Card>
        </div>
    )
  }

  else {
    return (
        <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
        <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
            <div>
                <p className="text-3xl font-bold text-hospital-blue-gray">Please Collect Your Sticker </p>
                <p className="text-3xl font-bold text-hospital-blue-gray">& Stick It Vertically on Your Pants</p>
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
                    onClick={handleBack}
                    variant="ghost"
                    className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
                >
                    {t("common.back")}
                </Button>
                <Button
                    onClick={handleCollected}
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
