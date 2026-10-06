import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next's development badge sits in a corner of the screen, and the corners
  // are taken: the account button, and both ends of the phone's navigation
  // bar. Compile and runtime errors are still shown without it.
  devIndicators: false,
};

export default nextConfig;
