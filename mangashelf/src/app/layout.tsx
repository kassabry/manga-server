import type { Metadata, Viewport } from "next";
import { SessionProvider } from "next-auth/react";
import { Navbar, BottomNav } from "@/components/layout/Navbar";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "ORVault",
  description: "Self-hosted manga reader and tracker",
  manifest: "/manifest.json",
  robots: { index: false, follow: false },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "ORVault",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0f0f0f",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="apple-touch-icon" sizes="180x180" href="/icon-192.png" />
      </head>
      <body className="bg-bg-primary text-text-primary flex h-dvh flex-col overflow-hidden">
        <SessionProvider>
          <ThemeProvider>
            <Navbar />
            <main className="mx-auto w-full max-w-7xl flex-1 overflow-y-auto px-4 py-6">
              {children}
            </main>
            <BottomNav />
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
