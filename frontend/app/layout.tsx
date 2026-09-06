import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'ZUMBA',
  description: 'Agentic AI assistant',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#08080b] text-zinc-100 antialiased overflow-hidden">{children}</body>
    </html>
  );
}
