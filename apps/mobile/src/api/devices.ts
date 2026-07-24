// Push device registration REST for the mobile client (原生推送设备注册).
//
// Bearer-authenticated wrappers over api/routes/devices.py. REST DTOs track OpenAPI.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type DevicePlatform = Schemas["DeviceRegistration"]["platform"];

/** Register (or refresh) this device's push token for the current user. */
export async function registerDevice(
  token: string,
  platform: DevicePlatform,
): Promise<void> {
  const res = await apiFetch("/v1/devices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token,
      platform,
    } satisfies Schemas["DeviceRegistration"]),
  });
  if (!res.ok) throw new Error(`设备注册失败 (${res.status})`);
}

/** Unregister one device token (logout). */
export async function unregisterDevice(token: string): Promise<void> {
  const res = await apiFetch(`/v1/devices?token=${encodeURIComponent(token)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`设备注销失败 (${res.status})`);
}
