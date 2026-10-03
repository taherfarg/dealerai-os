import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next's development badge sits on the first link of the phone's navigation
  // bar, and the end-to-end suite presses that link (e2e/stack.ts sets E2E).
  devIndicators: process.env.E2E === "1" ? false : undefined,
};

export default nextConfig;
