import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // "standalone" copies only what the server needs into .next/standalone, which is what the container image runs
  // (deploy/cloud). `next start` on this PC is unaffected.
  output: "standalone",
};

export default nextConfig;
