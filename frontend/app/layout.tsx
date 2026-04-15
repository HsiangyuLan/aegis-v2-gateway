import type { Metadata } from "next";
import { Inter, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

/**
 * Font strategy:
 * - Inter (400/700) via next/font/google → "--font-body"
 * - Futura Heavy: commercial font loaded via @font-face in globals.css
 *   Place files at: public/fonts/FuturaHeavy.woff2 / FuturaHeavyItalic.woff2
 *   Fallback: Century Gothic → Trebuchet MS → sans-serif
 * - Sentry initialised via instrumentation.ts (not here, to avoid double-init)
 */

const inter = Inter({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "HSIANGYU LAN — MIS Architect · Fisher College of Business",
  description:
    "Portfolio of Hsiangyu Lan — MIS graduate from Fisher College of Business " +
    "architecting HFT-grade inference infrastructure, Rust FFI edge computing, " +
    "and FinOps arbitrage systems.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider
      appearance={{
        variables: {
          colorPrimary: "#FF0000",
          colorBackground: "#FFFFFF",
          colorText: "#000000",
          borderRadius: "0px",
        },
      }}
    >
      <html
        lang="en"
        className={`${inter.variable} ${geistMono.variable} h-full`}
      >
        <head>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link
            rel="preconnect"
            href="https://fonts.gstatic.com"
            crossOrigin="anonymous"
          />
          <link
            rel="stylesheet"
            href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
          />
        </head>
        <body className="min-h-full antialiased">
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
