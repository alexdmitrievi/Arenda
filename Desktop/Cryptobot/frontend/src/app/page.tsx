"use client";

import { useEffect, useState } from "react";
import {
  fetchSignals,
  fetchPositions,
  fetchTrades,
  executeSignal,
  closePosition,
  createSignalStream,
  getToken,
  setToken,
  Signal,
  Position,
  Trade,
} from "@/lib/api";
import { useRouter } from "next/navigation";

export default function Dashboard() {
  const router = useRouter();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [executing, setExecuting] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    loadData();
    // SSE delivers new signals instantly; polling stays as a slow fallback
    const stream = createSignalStream((signal) => {
      setSignals((prev) =>
        prev.some((s) => s.id === signal.id) ? prev : [signal, ...prev]
      );
    });
    const interval = setInterval(loadData, 120000);
    return () => {
      clearInterval(interval);
      stream?.close();
    };
  }, []);

  async function loadData() {
    try {
      const [sigRes, posRes, tradeRes] = await Promise.all([
        fetchSignals(48),
        fetchPositions(),
        fetchTrades(20),
      ]);
      setSignals(sigRes.signals);
      setPositions(posRes.positions);
      setTrades(tradeRes.trades);
      setError("");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load data";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleExecute(signalId: string) {
    setExecuting(signalId);
    try {
      await executeSignal(signalId);
      await loadData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Execution failed";
      setError(msg);
    } finally {
      setExecuting(null);
    }
  }

  async function handleClose(tradeId: string) {
    try {
      await closePosition(tradeId);
      await loadData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Close failed";
      setError(msg);
    }
  }

  function handleLogout() {
    setToken(null);
    router.push("/login");
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-zinc-400 text-lg">Loading...</p>
      </div>
    );
  }

  const activeSignals = signals.filter((s) => !s.executed);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <header className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">TBX Trade Terminal</h1>
          <p className="text-zinc-500 text-sm">SMC Signals & Execution</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => router.push("/settings")}
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm transition-colors"
          >
            Settings
          </button>
          <button
            onClick={handleLogout}
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm transition-colors"
          >
            Logout
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
          {error}
          <button onClick={() => setError("")} className="ml-3 underline">Dismiss</button>
        </div>
      )}

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-zinc-300">
          Active Signals
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({activeSignals.length})
          </span>
        </h2>

        {activeSignals.length === 0 ? (
          <div className="p-8 bg-zinc-900 rounded-xl border border-zinc-800 text-center">
            <p className="text-zinc-500">No active signals. Waiting for SMC analysis...</p>
            <p className="text-zinc-700 text-xs mt-2">Signals update every 1H on candle close</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {activeSignals.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between p-4 bg-zinc-900 rounded-xl border border-zinc-800 hover:border-zinc-700 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <span
                    className={`text-lg font-bold ${
                      s.direction === "buy" ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {s.direction === "buy" ? "LONG" : "SHORT"}
                  </span>
                  <div>
                    <p className="font-semibold">{s.symbol}</p>
                    <p className="text-xs text-zinc-500">
                      Entry: ${s.entry?.toFixed(2)} | SL: ${s.stop_loss?.toFixed(2)}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {s.take_profit?.map((tp: number, i: number) => (
                      <span key={i} className="text-xs bg-zinc-800 px-2 py-0.5 rounded">
                        TP{i + 1}: ${tp.toFixed(2)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs bg-zinc-800 px-2 py-1 rounded font-mono">
                    {s.confidence}%
                  </span>
                  <button
                    onClick={() => handleExecute(s.id)}
                    disabled={executing === s.id}
                    className={`px-5 py-2 rounded-lg font-medium text-sm transition-all ${
                      s.direction === "buy"
                        ? "bg-green-600 hover:bg-green-500"
                        : "bg-red-600 hover:bg-red-500"
                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                  >
                    {executing === s.id ? "..." : "Execute"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-zinc-300">
          Open Positions
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({positions.length})
          </span>
        </h2>
        {positions.length === 0 ? (
          <p className="text-zinc-600 text-sm p-4 bg-zinc-900 rounded-xl border border-zinc-800">
            No open positions
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-left border-b border-zinc-800">
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3">Entry</th>
                  <th className="py-2 px-3">Size</th>
                  <th className="py-2 px-3">PnL</th>
                  <th className="py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-900">
                    <td className="py-3 px-3 font-medium">{p.symbol}</td>
                    <td className={`py-3 px-3 ${p.side === "buy" ? "text-green-400" : "text-red-400"}`}>
                      {p.side.toUpperCase()}
                    </td>
                    <td className="py-3 px-3 font-mono">${p.entry_price.toFixed(2)}</td>
                    <td className="py-3 px-3 font-mono">{p.size}</td>
                    <td className={`py-3 px-3 font-mono ${(p.pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${p.pnl?.toFixed(2) || "0.00"}
                    </td>
                    <td className="py-3 px-3">
                      <button
                        onClick={() => handleClose(p.id)}
                        className="px-3 py-1 bg-zinc-700 hover:bg-zinc-600 rounded text-xs transition-colors"
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-4 text-zinc-300">
          Trade History
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({trades.length})
          </span>
        </h2>
        {trades.length === 0 ? (
          <p className="text-zinc-600 text-sm p-4 bg-zinc-900 rounded-xl border border-zinc-800">
            No trades yet
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-left border-b border-zinc-800">
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3">Entry</th>
                  <th className="py-2 px-3">Exit</th>
                  <th className="py-2 px-3">PnL</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} className="border-b border-zinc-800/50 hover:bg-zinc-900">
                    <td className="py-3 px-3 font-medium">{t.symbol}</td>
                    <td className={`py-3 px-3 ${t.side === "buy" ? "text-green-400" : "text-red-400"}`}>
                      {t.side.toUpperCase()}
                    </td>
                    <td className="py-3 px-3 font-mono">${t.entry_price.toFixed(2)}</td>
                    <td className="py-3 px-3 font-mono">
                      {t.exit_price ? `$${t.exit_price.toFixed(2)}` : "-"}
                    </td>
                    <td className={`py-3 px-3 font-mono ${(t.pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {t.pnl != null ? `$${t.pnl.toFixed(2)}` : "-"}
                      {t.pnl_pct != null && (
                        <span className="text-xs ml-1">
                          ({t.pnl_pct > 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%)
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${
                          t.status === "open"
                            ? "bg-blue-500/20 text-blue-400"
                            : t.status === "closed"
                            ? "bg-zinc-700 text-zinc-400"
                            : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {t.status}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-zinc-500 text-xs">
                      {t.created_at ? new Date(t.created_at).toLocaleDateString("ru-RU") : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
