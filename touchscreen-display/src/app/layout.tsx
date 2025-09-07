"use client";

import React from "react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";
import KioskLayout from "@/components/layouts/KioskLayout";
import "./globals.css";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <I18nextProvider i18n={i18n}>
          <KioskLayout>{children}</KioskLayout>
        </I18nextProvider>
      </body>
    </html>
  );
}
