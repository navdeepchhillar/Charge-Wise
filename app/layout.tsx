import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Chargewise | EV Charging Assistant",
  description: "Find a compatible charging stop. Compare stations, plan battery reserves and explore energy estimates.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
