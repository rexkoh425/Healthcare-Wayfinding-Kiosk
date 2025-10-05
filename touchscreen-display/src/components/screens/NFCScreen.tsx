import React, { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Wifi, ArrowRight, AlertCircle, CheckCircle } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import useWebSocket from "@/lib/useWebSocket";

enum ScanStatus {
  WAITING,
  SCANNING,
  SUCCESS,
  ERROR,
}

const NFCScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const [scanStatus, setScanStatus] = useState<ScanStatus>(ScanStatus.SCANNING);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (scanStatus !== ScanStatus.SCANNING) {
      return;
    }

    let step = 0;
    const interval = window.setInterval(() => {
      step += 5;
      setProgress(step);

      if (step >= 100) {
        window.clearInterval(interval);
        setTimeout(() => {
          setScanStatus(ScanStatus.SUCCESS);
          setTimeout(() => {
            router.push("/video-walkthrough");
          }, 1000);
        }, 500);
      }
    }, 80);

    return () => {
      window.clearInterval(interval);
    };
  }, [router, scanStatus]);

  const handleBack = () => {
    send({ type: "action", action: "idle" });
    router.push("/");
  };

  return (
    <div className="flex flex-col items-center justify-center h-[85vh] animate-fade-in">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        <div className="mb-10">
          <div
            className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 ${
              scanStatus === ScanStatus.WAITING
                ? "bg-hospital-teal/10"
                : scanStatus === ScanStatus.SCANNING
                  ? "bg-hospital-blue/10"
                  : scanStatus === ScanStatus.SUCCESS
                    ? "bg-green-100"
                    : "bg-red-100"
            }`}
          >
            {scanStatus === ScanStatus.WAITING && (
              <Wifi size={48} className="text-hospital-teal" />
            )}
            {scanStatus === ScanStatus.SCANNING && (
              <Wifi size={48} className="text-hospital-blue animate-pulse" />
            )}
            {scanStatus === ScanStatus.SUCCESS && (
              <CheckCircle size={48} className="text-green-500" />
            )}
            {scanStatus === ScanStatus.ERROR && (
              <AlertCircle size={48} className="text-red-500" />
            )}
          </div>

          <h2 className="text-3xl font-bold text-hospital-blue-gray mb-4">
            {scanStatus === ScanStatus.WAITING && t("nfc.tapCard")}
            {scanStatus === ScanStatus.SCANNING && t("nfc.scanning")}
            {scanStatus === ScanStatus.SUCCESS && `${t("nfc.success")} E2A Studio 3`}
            {scanStatus === ScanStatus.ERROR && t("nfc.error")}
          </h2>

          <p className="text-hospital-blue-gray/70 text-xl max-w-lg mx-auto">
            {scanStatus === ScanStatus.WAITING && t("nfc.waitingDescription")}
            {scanStatus === ScanStatus.SCANNING && t("nfc.scanningDescription")}
            {scanStatus === ScanStatus.SUCCESS && t("nfc.successDescription")}
            {scanStatus === ScanStatus.ERROR && t("nfc.errorDescription")}
          </p>
        </div>

        <div className="mb-12">
          <div className="relative w-full h-64 border-2 border-dashed border-hospital-blue/30 rounded-lg flex items-center justify-center bg-hospital-blue/5 mb-4">
            <div
              className={`w-40 h-40 rounded-full flex items-center justify-center ${
                scanStatus === ScanStatus.WAITING
                  ? "bg-white border-4 border-hospital-teal"
                  : scanStatus === ScanStatus.SCANNING
                    ? "bg-white border-4 border-hospital-blue animate-pulse"
                    : scanStatus === ScanStatus.SUCCESS
                      ? "bg-white border-4 border-green-500"
                      : "bg-white border-4 border-red-500"
              }`}
            >
              <Wifi
                size={64}
                className={
                  scanStatus === ScanStatus.WAITING
                    ? "text-hospital-teal"
                    : scanStatus === ScanStatus.SCANNING
                      ? "text-hospital-blue"
                      : scanStatus === ScanStatus.SUCCESS
                        ? "text-green-500"
                        : "text-red-500"
                }
              />
            </div>

            {scanStatus === ScanStatus.SCANNING && (
              <div className="absolute inset-0 bg-hospital-blue/5 rounded-lg flex items-center justify-center">
                <div className="w-64 h-64 border-4 border-hospital-blue/30 rounded-full animate-ping opacity-75" />
              </div>
            )}
          </div>
          {scanStatus === ScanStatus.SCANNING && (
            <Progress value={progress} className="h-2 mb-2" />
          )}
        </div>

        <div className="flex justify-between">
          <Button
            onClick={handleBack}
            variant="ghost"
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
            disabled={
              scanStatus === ScanStatus.SCANNING ||
              scanStatus === ScanStatus.SUCCESS
            }
          >
            {t("common.back")}
          </Button>

          {scanStatus === ScanStatus.WAITING && (
            <Button className="bg-hospital-teal hover:bg-hospital-teal/90 text-white kiosk-button">
              {t("nfc.simulateTap")}
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          )}

          {scanStatus === ScanStatus.ERROR && (
            <Button className="bg-hospital-teal hover:bg-hospital-teal/90 text-white kiosk-button">
              {t("nfc.tryAgain")}
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
};

export default NFCScreen;
