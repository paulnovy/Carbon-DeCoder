const configuredApiBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();

function defaultApiBase() {
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

export const API_BASE = configuredApiBase || defaultApiBase();
export const API_CONFIG = {
  baseUrl: API_BASE,
  configured: Boolean(configuredApiBase),
  source: configuredApiBase ? "NEXT_PUBLIC_API_BASE_URL" : "browser-host",
};

export function apiUrl(pathOrUrl) {
  if (!pathOrUrl) return API_BASE;
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return `${API_BASE}${pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`}`;
}

export async function apiFetch(pathOrUrl, { timeoutMs = 10000, ...options } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(apiUrl(pathOrUrl), {
      ...options,
      signal: options.signal || controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

export async function apiJson(pathOrUrl, { fallback, timeoutMs = 10000, ...options } = {}) {
  try {
    const response = await apiFetch(pathOrUrl, { ...options, timeoutMs });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail = payload?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message || detail?.code || payload?.message || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return await response.json();
  } catch (error) {
    if (fallback !== undefined) return fallback;
    throw error;
  }
}

export async function fetchJson(url, fallback = null, { timeoutMs = 2500, ...options } = {}) {
  try {
    return await apiJson(url, { ...options, fallback, timeoutMs });
  } catch {
    return fallback;
  }
}

export async function fetchApiHealth(apiBase = API_BASE, options) {
  const health = await fetchJson(`${apiBase}/health`, null, options);
  return health?.ok === true ? health : null;
}

export async function postJson(pathOrUrl, body, options = {}) {
  return apiJson(pathOrUrl, {
    ...options,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    body: JSON.stringify(body || {}),
  });
}
