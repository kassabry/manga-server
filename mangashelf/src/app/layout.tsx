import type { Metadata, Viewport } from "next";
import { SessionProvider } from "next-auth/react";
import { Navbar } from "@/components/layout/Navbar";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "ORVault",
  description: "Self-hosted manga reader and tracker",
  manifest: "/manifest.json",
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
      <body className="bg-bg-primary text-text-primary min-h-screen">
        <SessionProvider>
          <ThemeProvider>
            <Navbar />
            <main className="mx-auto max-w-7xl px-4 py-6 pb-20 sm:pb-6">
              {children}
            </main>
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
