import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";
import { MedicalIcon, MedicalIconType } from "@/components/ui/MedicalIcons";


const RfidScreen: React.FC = () => {
    const router = useRouter();
    const { t } = useTranslation();
    const { send } = useWebSocket();
    const searchParams = useSearchParams();
    const [dispensing, setDispensing] = useState(true);

    const dest = searchParams.get("dest");

    useEffect(() => {
        async function handleTags() {
            try {
                // 1️⃣ GET request to ESP32
                const espRes = await fetch("http://localhost:5000/"); // ESP32 endpoint
                if (!espRes.ok) throw new Error(`HTTP error from rfid! status: ${espRes.status}`);

                const tagData = await espRes.json(); // assuming ESP32 returns JSON
                console.log("Received from ESP32:", tagData);

                // 2️⃣ POST request to user/backend
                const postRes = await fetch("http://localhost:8000/users/", {
                    method: "POST",
                    headers: {
                    "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        rfidTagId: tagData.epc,
                        destination: dest,
                    })
                });

                if (!postRes.ok) {
                    const postResult = await postRes.json();
                    console.log("POST result:", postResult);
                    setDispensing(false);
                } else if (postRes.status == 409){
                    //ignore 
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
                  <p className="text-3xl font-bold text-hospital-blue-gray">And stick it in an upright position</p>
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
    );
    }
};

export default RfidScreen;