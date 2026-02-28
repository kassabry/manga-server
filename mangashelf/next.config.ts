import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  serverExternalPackages: ["sharp", "jszip"],
  images: {
    unoptimized: false,
  },
  devIndicators: false,
};

export default nextConfig;
