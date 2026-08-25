import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RingSentinel",
  description:
    "Fraud-ring detection via entity graphs. Every flag is reviewed by a human.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
