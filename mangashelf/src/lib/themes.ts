export interface ThemeColors {
  bgPrimary: string;
  bgSecondary: string;
  bgCard: string;
  bgHover: string;
  accent: string;
  accentHover: string;
  textPrimary: string;
  textSecondary: string;
  border: string;
}

export interface ThemePreset {
  id: string;
  name: string;
  colors: ThemeColors;
}

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: "midnight",
    name: "Midnight",
    colors: {
      bgPrimary: "#0f0f0f",
      bgSecondary: "#1a1a2e",
      bgCard: "#16213e",
      bgHover: "#1f2b4d",
      accent: "#e94560",
      accentHover: "#ff6b81",
      textPrimary: "#eaeaea",
      textSecondary: "#a0a0b0",
      border: "#2a2a4a",
    },
  },
  {
    id: "amoled",
    name: "AMOLED Dark",
    colors: {
      bgPrimary: "#000000",
      bgSecondary: "#0a0a0a",
      bgCard: "#111111",
      bgHover: "#1a1a1a",
      accent: "#bb86fc",
      accentHover: "#d4a5ff",
      textPrimary: "#e0e0e0",
      textSecondary: "#888888",
      border: "#222222",
    },
  },
  {
    id: "ocean",
    name: "Ocean",
    colors: {
      bgPrimary: "#0b1622",
      bgSecondary: "#152232",
      bgCard: "#1a2d42",
      bgHover: "#223a52",
      accent: "#02a9ff",
      accentHover: "#4dc3ff",
      textPrimary: "#c8d6e5",
      textSecondary: "#8899aa",
      border: "#253a50",
    },
  },
  {
    id: "forest",
    name: "Forest",
    colors: {
      bgPrimary: "#0d1117",
      bgSecondary: "#161b22",
      bgCard: "#1c2333",
      bgHover: "#252d3d",
      accent: "#3fb950",
      accentHover: "#56d364",
      textPrimary: "#e6edf3",
      textSecondary: "#8b949e",
      border: "#30363d",
    },
  },
  {
    id: "sunset",
    name: "Sunset",
    colors: {
      bgPrimary: "#1a1015",
      bgSecondary: "#231620",
      bgCard: "#2d1c28",
      bgHover: "#3a2535",
      accent: "#ff6b35",
      accentHover: "#ff8c5a",
      textPrimary: "#f0e0e6",
      textSecondary: "#a08090",
      border: "#3a2838",
    },
  },
  {
    id: "nord",
    name: "Nord",
    colors: {
      bgPrimary: "#2e3440",
      bgSecondary: "#3b4252",
      bgCard: "#434c5e",
      bgHover: "#4c566a",
      accent: "#88c0d0",
      accentHover: "#8fbcbb",
      textPrimary: "#eceff4",
      textSecondary: "#d8dee9",
      border: "#4c566a",
    },
  },
  {
    id: "light",
    name: "Light",
    colors: {
      bgPrimary: "#f5f5f5",
      bgSecondary: "#ffffff",
      bgCard: "#ffffff",
      bgHover: "#f0f0f0",
      accent: "#e94560",
      accentHover: "#d63851",
      textPrimary: "#1a1a1a",
      textSecondary: "#666666",
      border: "#e0e0e0",
    },
  },
];

export function applyTheme(colors: ThemeColors) {
  const root = document.documentElement;
  root.style.setProperty("--color-bg-primary", colors.bgPrimary);
  root.style.setProperty("--color-bg-secondary", colors.bgSecondary);
  root.style.setProperty("--color-bg-card", colors.bgCard);
  root.style.setProperty("--color-bg-hover", colors.bgHover);
  root.style.setProperty("--color-accent", colors.accent);
  root.style.setProperty("--color-accent-hover", colors.accentHover);
  root.style.setProperty("--color-text-primary", colors.textPrimary);
  root.style.setProperty("--color-text-secondary", colors.textSecondary);
  root.style.setProperty("--color-border", colors.border);
}

export function getSavedTheme(): string {
  if (typeof window === "undefined") return "midnight";
  return localStorage.getItem("orvault-theme") || "midnight";
}

export function saveTheme(themeId: string) {
  localStorage.setItem("orvault-theme", themeId);
}

export function getSavedCustomColors(): ThemeColors | null {
  if (typeof window === "undefined") return null;
  const saved = localStorage.getItem("orvault-custom-colors");
  return saved ? JSON.parse(saved) : null;
}

export function saveCustomColors(colors: ThemeColors) {
  localStorage.setItem("orvault-custom-colors", JSON.stringify(colors));
}
