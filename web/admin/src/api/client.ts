export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
export type RecordData = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function refreshToken(): Promise<boolean> {
  const token = sessionStorage.getItem("admin_refresh_token");
  if (!token) return false;
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = await response.json();
        sessionStorage.setItem("admin_access_token", data.access_token);
        sessionStorage.setItem("admin_refresh_token", data.refresh_token);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = sessionStorage.getItem("admin_access_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retry && (await refreshToken()))
    return request<T>(path, options, false);
  if (!response.ok) {
    let body: RecordData = {};
    try {
      body = await response.json();
    } catch {
      /* 代理错误可能不是 JSON */
    }
    if (response.status === 401) {
      sessionStorage.removeItem("admin_access_token");
      sessionStorage.removeItem("admin_refresh_token");
      if (location.pathname !== "/login") location.assign("/login");
    }
    throw new ApiError(
      response.status,
      String(body.code || "HTTP_ERROR"),
      String(body.message || response.statusText),
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function query(
  path: string,
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  });
  const suffix = search.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export async function download(path: string, filename: string): Promise<void> {
  const headers = new Headers();
  const token = sessionStorage.getItem("admin_access_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { headers });
  if (!response.ok)
    throw new ApiError(response.status, "DOWNLOAD_ERROR", "下载失败");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
