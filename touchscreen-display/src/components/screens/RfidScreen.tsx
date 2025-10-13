import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";
import { MedicalIcon, MedicalIconType } from "@/components/ui/MedicalIcons";
import Image from "next/image";

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

const RfidScreen: React.FC = () => {
    const router = useRouter();
    const { t } = useTranslation();
    const { send } = useWebSocket();
    const searchParams = useSearchParams();
    const [dispensing, setDispensing] = useState(true);

    const dest = searchParams.get("dest");
    const baseUrl = resolveRfidBase();

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

  // when user clicks the Back Button
  const handleBack = () => {
    // send action to server (touchscreen -> hologram)
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }

    // then navigate
    router.push("/");
  };

  const handleCollected = () => {
    // send action to server (touchscreen -> hologram)
    try {
      send({ type: "action", action: "idle" });
    } catch (err) {
      console.warn("Failed to send WS idle action", err);
    }
    // then navigate
    router.push("/");
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
                <p className="text-3xl font-bold text-hospital-blue-gray">Please Collect your Sticker </p>
                <p className="text-3xl font-bold text-hospital-blue-gray">And stick it vertically on your pants</p>
            </div>
            <div className="flex items-center justify-center w-80 p-4 rounded-xl mx-auto">
                <Image
                    src="/rfid/wearGuide.jpg" // put your jpg inside /public folder
                    alt="RFID Wear Guide"
                    width={300}
                    height={200}
                    className="rounded-lg object-contain"
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