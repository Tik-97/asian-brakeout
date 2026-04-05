import type { Metadata } from "next";
import { OrientationLock } from "./ui/orientation-lock";
import "./globals.css";

export const metadata: Metadata = {
  title: "Asian Breakout Dashboard",
  description: "Local live dashboard for the Asian Breakout trading bot.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        <OrientationLock />
      </body>
    </html>
  );
}
