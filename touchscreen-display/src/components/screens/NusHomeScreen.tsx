import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Mic, SmartphoneNfc } from "lucide-react";
import { useRouter } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";

const HomeScreen: React.FC = () => {
  const router = useRouter();
  const { send } = useWebSocket();

  const handleScan = () => {
    router.push("/nfc");
  };

  const handleTalk = () => {
    send({ type: "action", action: "talk" });
    router.push("/chat");
  };

  return (
    <div className="flex flex-col items-center justify-center h-[80vh] animate-fade-in">
      <Card className="w-[90vw] max-w-none p-12 text-center kiosk-card flex flex-col scale-110">
        <div className="mb-8">
          <h2 className="text-5xl font-bold text-hospital-blue-gray mb-2">
            Hello, I&apos;m your wayfinding assistant!
          </h2>
          <p className="text-hospital-blue-gray/70 text-3xl max-w-xl mx-auto">
            Guiding you through every step.
          </p>
        </div>

        <div className="flex flex-col space-y-4">
          {/* Talk Button */}
          <Button
            onClick={handleTalk}
            size="lg"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-8 text-3xl kiosk-button"
          >
            <Mic className="mr-2 h-8 w-8" />
            Press here to tell me where you want to go
          </Button>

          {/* Scan Button */}
          <Button
            onClick={handleScan}
            size="lg"
            className="bg-hospital-teal hover:bg-hospital-teal/90 text-white py-8 text-3xl kiosk-button"
          >
            <SmartphoneNfc className="mr-2 h-8 w-8" />
            Tap your matric card
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default HomeScreen;
