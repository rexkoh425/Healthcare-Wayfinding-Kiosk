"use client";

import React, { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter } from "next/navigation";
import Spinner from "@/components/ui/Spinner";
import useWebSocket from "@/lib/useWebSocket";

const POLL_INTERVAL_MS = 500;
const VIDEO_PATH = "/camera/scanreg.mp4";

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
        const response = await fetch(`${apiBase}/latest_result`, {
          cache: "no-store",
        });
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
        const locations: string[] = Array.isArray(payload.data?.locations)
          ? payload.data.locations
          : [];
        if (locations.length > 0) {
          const params = new URLSearchParams({
            locations: JSON.stringify(locations),
          });
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
      const locations: string[] = Array.isArray(payload.locations)
        ? payload.locations
        : [];
      if (locations.length === 0) {
        alert(
          "No destination detected. Please adjust the document and try again."
        );
      } else {
        const params = new URLSearchParams({
          locations: JSON.stringify(locations),
        });
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
    if (apiBase) {
      fetch(`${apiBase}/latest_result/reset`, { method: "POST" }).catch(
        (error) => {
          console.warn("Failed to reset latest OCR result on back", error);
        }
      );
    }
    router.replace("/");
  };

  return (
    <div className="relative flex flex-col items-center justify-center h-[80vh]">
      <Card className="w-[90vw] max-w-none p-12 text-center kiosk-card flex flex-col scale-110">
        {/* Video + Camera Row */}
        <div className="flex flex-col md:flex-row items-center justify-center gap-6 mb-6 w-full">
          {/* Instructional Video */}
          <div className="border rounded-lg shadow bg-white p-2 flex-shrink-0">
            <video
              src={VIDEO_PATH}
              autoPlay
              loop
              muted
              playsInline
              className="w-40 md:w-48 lg:w-56 aspect-square object-cover rounded-md"
              aria-label="Instructional video showing how to scan registration slip"
            />
          </div>

          {/* Camera Stream */}
          <div className="border rounded-lg overflow-hidden shadow flex justify-center items-center bg-black relative aspect-video w-full max-w-4xl">
            {streamUrl && !loading ? (
              <img
                ref={streamImgRef}
                src={streamUrl}
                alt="Live camera stream"
                className="w-full h-full object-contain"
              />
            ) : (
              !loading && (
                <p className="text-white p-12 text-lg text-center">
                  Camera feed unavailable or loading...
                </p>
              )
            )}
          </div>
        </div>

        <div className="flex flex-col space-y-4">
          <Button
            onClick={handleScan}
            size="lg"
            disabled={loading}
            className={`w-full bg-hospital-teal text-white py-8 text-3xl kiosk-button ${
              loading
                ? "cursor-not-allowed opacity-80"
                : "hover:bg-hospital-teal/90"
            }`}
          >
            {loading ? (
              <Spinner size={28} />
            ) : (
              <>
                <Search className="mr-2 h-8 w-8" />
                Scan Registration Slip
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
            Back
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
