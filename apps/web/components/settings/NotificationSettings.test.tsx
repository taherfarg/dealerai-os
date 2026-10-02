import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { LocaleProvider } from "@/lib/i18n-client";
import { NotificationSettings } from "./NotificationSettings";

const PHONE = {
  id: "phone",
  user_agent:
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  created_at: "2026-10-01T08:00:00Z",
  last_success_at: "2026-10-02T06:30:00Z",
};
const LAPTOP = {
  id: "laptop",
  user_agent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  created_at: "2026-09-30T08:00:00Z",
  last_success_at: null,
};
const SUBSCRIPTION = { endpoint: "https://fcm.googleapis.com/x", p256dh: "p", auth: "a", user_agent: "ua" };

const state = vi.hoisted(() => ({
  can: true,
  homeScreen: false,
  mine: null as string | null,
  keyError: null as unknown,
  devices: [] as object[],
  subscribed: [] as unknown[],
  removed: [] as string[],
  tested: null as { sent: number; failed: number } | null,
  refusal: null as Error | null,
  silenced: 0,
  offer: null as { prompt: () => Promise<void> } | null,
}));

vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { tenant: { timezone: "Asia/Dubai" } } }),
  usePushKey: () => ({
    data: state.keyError ? undefined : { public_key: "the-key" },
    isError: state.keyError !== null,
    error: state.keyError,
  }),
  usePushDevices: () => ({ data: state.devices }),
  useSubscribeDevice: () => ({
    mutateAsync: async (body: unknown) => {
      state.subscribed.push(body);
      return { id: "new-device" };
    },
  }),
  useRemoveDevice: () => ({ mutate: (id: string) => state.removed.push(id) }),
  useTestPush: () => ({ isPending: false, data: state.tested, mutate: vi.fn() }),
}));

vi.mock("@/lib/push", async (original) => ({
  ...(await original<typeof import("@/lib/push")>()),
  supportsPush: () => state.can,
  needsHomeScreen: () => state.homeScreen,
  isStandalone: () => false,
  watchDevice: () => () => {},
  rememberedDevice: () => state.mine,
  rememberDevice: (id: string | null) => void (state.mine = id),
  subscribeThisDevice: async (key: string) => {
    if (state.refusal) throw state.refusal;
    expect(key).toBe("the-key");
    return SUBSCRIPTION;
  },
  silenceThisDevice: async () => void (state.silenced += 1),
}));

vi.mock("@/components/ServiceWorker", () => ({ useInstallOffer: () => state.offer }));

function show() {
  render(
    <LocaleProvider locale="en">
      <NotificationSettings />
    </LocaleProvider>,
  );
}

const turnOn = () => screen.queryByRole("button", { name: "Turn on notifications on this device" });

beforeEach(() => {
  Object.assign(state, {
    can: true,
    homeScreen: false,
    mine: null,
    keyError: null,
    devices: [],
    subscribed: [],
    removed: [],
    tested: null,
    refusal: null,
    silenced: 0,
    offer: null,
  });
});

describe("NotificationSettings", () => {
  it("says so when this browser cannot push", () => {
    state.can = false;
    show();
    expect(screen.getByText("This browser cannot receive notifications.")).toBeTruthy();
    expect(turnOn()).toBeNull();
  });

  it("explains the Home Screen first on an iPhone", () => {
    state.can = false; // a tab on an iPhone has no push until it is installed
    state.homeScreen = true;
    show();
    expect(screen.getByText(/Add to Home Screen/)).toBeTruthy();
    expect(screen.queryByText("This browser cannot receive notifications.")).toBeNull();
    expect(turnOn()).toBeNull();
  });

  it("says when the server has no key", () => {
    state.keyError = new ApiError({
      type: "push-unavailable",
      title: "Push is not configured",
      status: 503,
    });
    show();
    expect(screen.getByText("Notifications are not set up on this server yet.")).toBeTruthy();
    expect(turnOn()).toBeNull();
  });

  it("turns notifications on for this device, and remembers which one it is", async () => {
    show();
    fireEvent.click(turnOn()!);
    await waitFor(() => expect(state.subscribed).toEqual([SUBSCRIPTION]));
    await waitFor(() => expect(state.mine).toBe("new-device"));
  });

  it("says when the browser has been told no", async () => {
    state.refusal = new Error("denied");
    show();
    fireEvent.click(turnOn()!);
    expect((await screen.findByRole("alert")).textContent).toMatch(/blocked for this site/);
    expect(state.subscribed).toEqual([]);
  });

  it("says it is on once this device is among mine", () => {
    state.devices = [PHONE];
    state.mine = "phone";
    show();
    expect(screen.getByText("Notifications are on for this device.")).toBeTruthy();
    expect(turnOn()).toBeNull();
  });

  it("offers to turn it on again when this device was removed somewhere else", () => {
    state.devices = [LAPTOP];
    state.mine = "phone"; // remembered here, gone from the server
    show();
    expect(turnOn()).not.toBeNull();
  });

  it("lists my devices and marks this one", () => {
    state.devices = [PHONE, LAPTOP];
    state.mine = "phone";
    show();
    const rows = screen.getAllByRole("listitem").map((row) => row.textContent);
    expect(rows[0]).toContain("Chrome · Android");
    expect(rows[0]).toContain("This device");
    expect(rows[0]).toContain("last reached");
    expect(rows[1]).toContain("Chrome · Windows");
    expect(rows[1]).not.toContain("This device");
    expect(rows[1]).toContain("not reached yet");
  });

  it("removes a device, and silences this browser when it is the one", () => {
    state.devices = [PHONE, LAPTOP];
    state.mine = "phone";
    show();
    const [phone, laptop] = screen.getAllByRole("button", { name: "Remove" });

    fireEvent.click(laptop);
    expect(state.removed).toEqual(["laptop"]);
    expect(state.silenced).toBe(0);

    fireEvent.click(phone);
    expect(state.removed).toEqual(["laptop", "phone"]);
    expect(state.silenced).toBe(1);
  });

  it("says how a test went", () => {
    state.devices = [PHONE, LAPTOP];
    state.tested = { sent: 1, failed: 1 };
    show();
    expect(screen.getByRole("status").textContent).toBe(
      "Sent to this many devices: 1 · Could not reach this many: 1",
    );
  });

  it("has nothing to test with no device", () => {
    show();
    expect(screen.getByText("No device is subscribed yet.")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Send a test notification" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("offers to install when the browser does", () => {
    const prompt = vi.fn(async () => {});
    state.offer = { prompt };
    show();
    fireEvent.click(screen.getByRole("button", { name: "Install the app" }));
    expect(prompt).toHaveBeenCalled();
  });

  it("does not offer to install otherwise", () => {
    show();
    expect(screen.queryByRole("button", { name: "Install the app" })).toBeNull();
  });
});
