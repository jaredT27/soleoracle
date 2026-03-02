import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SoleOracle — Sneaker Drop Oracle & Resale Copilot",
  description: "Real-time sneaker drops, rarity intelligence, and portfolio tracking",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-bg text-white min-h-screen">
        {children}
      </body>
    </html>
  );
}
