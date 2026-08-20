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

function fmtPrice(p: number | null | undefined): string {
  if (p == null) return "—";
  if (p >= 1000) return p.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  if (p >= 1) return p.toFixed(2);
  if (p >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

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
      if (signal.direction !== "buy") return; // BUY-only trading phase
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
        fetchSignals(48, "buy"),
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

  async function handleExecute(signalId: string, paper: boolean) {
    setExecuting(paper ? `paper-${signalId}` : `real-${signalId}`);
    try {
      await executeSignal(signalId, paper);
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
        <p className="text-zinc-400 text-lg">Загрузка...</p>
      </div>
    );
  }

  const activeSignals = signals.filter((s) => !s.executed && s.direction === "buy");

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <header className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">TBX Trade Terminal</h1>
          <p className="text-zinc-500 text-sm">Сигналы SMC · только BUY · бессрочные фьючерсы Bybit</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => router.push("/settings")}
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm transition-colors"
          >
            Настройки
          </button>
          <button
            onClick={handleLogout}
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm transition-colors"
          >
            Выйти
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
          {error}
          <button onClick={() => setError("")} className="ml-3 underline">Скрыть</button>
        </div>
      )}

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-zinc-300">
          Активные сигналы
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({activeSignals.length})
          </span>
        </h2>

        {activeSignals.length === 0 ? (
          <div className="p-8 bg-zinc-900 rounded-xl border border-zinc-800 text-center">
            <p className="text-zinc-500">Нет активных сигналов. Ждём закрытия часовой свечи...</p>
            <p className="text-zinc-700 text-xs mt-2">Движок анализирует 16 пар каждый час</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {activeSignals.map((s) => (
              <div
                key={s.id}
                className="p-4 bg-zinc-900 rounded-xl border border-zinc-800 hover:border-zinc-700 transition-colors"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="text-xl font-extrabold tracking-wide font-mono text-white">
                      {s.symbol}
                    </span>
                    <span className="text-xs px-2 py-1 rounded bg-green-500/20 text-green-400 font-bold">
                      LONG
                    </span>
                    <span className="text-xs px-2 py-1 rounded bg-zinc-800 text-zinc-400">
                      уверенность {s.confidence}%
                    </span>
                    <span className="text-xs text-zinc-600">{fmtTime(s.created_at)}</span>
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm mb-3">
                  <div className="bg-zinc-800/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] uppercase text-zinc-500">Вход</p>
                    <p className="font-mono font-semibold">{fmtPrice(s.entry)}</p>
                  </div>
                  <div className="bg-zinc-800/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] uppercase text-zinc-500">Стоп-лосс</p>
                    <p className="font-mono font-semibold text-red-400">{fmtPrice(s.stop_loss)}</p>
                  </div>
                  <div className="bg-zinc-800/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] uppercase text-zinc-500">Зона стопа</p>
                    <p className="font-mono font-semibold">
                      {s.stop_zone_pct != null ? `${s.stop_zone_pct}%` : "—"}
                    </p>
                  </div>
                  <div className="bg-zinc-800/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] uppercase text-zinc-500">RR</p>
                    <p className="font-mono font-semibold text-green-400">
                      {s.rr != null ? `1:${s.rr}` : "—"}
                    </p>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex gap-2">
                    {s.take_profit?.map((tp: number, i: number) => (
                      <span key={i} className="text-xs bg-zinc-800 px-2 py-0.5 rounded font-mono text-green-300">
                        TP{i + 1}: {fmtPrice(tp)}
                      </span>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleExecute(s.id, true)}
                      disabled={executing !== null}
                      className="px-4 py-2 rounded-lg font-medium text-sm bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                      {executing === `paper-${s.id}` ? "..." : "Бумажно (Paper)"}
                    </button>
                    <button
                      onClick={() => handleExecute(s.id, false)}
                      disabled={executing !== null}
                      className="px-4 py-2 rounded-lg font-medium text-sm bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                      {executing === `real-${s.id}` ? "..." : "Реально (Bybit)"}
                    </button>
                  </div>
                </div>

                {s.metadata?.ai_analysis ? (
                  <details className="mt-3 text-sm">
                    <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">
                      📊 Аналитика ИИ (DeepSeek)
                    </summary>
                    <p className="mt-2 text-zinc-300 whitespace-pre-wrap bg-zinc-800/40 rounded-lg p-3">
                      {s.metadata.ai_analysis}
                    </p>
                  </details>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-zinc-300">
          Открытые позиции
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({positions.length})
          </span>
        </h2>
        {positions.length === 0 ? (
          <p className="text-zinc-600 text-sm p-4 bg-zinc-900 rounded-xl border border-zinc-800">
            Нет открытых позиций
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-left border-b border-zinc-800">
                  <th className="py-2 px-3">Инструмент</th>
                  <th className="py-2 px-3">Сторона</th>
                  <th className="py-2 px-3">Вход</th>
                  <th className="py-2 px-3">Объём</th>
                  <th className="py-2 px-3">PnL</th>
                  <th className="py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className="border-b border-zinc-800/50 hover:bg-zinc-900">
                    <td className="py-3 px-3 font-mono font-semibold">{p.symbol}</td>
                    <td className={`py-3 px-3 ${p.side === "buy" ? "text-green-400" : "text-red-400"}`}>
                      {p.side === "buy" ? "LONG" : "SHORT"}
                    </td>
                    <td className="py-3 px-3 font-mono">{fmtPrice(p.entry_price)}</td>
                    <td className="py-3 px-3 font-mono">{p.size}</td>
                    <td className={`py-3 px-3 font-mono ${(p.pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${p.pnl?.toFixed(2) || "0.00"}
                    </td>
                    <td className="py-3 px-3">
                      <button
                        onClick={() => handleClose(p.id)}
                        className="px-3 py-1 bg-zinc-700 hover:bg-zinc-600 rounded text-xs transition-colors"
                      >
                        Закрыть
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
          История сделок
          <span className="ml-2 text-sm text-zinc-600 font-normal">
            ({trades.length})
          </span>
        </h2>
        {trades.length === 0 ? (
          <p className="text-zinc-600 text-sm p-4 bg-zinc-900 rounded-xl border border-zinc-800">
            Сделок пока нет
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-left border-b border-zinc-800">
                  <th className="py-2 px-3">Инструмент</th>
                  <th className="py-2 px-3">Сторона</th>
                  <th className="py-2 px-3">Вход</th>
                  <th className="py-2 px-3">Выход</th>
                  <th className="py-2 px-3">PnL</th>
                  <th className="py-2 px-3">Статус</th>
                  <th className="py-2 px-3">Дата</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} className="border-b border-zinc-800/50 hover:bg-zinc-900">
                    <td className="py-3 px-3 font-mono font-semibold">{t.symbol}</td>
                    <td className={`py-3 px-3 ${t.side === "buy" ? "text-green-400" : "text-red-400"}`}>
                      {t.side === "buy" ? "LONG" : "SHORT"}
                    </td>
                    <td className="py-3 px-3 font-mono">{fmtPrice(t.entry_price)}</td>
                    <td className="py-3 px-3 font-mono">
                      {t.exit_price ? fmtPrice(t.exit_price) : "-"}
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
