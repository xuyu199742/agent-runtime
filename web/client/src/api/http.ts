interface Tokens {
  access_token: string;
  refresh_token: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const accessKey = "client_access_token";
const refreshKey = "client_refresh_token";
let refreshPromise: Promise<boolean> | null = null;

export function hasSession(): boolean {
  return !!sessionStorage.getItem(accessKey);
}

export function saveSession(tokens: Tokens): void {
  sessionStorage.setItem(accessKey, tokens.access_token);
  sessionStorage.setItem(refreshKey, tokens.refresh_token);
}

export function clearSession(): void {
  sessionStorage.removeItem(accessKey);
  sessionStorage.removeItem(refreshKey);
}

async function refreshSession(): Promise<boolean> {
  const token = sessionStorage.getItem(refreshKey);
  if (!token) return false;
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        saveSession((await response.json()) as Tokens);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function authorizedFetch(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<Response> {
  const headers = new Headers(options.headers);
  const token = sessionStorage.getItem(accessKey);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retry && (await refreshSession()))
    return authorizedFetch(path, options, false);
  if (response.status === 401 && path !== "/api/v1/auth/login") {
    clearSession();
    window.dispatchEvent(new Event("client:auth-expired"));
  }
  return response;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await authorizedFetch(path, options);
  if (!response.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = await response.json();
    } catch {
      /* 网关错误可能不是 JSON */
    }
    throw new ApiError(
      response.status,
      String(body.code || "HTTP_ERROR"),
      String(body.message || body.detail || response.statusText),
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
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
};

export async function artifactBlob(id: string): Promise<Blob> {
  const response = await authorizedFetch(
    `/api/v1/client/artifacts/${id}/download`,
  );
  if (!response.ok)
    throw new ApiError(response.status, "DOWNLOAD_FAILED", "文件读取失败");
  return response.blob();
}

export async function downloadArtifact(
  id: string,
  filename: string,
): Promise<void> {
  const blob = await artifactBlob(id);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
