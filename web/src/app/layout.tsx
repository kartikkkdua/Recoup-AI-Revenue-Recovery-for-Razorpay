import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Recoup — AI Revenue Recovery for Razorpay",
  description:
    "An agent that watches your Razorpay payment stream, classifies every failure, and recovers the ones that shouldn't have failed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text">{children}</body>
    </html>
  );
}
