"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchUserProfile, updateUserSettings, getExchangeKeys, getToken } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<{ email: string; username: string } | null>(null);
  const [bybitKey, setBybitKey] = useState("");
  const [bybitSecret, setBybitSecret] = useState("");
  const [existingKeys, setExistingKeys] = useState<string[]>([]);
  const [riskPct, setRiskPct] = useState("2");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    loadProfile();
  }, []);

  async function loadProfile() {
    try {
      const [p, keys] = await Promise.all([fetchUserProfile(), getExchangeKeys()]);
      setProfile(p);
      setExistingKeys(keys.map((k: { exchange: string }) => k.exchange));
    } catch {
      router.push("/login");
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage("");

    try {
      if (bybitKey && bybitSecret) {
        await updateUserSettings({
          exchange: "bybit",
          api_key: bybitKey,
          secret: bybitSecret,
        });
      }

      setMessage("Settings saved");
      setBybitKey("");
      setBybitSecret("");
      await loadProfile();
    } catch (e: unknown) {
      setMessage(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto px-4 py-10">
      <button
        onClick={() => router.push("/")}
        className="text-zinc-500 hover:text-zinc-300 text-sm mb-6 transition-colors"
      >
        ← Back to Dashboard
      </button>

      <h1 className="text-2xl font-bold mb-8">Settings</h1>

      {profile && (
        <div className="mb-8 p-4 bg-zinc-900 rounded-xl border border-zinc-800">
          <p className="text-sm text-zinc-400">Account</p>
          <p className="font-medium">{profile.email}</p>
          <p className="text-zinc-500 text-sm">@{profile.username}</p>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-5">
        {message && (
          <div
            className={`p-3 rounded-lg text-sm ${
              message === "Settings saved"
                ? "bg-green-500/10 border border-green-500/30 text-green-400"
                : "bg-red-500/10 border border-red-500/30 text-red-400"
            }`}
          >
            {message}
          </div>
        )}

        <div>
          <h2 className="text-lg font-semibold mb-3 text-zinc-300">Bybit API</h2>
          {existingKeys.includes("bybit") ? (
            <p className="text-sm text-green-400 mb-3">Bybit API keys configured</p>
          ) : (
            <p className="text-xs text-zinc-600 mb-3">
              Create an API key on Bybit with trading permissions.
            </p>
          )}

          <div className="space-y-3">
            <div>
              <label className="block text-sm text-zinc-400 mb-1">API Key</label>
              <input
                type="password"
                value={bybitKey}
                onChange={(e) => setBybitKey(e.target.value)}
                className="w-full px-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-lg focus:outline-none focus:border-zinc-600 text-zinc-100 transition-colors"
                placeholder="Enter new API key"
              />
            </div>
            <div>
              <label className="block text-sm text-zinc-400 mb-1">API Secret</label>
              <input
                type="password"
                value={bybitSecret}
                onChange={(e) => setBybitSecret(e.target.value)}
                className="w-full px-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-lg focus:outline-none focus:border-zinc-600 text-zinc-100 transition-colors"
                placeholder="Enter new API secret"
              />
            </div>
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold mb-3 text-zinc-300">Risk Management</h2>
          <div>
            <label className="block text-sm text-zinc-400 mb-1">Risk per trade (%)</label>
            <input
              type="number"
              value={riskPct}
              onChange={(e) => setRiskPct(e.target.value)}
              min="0.1"
              max="10"
              step="0.1"
              className="w-full px-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-lg focus:outline-none focus:border-zinc-600 text-zinc-100 transition-colors"
            />
            <p className="text-xs text-zinc-600 mt-1">Recommended: 1-2% per trade</p>
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="w-full py-2.5 bg-white text-black font-medium rounded-lg hover:bg-zinc-200 transition-colors disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </form>
    </div>
  );
}
