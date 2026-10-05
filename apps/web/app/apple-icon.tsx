import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** The Home Screen icon on an iPhone: app/icon.tsx's drawing, at Apple's size. */
export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0f7a55",
          color: "white",
          fontSize: 90,
          fontWeight: 700,
        }}
      >
        D
      </div>
    ),
    size,
  );
}
