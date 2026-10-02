import type { MetadataRoute } from "next";

/** What makes the app installable ([07] § 8). The icons are drawn in app/icon.tsx. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DealerAI",
    short_name: "DealerAI",
    description: "The dealership's customers, in one inbox.",
    start_url: "/",
    display: "standalone",
    background_color: "#0a2540",
    theme_color: "#0a2540",
    icons: [
      { src: "/icon/192", sizes: "192x192", type: "image/png" },
      { src: "/icon/512", sizes: "512x512", type: "image/png" },
      { src: "/icon/512", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
