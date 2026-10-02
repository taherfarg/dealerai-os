import { describe, expect, it } from "vitest";
import { deviceName, keyBytes, needsHomeScreen } from "./push";

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";
const IPHONE_CHROME =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1";
const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";
const WINDOWS_EDGE =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0";
const LINUX_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0";
const MAC_SAFARI =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15";

describe("keyBytes", () => {
  it("turns the server's key into what subscribe() takes", () => {
    // RFC 8291's application server key: an uncompressed P-256 point.
    const bytes = keyBytes(
      "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8",
    );
    expect(bytes).toHaveLength(65);
    expect(bytes[0]).toBe(4);
    expect(bytes[64]).toBe(0x0f);
  });
});

describe("needsHomeScreen", () => {
  it("knows an iPhone that has not been added to the Home Screen", () => {
    expect(needsHomeScreen(IPHONE_SAFARI, false)).toBe(true);
    expect(needsHomeScreen(IPHONE_CHROME, false)).toBe(true);
  });

  it("lets it be once the app is opened from the Home Screen", () => {
    expect(needsHomeScreen(IPHONE_SAFARI, true)).toBe(false);
  });

  it("asks nothing of the browsers that push from a tab", () => {
    expect(needsHomeScreen(ANDROID_CHROME, false)).toBe(false);
    expect(needsHomeScreen(WINDOWS_EDGE, false)).toBe(false);
  });
});

describe("deviceName", () => {
  it("names a device by its browser and system", () => {
    expect(deviceName(ANDROID_CHROME)).toBe("Chrome · Android");
    expect(deviceName(IPHONE_SAFARI)).toBe("Safari · iPhone");
    expect(deviceName(IPHONE_CHROME)).toBe("Chrome · iPhone");
    expect(deviceName(WINDOWS_EDGE)).toBe("Edge · Windows");
    expect(deviceName(LINUX_FIREFOX)).toBe("Firefox · Linux");
    expect(deviceName(MAC_SAFARI)).toBe("Safari · Mac");
  });

  it("says nothing rather than guess", () => {
    expect(deviceName(null)).toBe("");
    expect(deviceName("curl/8.4.0")).toBe("");
  });
});
