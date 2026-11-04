import type { PublicCar } from "@islamic-car/shared";

// Серверные компоненты обращаются к API напрямую, минуя браузерный прокси.
const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { cache: "no-store" });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`API ${res.status}`);
    return (await res.json()) as T;
  } catch (e) {
    console.error("API недоступен:", path, e);
    return null;
  }
}

export type Company = { seller_name: string; support_phone: string; consent_version: string };

export const getCars = (query = "") => apiGet<PublicCar[]>(`/api/public/cars${query ? `?${query}` : ""}`);
export const getCar = (id: string) => apiGet<PublicCar>(`/api/public/cars/${encodeURIComponent(id)}`);
export const getMakes = () => apiGet<string[]>("/api/public/makes");
export const getCompany = () => apiGet<Company>("/api/public/company");
