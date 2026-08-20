const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

let authToken: string | null = null;

export function setToken(token: string | null) {
  authToken = token;
  if (token) {
    localStorage.setItem("tbx_token", token);
  } else {
    localStorage.removeItem("tbx_token");
  }
}

export function getToken(): string | null {
  if (!authToken) {
    authToken = localStorage.getItem("tbx_token");
  }
  return authToken;
}

export function setRefreshToken(token: string | null) {
  if (token) {
    localStorage.setItem("tbx_refresh_token", token);
  } else {
    localStorage.removeItem("tbx_refresh_token");
  }
}

function getRefreshToken(): string | null {
  return localStorage.getItem("tbx_refresh_token");
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  // deduplicate: parallel 401s must trigger a single refresh request
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getRefreshToken();
      if (!refreshToken) return false;
      try {
        const res = await fetch(`${API_BASE}/auth/token/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        setToken(data.access_token);
        setRefreshToken(data.refresh_token);
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function logoutToLogin(): void {
  setToken(null);
  setRefreshToken(null);
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}

async function api<T>(
  path: string,
  options: RequestInit = {},
  isRetry = false
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    if (!isRetry && (await tryRefresh())) {
      return api<T>(path, options, true);
    }
    logoutToLogin();
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

export interface Signal {
  id: string;
  symbol: string;
  direction: string;
  entry: number;
  stop_loss: number;
  take_profit: number[];
  confidence: number;
  stop_zone_pct?: number;
  rr?: number;
  executed: boolean;
  metadata?: { ai_analysis?: string };
  created_at: string;
}

export interface Position {
  id: string;
  symbol: string;
  exchange: string;
  side: string;
  entry_price: number;
  size: number;
  pnl: number | null;
  created_at: string;
}

export interface Trade {
  id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  size: number;
  pnl: number | null;
  pnl_pct: number | null;
  status: string;
  created_at: string;
  closed_at: string | null;
}

export interface SignalsResponse {
  count: number;
  signals: Signal[];
}

export interface PositionsResponse {
  count: number;
  positions: Position[];
}

export interface TradesResponse {
  count: number;
  trades: Trade[];
}

export async function login(
  email: string,
  password: string
): Promise<{ access_token: string; refresh_token: string }> {
  const res = await api<{ access_token: string; refresh_token: string; token_type: string }>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }
  );
  setRefreshToken(res.refresh_token);
  return res;
}

export async function register(
  email: string,
  password: string,
  username: string
): Promise<{ access_token: string; refresh_token: string }> {
  const res = await api<{ access_token: string; refresh_token: string; token_type: string }>(
    "/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ email, password, username }),
    }
  );
  setRefreshToken(res.refresh_token);
  return res;
}

export async function fetchSignals(hours = 24, direction?: string): Promise<SignalsResponse> {
  const dir = direction ? `&direction=${direction}` : "";
  return api<SignalsResponse>(`/trading/signals?hours=${hours}${dir}`);
}

export async function executeSignal(
  signalId: string,
  paper = true
): Promise<{ status: string; trade_id: string }> {
  return api(`/trading/signals/${signalId}/execute`, {
    method: "POST",
    body: JSON.stringify({ paper }),
  });
}

export async function fetchPositions(): Promise<PositionsResponse> {
  return api<PositionsResponse>("/trading/positions");
}

export async function fetchTrades(limit = 50): Promise<TradesResponse> {
  return api<TradesResponse>(`/trading/trades?limit=${limit}`);
}

export async function closePosition(tradeId: string) {
  return api(`/trading/positions/${tradeId}/close`, { method: "POST" });
}

export async function fetchUserProfile(): Promise<{ id: string; email: string; username: string }> {
  return api("/users/me");
}

export async function updateUserSettings(settings: {
  exchange?: string;
  api_key?: string;
  secret?: string;
  risk_per_trade_pct?: number;
}) {
  if (settings.api_key && settings.secret && settings.exchange) {
    return api("/users/me/exchange-keys", {
      method: "PUT",
      body: JSON.stringify({
        exchange: settings.exchange,
        api_key: settings.api_key,
        secret: settings.secret,
        risk_per_trade_pct: settings.risk_per_trade_pct,
      }),
    });
  }
  return api("/users/me", {
    method: "PATCH",
    body: JSON.stringify({}),
  });
}

export async function getExchangeKeys(): Promise<{ exchange: string; api_key_masked: string }[]> {
  return api("/users/me/exchange-keys");
}

export function createSignalStream(onSignal: (signal: Signal) => void): EventSource | null {
  const token = getToken();
  if (!token || typeof window === "undefined") return null;

  const source = new EventSource(
    `${API_BASE}/trading/signals/stream?token=${encodeURIComponent(token)}`
  );
  source.onmessage = (event) => {
    try {
      onSignal(JSON.parse(event.data));
    } catch {
      // keepalive or malformed frame — ignore
    }
  };
  return source;
}
