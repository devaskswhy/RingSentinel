import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";

/**
 * One display face, one body face.
 *
 * Space Grotesk carries the headlines — geometric and slightly technical, which
 * suits a tool about payment infrastructure without tipping into novelty.
 * Inter does everything else; it stays legible at the small sizes the console
 * table needs.
 *
 * Both are self-hosted by next/font, so there is no runtime request to Google
 * and no layout shift while a webfont swaps in.
 */
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});

const DESCRIPTION =
  "Fraud rings are invisible per transaction and obvious as a graph. RingSentinel finds the cluster, explains it in plain language, and puts a human in front of every decision.";

export const metadata: Metadata = {
  title: "RingSentinel — coordinated fraud, seen as a graph",
  description: DESCRIPTION,
  applicationName: "RingSentinel",
  // Card and icon are generated from app/opengraph-image.tsx and app/icon.svg,
  // so they cannot drift from the numbers in the repo the way exported assets
  // would. Next fills in the image tags from those files.
  openGraph: {
    title: "RingSentinel — coordinated fraud, seen as a graph",
    description: DESCRIPTION,
    siteName: "RingSentinel",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "RingSentinel — coordinated fraud, seen as a graph",
    description: DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: "#08090a",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${spaceGrotesk.variable} ${inter.variable}`}>
      {/* rs-grain lays a procedural noise field over the whole viewport. A
          perfectly flat dark background is what makes a dark interface read as
          a template; every real instrument has some texture to it. */}
      <body className="rs-grain">{children}</body>
    </html>
  );
}
