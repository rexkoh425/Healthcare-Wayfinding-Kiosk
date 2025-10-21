"use client";

import React from "react";
import { Route } from "lucide-react";
import { useRouter } from "next/navigation";
import useWebSocket from "@/lib/useWebSocket";

interface KioskLayoutProps {
  children: React.ReactNode;
  showHeader?: boolean;
}

const KioskLayout: React.FC<KioskLayoutProps> = ({
  children,
  showHeader = true,
}) => {
  const router = useRouter();
  const { send } = useWebSocket();

  const handleBack = () => {
    send({ type: "action", action: "idle" });
    router.push("/");
  };

  return (
    <div className="min-h-screen flex flex-col bg-hospital-gray">
      {showHeader && (
        <header className="bg-white shadow-sm border-b border-hospital-blue/10 p-4">
          <button onClick={handleBack}>
            <div className="container mx-auto flex items-center">
              <Route className="h-8 w-8 text-hospital-teal mr-3" />
              <h1 className="text-2xl font-bold text-hospital-blue-gray">
                Find My Way
              </h1>
            </div>
          </button>
        </header>
      )}
      <main className="flex-1 p-6 md:p-8 lg:p-10">
        <div className="container mx-auto">{children}</div>
      </main>
    </div>
  );
};

export default KioskLayout;
