import { Run } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  statusCode: number;
  data: unknown;

  constructor(message: string, statusCode: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.data = data;
  }
}

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)leadflow_csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

class ApiClient {
  private isRefreshing = false;
  private refreshPromise: Promise<boolean> | null = null;

  private async tryRefreshSession(): Promise<boolean> {
    if (this.isRefreshing && this.refreshPromise) {
      return this.refreshPromise;
    }

    this.isRefreshing = true;
    this.refreshPromise = (async () => {
      try {
        const response = await fetch(`${BASE_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
        });
        return response.ok;
      } catch {
        return false;
      } finally {
        this.isRefreshing = false;
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    isRetry = false
  ): Promise<T> {
    const url = `${BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    // Attach double-submit anti-CSRF token on state-changing operations
    const method = (options.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      const csrfToken = getCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }
    }

    const config: RequestInit = {
      ...options,
      headers,
      credentials: "include", // Guarantees browser attaches HttpOnly session cookies
    };

    const response = await fetch(url, config);

    // If 401 occurs and this isn't an auth endpoint or already retried, attempt transparent session refresh
    if (
      response.status === 401 &&
      !isRetry &&
      !endpoint.includes("/auth/login") &&
      !endpoint.includes("/auth/signup") &&
      !endpoint.includes("/auth/refresh") &&
      !endpoint.includes("/auth/logout")
    ) {
      const refreshed = await this.tryRefreshSession();
      if (refreshed) {
        return this.request<T>(endpoint, options, true);
      } else if (typeof window !== "undefined") {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    }

    if (response.status === 204) {
      return {} as T;
    }

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      let message = `Request failed with status ${response.status}`;
      if (typeof data?.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data?.detail)) {
        message = data.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ");
      } else if (typeof data?.message === "string") {
        message = data.message;
      }
      throw new ApiError(message, response.status, data);
    }

    return data as T;
  }

  public get<T>(endpoint: string, headers?: Record<string, string>): Promise<T> {
    return this.request<T>(endpoint, { method: "GET", headers });
  }

  public post<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    return this.request<T>(endpoint, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
      headers,
    });
  }

  public patch<T>(endpoint: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    return this.request<T>(endpoint, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
      headers,
    });
  }

  public delete<T>(endpoint: string, headers?: Record<string, string>): Promise<T> {
    return this.request<T>(endpoint, { method: "DELETE", headers });
  }

  /**
   * Securely streams and downloads authorized file exports (e.g. CSV or JSON) with cookie credentials.
   */
  public async downloadFile(endpoint: string, defaultFilename: string): Promise<void> {
    const url = `${BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
    const response = await fetch(url, {
      method: "GET",
      credentials: "include",
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      let message = `Export failed with status ${response.status}`;
      if (typeof data?.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data?.detail)) {
        message = data.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ");
      }
      throw new ApiError(message, response.status, data);
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition");
    let filename = defaultFilename;
    if (disposition && disposition.includes("filename=")) {
      const match = disposition.match(/filename="?([^";]+)"?/);
      if (match && match[1]) {
        filename = match[1];
      }
    }

    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(downloadUrl);
  }

  /**
   * Polls an asynchronous job run until status is completed or failed.
   */
  public async pollRun(
    runId: string,
    onProgress?: (run: Run) => void,
    intervalMs = 2000,
    maxAttempts = 1200
  ): Promise<Run> {
    let attempts = 0;
    while (attempts < maxAttempts) {
      const run = await this.get<Run>(`/runs/${runId}`);
      if (onProgress) {
        onProgress(run);
      }
      if (run.status === "completed" || run.status === "failed") {
        return run;
      }
      attempts++;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error("Polling timed out before job completed.");
  }
}

export const apiClient = new ApiClient();
