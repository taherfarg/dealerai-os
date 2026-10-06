import { ImageResponse } from "next/og";

export function generateImageMetadata() {
  return [192, 512].map((size) => ({
    id: String(size),
    size: { width: size, height: size },
    contentType: "image/png",
  }));
}

/**
 * The app's icon, as code: nothing binary to keep in step with the accent —
 * manifest.test.ts sees to it. The letter sits in the middle of the square, so
 * the maskable crop a phone applies keeps it.
 */
export default async function Icon({ id }: { id: Promise<string> | string }) {
  const size = Number(await id);
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
          fontSize: size * 0.5,
          fontWeight: 700,
        }}
      >
        D
      </div>
    ),
    { width: size, height: size },
  );
}
