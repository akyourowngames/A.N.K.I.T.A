import type { Metadata } from "next";
import "../index.css";

export const metadata: Metadata = {
  title: "Jarvis Desktop",
  description: "Dark cinematic AI assistant interface"
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
