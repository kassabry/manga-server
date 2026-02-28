"use client";

import { useEffect } from "react";
import { useSession } from "next-auth/react";
import {
  THEME_PRESETS,
  applyTheme,
  getSavedTheme,
  saveTheme,
  getSavedCustomColors,
  saveCustomColors,
} from "@/lib/themes";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();

  // Apply local theme immediately (prevents flash)
  useEffect(() => {
    const themeId = getSavedTheme();
    if (themeId === "custom") {
      const custom = getSavedCustomColors();
      if (custom) applyTheme(custom);
    } else {
      const preset = THEME_PRESETS.find((t) => t.id === themeId);
      if (preset) applyTheme(preset.colors);
    }
  }, []);

  // Sync with server preferences when logged in
  useEffect(() => {
    if (!session?.user) return;
    fetch("/api/user/preferences")
      .then((r) => r.json())
      .then((prefs) => {
        if (!prefs?.theme) return;
        const localTheme = getSavedTheme();
        if (prefs.theme !== localTheme) {
          if (prefs.theme === "custom" && prefs.customColors) {
            try {
              const colors = JSON.parse(prefs.customColors);
              applyTheme(colors);
              saveCustomColors(colors);
            } catch {}
          } else {
            const preset = THEME_PRESETS.find((t) => t.id === prefs.theme);
            if (preset) applyTheme(preset.colors);
          }
          saveTheme(prefs.theme);
        }
      })
      .catch(() => {});
  }, [session]);

  return <>{children}</>;
}
