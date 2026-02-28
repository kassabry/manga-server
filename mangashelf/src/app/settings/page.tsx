"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import {
  THEME_PRESETS,
  applyTheme,
  getSavedTheme,
  saveTheme,
  getSavedCustomColors,
  saveCustomColors,
  type ThemeColors,
} from "@/lib/themes";

type LayoutMode = "single" | "double" | "double-manga" | "longstrip";
type FitMode = "width" | "height" | "original";
type ReadingDirection = "ltr" | "rtl";
type BgColor = "black" | "dark" | "white";

interface UserPrefs {
  theme: string;
  customColors: string | null;
  readerLayout: string;
  readerFit: string;
  readerDirection: string;
  readerBgColor: string;
  readerBrightness: number;
  autoHideToolbar: boolean;
  swipeEnabled: boolean;
  carouselColumns: number;
}

export default function SettingsPage() {
  const { data: session } = useSession();
  const [activeTheme, setActiveTheme] = useState("midnight");
  const [customColors, setCustomColors] = useState<ThemeColors>(THEME_PRESETS[0].colors);
  const [prefs, setPrefs] = useState<UserPrefs | null>(null);
  const [activeTab, setActiveTab] = useState<"appearance" | "reader" | "account">("appearance");

  // Password change state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordMsg, setPasswordMsg] = useState("");
  const [passwordError, setPasswordError] = useState(false);

  useEffect(() => {
    const saved = getSavedTheme();
    setActiveTheme(saved);
    if (saved === "custom") {
      const custom = getSavedCustomColors();
      if (custom) setCustomColors(custom);
    }
  }, []);

  // Fetch preferences from server
  useEffect(() => {
    if (!session?.user) return;
    fetch("/api/user/preferences")
      .then((r) => r.json())
      .then((data) => {
        setPrefs(data);
        // Apply server theme if different from local
        if (data.theme && data.theme !== getSavedTheme()) {
          if (data.theme === "custom" && data.customColors) {
            const colors = JSON.parse(data.customColors);
            applyTheme(colors);
            saveCustomColors(colors);
            setCustomColors(colors);
          } else {
            const preset = THEME_PRESETS.find((t) => t.id === data.theme);
            if (preset) applyTheme(preset.colors);
          }
          saveTheme(data.theme);
          setActiveTheme(data.theme);
        }
      });
  }, [session]);

  function updatePref(updates: Partial<UserPrefs>) {
    setPrefs((prev) => prev ? { ...prev, ...updates } : null);
    // Debounced save to server
    fetch("/api/user/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
  }

  function selectPreset(id: string) {
    const preset = THEME_PRESETS.find((t) => t.id === id);
    if (preset) {
      applyTheme(preset.colors);
      saveTheme(id);
      setActiveTheme(id);
      updatePref({ theme: id });
    }
  }

  function updateCustomColor(key: keyof ThemeColors, value: string) {
    const updated = { ...customColors, [key]: value };
    setCustomColors(updated);
    applyTheme(updated);
    saveCustomColors(updated);
    saveTheme("custom");
    setActiveTheme("custom");
    updatePref({ theme: "custom", customColors: JSON.stringify(updated) });
  }

  async function handlePasswordChange(e: React.FormEvent) {
    e.preventDefault();
    setPasswordMsg("");
    setPasswordError(false);
    const res = await fetch("/api/user/account", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currentPassword, newPassword }),
    });
    const data = await res.json();
    if (res.ok) {
      setPasswordMsg("Password changed successfully!");
      setPasswordError(false);
      setCurrentPassword("");
      setNewPassword("");
    } else {
      setPasswordMsg(data.error || "Failed to change password");
      setPasswordError(true);
    }
  }

  const colorLabels: Record<keyof ThemeColors, string> = {
    bgPrimary: "Background",
    bgSecondary: "Navbar / Cards BG",
    bgCard: "Card Fill",
    bgHover: "Hover State",
    accent: "Accent",
    accentHover: "Accent Hover",
    textPrimary: "Text",
    textSecondary: "Text Secondary",
    border: "Borders",
  };

  const tabs = [
    { id: "appearance" as const, label: "Appearance" },
    { id: "reader" as const, label: "Reader" },
    { id: "account" as const, label: "Account" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* Tab navigation */}
      <div className="flex gap-1 rounded-lg border border-border bg-bg-card p-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition ${
              activeTab === tab.id
                ? "bg-accent text-white"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Appearance Tab */}
      {activeTab === "appearance" && (
        <div className="space-y-8">
          {/* Theme Presets */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">Theme</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {THEME_PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  onClick={() => selectPreset(preset.id)}
                  className={`group relative overflow-hidden rounded-xl border-2 p-0.5 transition ${
                    activeTheme === preset.id
                      ? "border-accent"
                      : "border-border hover:border-text-secondary"
                  }`}
                >
                  <div
                    className="flex h-20 flex-col rounded-lg"
                    style={{ backgroundColor: preset.colors.bgPrimary }}
                  >
                    <div
                      className="flex h-5 items-center px-2"
                      style={{ backgroundColor: preset.colors.bgSecondary }}
                    >
                      <div className="h-1.5 w-8 rounded" style={{ backgroundColor: preset.colors.accent }} />
                    </div>
                    <div className="flex flex-1 gap-1 p-2">
                      <div className="h-full w-1/3 rounded" style={{ backgroundColor: preset.colors.bgCard }} />
                      <div className="flex flex-1 flex-col gap-1">
                        <div className="h-1.5 w-full rounded" style={{ backgroundColor: preset.colors.textPrimary }} />
                        <div className="h-1 w-2/3 rounded" style={{ backgroundColor: preset.colors.textSecondary }} />
                      </div>
                    </div>
                  </div>
                  <div className="px-2 py-1.5 text-center text-xs font-medium">{preset.name}</div>
                  {activeTheme === preset.id && (
                    <div className="absolute right-1 top-1 rounded-full bg-accent p-0.5">
                      <svg className="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                  )}
                </button>
              ))}
            </div>
          </section>

          {/* Custom Colors */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">Custom Colors</h2>
            <p className="mb-4 text-sm text-text-secondary">
              Pick any color to override the current theme. Changes apply instantly.
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {(Object.keys(colorLabels) as (keyof ThemeColors)[]).map((key) => (
                <div key={key} className="flex items-center gap-3 rounded-lg border border-border p-3">
                  <input
                    type="color"
                    value={customColors[key]}
                    onChange={(e) => updateCustomColor(key, e.target.value)}
                    className="h-8 w-8 cursor-pointer rounded border-0 bg-transparent"
                  />
                  <div>
                    <div className="text-sm font-medium">{colorLabels[key]}</div>
                    <div className="text-xs text-text-secondary">{customColors[key]}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Display Settings */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">Display</h2>
            <div className="rounded-lg border border-border p-4">
              <label className="mb-2 flex items-center justify-between text-sm">
                <span>Items per row in carousels</span>
                <span className="font-mono text-accent">{prefs?.carouselColumns || 5}</span>
              </label>
              <input
                type="range"
                min={3}
                max={8}
                value={prefs?.carouselColumns || 5}
                onChange={(e) => updatePref({ carouselColumns: parseInt(e.target.value) })}
                className="w-full accent-accent"
              />
              <div className="mt-1 flex justify-between text-[10px] text-text-secondary">
                <span>3</span><span>4</span><span>5</span><span>6</span><span>7</span><span>8</span>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* Reader Tab */}
      {activeTab === "reader" && prefs && (
        <div className="space-y-6">
          {/* Layout Mode */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Default Layout</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([["single", "Single Page"], ["double", "Double Page"], ["double-manga", "Double (Manga)"], ["longstrip", "Long Strip"]] as [LayoutMode, string][]).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => updatePref({ readerLayout: value })}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    prefs.readerLayout === value
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border hover:bg-bg-hover"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* Fit Mode */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Default Scaling</h2>
            <div className="grid grid-cols-3 gap-2">
              {([["width", "Fit Width"], ["height", "Fit Height"], ["original", "Original"]] as [FitMode, string][]).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => updatePref({ readerFit: value })}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    prefs.readerFit === value
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border hover:bg-bg-hover"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* Reading Direction */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Reading Direction</h2>
            <div className="grid grid-cols-2 gap-2">
              {([["ltr", "Left \u2192 Right"], ["rtl", "Right \u2192 Left"]] as [ReadingDirection, string][]).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => updatePref({ readerDirection: value })}
                  className={`rounded-lg border px-3 py-2 text-sm ${
                    prefs.readerDirection === value
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border hover:bg-bg-hover"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* Background Color */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Background Color</h2>
            <div className="grid grid-cols-3 gap-2">
              {([["black", "Black", "#000"], ["dark", "Dark", "#1a1a2e"], ["white", "White", "#f5f5f5"]] as [BgColor, string, string][]).map(([value, label, color]) => (
                <button
                  key={value}
                  onClick={() => updatePref({ readerBgColor: value })}
                  className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                    prefs.readerBgColor === value ? "ring-2 ring-accent" : "border-border"
                  }`}
                  style={{ backgroundColor: color, color: value === "white" ? "#000" : "#fff" }}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* Brightness */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Default Brightness</h2>
            <div className="rounded-lg border border-border p-4">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span>Brightness</span>
                <span className="font-mono text-accent">{prefs.readerBrightness}%</span>
              </div>
              <input
                type="range"
                min={20}
                max={150}
                value={prefs.readerBrightness}
                onChange={(e) => updatePref({ readerBrightness: parseInt(e.target.value) })}
                className="w-full accent-accent"
              />
            </div>
          </section>

          {/* Toggles */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Behavior</h2>
            <div className="space-y-3 rounded-lg border border-border p-4">
              <label className="flex items-center justify-between">
                <span className="text-sm">Swipe navigation</span>
                <button
                  onClick={() => updatePref({ swipeEnabled: !prefs.swipeEnabled })}
                  className={`h-6 w-11 rounded-full transition ${prefs.swipeEnabled ? "bg-accent" : "bg-bg-hover"}`}
                >
                  <div className={`h-5 w-5 rounded-full bg-white transition-transform ${prefs.swipeEnabled ? "translate-x-5" : "translate-x-0.5"}`} />
                </button>
              </label>
              <label className="flex items-center justify-between">
                <span className="text-sm">Auto-hide toolbar</span>
                <button
                  onClick={() => updatePref({ autoHideToolbar: !prefs.autoHideToolbar })}
                  className={`h-6 w-11 rounded-full transition ${prefs.autoHideToolbar ? "bg-accent" : "bg-bg-hover"}`}
                >
                  <div className={`h-5 w-5 rounded-full bg-white transition-transform ${prefs.autoHideToolbar ? "translate-x-5" : "translate-x-0.5"}`} />
                </button>
              </label>
            </div>
          </section>
        </div>
      )}

      {/* Account Tab */}
      {activeTab === "account" && (
        <div className="space-y-8">
          {/* User Info */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">Account Info</h2>
            <div className="rounded-lg border border-border p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-lg font-bold text-white">
                  {session?.user?.name?.[0]?.toUpperCase()}
                </div>
                <div>
                  <div className="font-medium">{session?.user?.name}</div>
                  <div className="text-xs text-text-secondary">
                    {(session?.user as { role?: string })?.role === "admin" ? "Administrator" : "User"}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Change Password */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">Change Password</h2>
            <form onSubmit={handlePasswordChange} className="space-y-4 rounded-lg border border-border p-4">
              {passwordMsg && (
                <div className={`rounded-lg px-4 py-2 text-sm ${passwordError ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"}`}>
                  {passwordMsg}
                </div>
              )}
              <div>
                <label className="mb-1 block text-sm text-text-secondary">Current Password</label>
                <input
                  type="password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-text-secondary">New Password</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none"
                />
              </div>
              <button
                type="submit"
                className="rounded-lg bg-accent px-6 py-2 font-medium text-white hover:bg-accent-hover"
              >
                Update Password
              </button>
            </form>
          </section>

          {/* About */}
          <section>
            <h2 className="mb-4 text-lg font-semibold">About</h2>
            <div className="rounded-lg border border-border p-4 text-sm text-text-secondary">
              <p className="font-medium text-text-primary">ORVault</p>
              <p className="mt-1">Self-hosted manga reader and tracker</p>
              <p className="mt-1">Built with Next.js, Prisma, and Tailwind CSS</p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
