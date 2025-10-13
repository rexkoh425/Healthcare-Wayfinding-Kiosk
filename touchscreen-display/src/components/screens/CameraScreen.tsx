import React, { useEffect, useRef, useState } from "react";
import { Search, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import Spinner from "@/components/ui/Spinner";
import useWebSocket from "@/lib/useWebSocket";

const POLL_INTERVAL_MS = 500;

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

const CameraScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();
  const { send } = useWebSocket();

  const [apiBase, setApiBase] = useState<string>("");
  const [streamUrl, setStreamUrl] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const streamImgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    const base = resolveOcrBase();
    setApiBase(base);
    if (base) {
      setStreamUrl(`${base}/stream.mjpg`);
    }
    return () => {
      const imgEl = streamImgRef.current;
      if (imgEl) {
        imgEl.src = "";
        imgEl.removeAttribute("src");
      }
    };
  }, []);

  useEffect(() => {
    if (!apiBase || typeof window === "undefined") {
      return undefined;
    }

    let lastSeenTs: number | null = null;

    async function pollLatest() {
      try {
        const response = await fetch(`${apiBase}/latest_result`, { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        if (!payload.ready) {
          return;
        }
        if (lastSeenTs && payload.updated_at === lastSeenTs) {
          return;
        }
        lastSeenTs = payload.updated_at;
        const locations: string[] = Array.isArray(payload.data?.locations) ? payload.data.locations : [];
        if (locations.length > 0) {
          const params = new URLSearchParams({ locations: JSON.stringify(locations) });
          router.push(`/destination?${params.toString()}`);
        }
      } catch (error) {
        console.error("latest_result poll failed", error);
      }
    }

    pollLatest();
    const id = window.setInterval(pollLatest, POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(id);
    };
  }, [apiBase, router]);

  const handleScan = async () => {
    if (!apiBase) {
      alert("Camera service offline. Please try again shortly.");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/ocr`, { method: "POST" });
      if (!response.ok) {
        throw new Error(`OCR request failed: ${response.status}`);
      }
      const payload = await response.json();
      const locations: string[] = Array.isArray(payload.locations) ? payload.locations : [];
      if (locations.length === 0) {
        alert("No destination detected. Please adjust the document and try again.");
      } else {
        const params = new URLSearchParams({ locations: JSON.stringify(locations) });
        router.push(`/destination?${params.toString()}`);
      }
    } catch (error) {
      console.error("OCR trigger failed", error);
      alert("Error running OCR. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    const imgEl = streamImgRef.current;
    if (imgEl) {
      imgEl.src = "";
      imgEl.removeAttribute("src");
    }
    setStreamUrl("");
    send({ type: "action", action: "idle" });
    router.replace("/");
    router.refresh();
  };

  return (
    <div className="relative flex flex-col items-center justify-center h-[85vh]">
      <Card className="w-full max-w-3xl p-8 text-center kiosk-card">
        <div className="mb-8">
          <div className="bg-hospital-teal/10 w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6">
            <FileText size={48} className="text-hospital-teal" />
          </div>
          <p className="text-hospital-blue-gray/70 text-xl max-w-xl mx-auto">
            {t("camera.description")}
          </p>
        </div>

        {streamUrl && !loading && (
          <div className="mb-8 flex justify-center">
            <div className="border rounded-lg overflow-hidden shadow flex justify-center items-center max-h-[75vh] w-full max-w-2xl bg-black">
              <img
                ref={streamImgRef}
                src={streamUrl}
                alt="Live camera stream"
                className="max-h-[75vh] w-auto object-contain"
              />
            </div>
          </div>
        )}

        <div className="flex flex-col space-y-4">
          <Button
            onClick={handleScan}
            size="lg"
            disabled={loading}
            className={`relative bg-hospital-teal text-white py-6 text-lg kiosk-button ${
              loading ? "cursor-not-allowed opacity-80" : "hover:bg-hospital-teal/90"
            }`}
          >
            {loading ? <Spinner size={28} /> : (
              <>
                <Search className="mr-2 h-5 w-5" />
                {t("camera.scanDocument")}
              </>
            )}
          </Button>
        </div>

        <div className="flex justify-between mt-6">
          <Button
            onClick={handleBack}
            variant="ghost"
            className="text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/10"
            disabled={loading}
          >
            {t("common.back")}
          </Button>
        </div>
      </Card>

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/70 backdrop-blur-sm z-20">
          <Spinner size={48} className="text-hospital-teal" />
        </div>
      )}
    </div>
  );
};

export default CameraScreen;
