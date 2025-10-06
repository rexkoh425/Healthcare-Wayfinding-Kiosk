import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Mic, ScanText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";

const HomeScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const handleScan = () => {
    router.push("/camera");
  };

  const handleTalk = () => {
    send({ type: "action", action: "talk" });
    router.push("/chat");
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-hospital-blue-gray mb-2">
            {t("home.title")}
          </h2>
          <p className="text-hospital-blue-gray/70 text-xl max-w-xl mx-auto">
            {t("home.caption")}
          </p>
        </div>

        <div className="flex flex-col space-y-4">
          {/* Talk Button */}
          <Button
            onClick={handleTalk}
            size="lg"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-6 text-lg kiosk-button"
          >
            <Mic className="mr-2 h-5 w-5" />
            {t("home.talkButton")}
          </Button>

          {/* Scan Button */}
          <Button
            onClick={handleScan}
            size="lg"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-6 text-lg kiosk-button"
          >
            <ScanText className="mr-2 h-5 w-5" />
            {t("home.scanButton")}
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default HomeScreen;