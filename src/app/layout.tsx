import type { Metadata } from "next";
import type { Viewport } from "next";
import "../index.css";

export const metadata: Metadata = {
  title: "Jarvis Desktop",
  description: "Dark cinematic AI assistant interface"
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
