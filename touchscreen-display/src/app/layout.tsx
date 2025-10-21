import React from "react";
import KioskLayout from "@/components/layouts/KioskLayout";
import "./globals.css";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head />
      <body>
        <KioskLayout>{children}</KioskLayout>
      </body>
    </html>
  );
}
