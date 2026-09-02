import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  serverExternalPackages: ["sharp", "jszip"],
  images: {
    unoptimized: false,
  },
  devIndicators: false,
  async headers() {
    return [
      {
        // The worker controls the whole origin, and must never be served from
        // a stale HTTP cache — that is how a bad worker gets stuck for a day.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default nextConfig;
