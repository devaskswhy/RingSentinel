import type { Metadata } from "next";
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

export const metadata: Metadata = {
  title: "RingSentinel — coordinated fraud, seen as a graph",
  description:
    "Fraud rings are invisible per transaction and obvious as a graph. RingSentinel finds the cluster, explains it in plain language, and puts a human in front of every decision.",
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
