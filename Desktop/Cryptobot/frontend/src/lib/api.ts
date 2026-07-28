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

async function api<T>(
  path: string,
  options: RequestInit = {}
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
    setToken(null);
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
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
  executed: boolean;
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

export async function login(email: string, password: string): Promise<{ access_token: string }> {
  const res = await api<{ access_token: string; token_type: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return res;
}

export async function register(email: string, password: string, username: string) {
  return api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, username }),
  });
}

export async function fetchSignals(hours = 24): Promise<SignalsResponse> {
  return api<SignalsResponse>(`/trading/signals?hours=${hours}`);
}

export async function executeSignal(signalId: string): Promise<{ status: string; trade_id: string }> {
  return api(`/trading/signals/${signalId}/execute`, { method: "POST" });
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
