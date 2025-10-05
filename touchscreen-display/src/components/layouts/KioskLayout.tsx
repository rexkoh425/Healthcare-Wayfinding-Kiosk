"use client";

import React, { useState } from "react";
import { ScanLine, Globe } from "lucide-react";
import { useTranslation } from "react-i18next";

const languages = [
  { id: "en", name: "English", local: "English" },
  { id: "zh", name: "Mandarin", local: "Chinese" },
  { id: "ms", name: "Malay", local: "Melayu" },
  { id: "ta", name: "Tamil", local: "Tamil" },
];

interface KioskLayoutProps {
  children: React.ReactNode;
  showHeader?: boolean;
}

const KioskLayout: React.FC<KioskLayoutProps> = ({
  children,
  showHeader = true,
}) => {
  const { i18n } = useTranslation();
  const [selectedLang, setSelectedLang] = useState<string>("en");

  const handleLanguageClick = (langId: string) => {
    setSelectedLang(langId);
    i18n.changeLanguage(langId);
  };

  return (
    <div className="min-h-screen flex flex-col bg-hospital-gray">
      {showHeader && (
        <header className="bg-white shadow-sm border-b border-hospital-blue/10 p-4">
          <div className="container mx-auto flex items-center">
            <ScanLine className="h-8 w-8 text-hospital-teal mr-3" />
            <h1 className="text-2xl font-bold text-hospital-blue-gray">
              Scan and Go
            </h1>
          </div>

          <div className="absolute top-4 right-8 flex items-center space-x-4">
            <Globe size={20} className="text-hospital-teal" />
            <div className="flex space-x-2">
              {languages.map((lang) => (
                <button
                  key={lang.id}
                  onClick={() => handleLanguageClick(lang.id)}
                  className={[
                    "px-2 py-1 rounded text-sm font-medium",
                    selectedLang === lang.id
                      ? "bg-hospital-teal/10 text-hospital-teal"
                      : "text-hospital-blue-gray/70 hover:text-hospital-blue-gray hover:bg-hospital-blue/5",
                  ].join(" ")}
                >
                  {lang.local}
                </button>
              ))}
            </div>
          </div>
        </header>
      )}
      <main className="flex-1 p-6 md:p-8 lg:p-10">
        <div className="container mx-auto">{children}</div>
      </main>
    </div>
  );
};

export default KioskLayout;
