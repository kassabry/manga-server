import { resolve } from "path";
import { scanLibrary } from "./scanner";
import { prisma } from "./db";

let scanInterval: ReturnType<typeof setInterval> | null = null;
let lastScanTime: Date | null = null;
let isScanning = false;
let currentIntervalMs = 1800000; // 30 min default

async function getConfiguredInterval(): Promise<number> {
  try {
    const config = await prisma.siteConfig.findUnique({ where: { key: "scanIntervalMs" } });
    if (config) return parseInt(config.value) || 1800000;
  } catch {
    // DB might not be ready yet
  }
  return parseInt(process.env.SCAN_INTERVAL_MS || "1800000");
}

async function runScan() {
  if (isScanning) return;
  isScanning = true;

  const libraryPath = resolve(process.env.LIBRARY_PATH || "../library");
  try {
    console.log(`[AutoScan] Starting library scan at ${new Date().toISOString()}`);
    const result = await scanLibrary(libraryPath);
    lastScanTime = new Date();
    console.log(
      `[AutoScan] Complete: +${result.seriesAdded} series, +${result.chaptersAdded} chapters, ${result.seriesUpdated} updated`
    );
    if (result.errors.length > 0) {
      console.warn(`[AutoScan] ${result.errors.length} errors:`, result.errors.slice(0, 5));
    }
  } catch (err) {
    console.error("[AutoScan] Scan failed:", err);
  } finally {
    isScanning = false;
  }
}

export async function startAutoScan() {
  if (scanInterval) return;

  currentIntervalMs = await getConfiguredInterval();

  if (currentIntervalMs <= 0) {
    console.log("[AutoScan] Auto-scan disabled");
    return;
  }

  console.log(`[AutoScan] Starting auto-scan every ${currentIntervalMs / 60000} minutes`);

  // Run initial scan after a short delay
  setTimeout(() => runScan(), 5000);

  scanInterval = setInterval(() => runScan(), currentIntervalMs);
}

export function stopAutoScan() {
  if (scanInterval) {
    clearInterval(scanInterval);
    scanInterval = null;
  }
}

export async function updateScanInterval(newIntervalMs: number) {
  stopAutoScan();
  currentIntervalMs = newIntervalMs;

  // Save to database
  await prisma.siteConfig.upsert({
    where: { key: "scanIntervalMs" },
    update: { value: String(newIntervalMs) },
    create: { key: "scanIntervalMs", value: String(newIntervalMs) },
  });

  if (newIntervalMs > 0) {
    console.log(`[AutoScan] Interval updated to ${newIntervalMs / 60000} minutes`);
    scanInterval = setInterval(() => runScan(), newIntervalMs);
  } else {
    console.log("[AutoScan] Auto-scan disabled");
  }
}

export async function getAutoScanStatus() {
  // Always read interval from DB to avoid stale module-level state
  // across Next.js API route worker contexts
  let intervalMs = currentIntervalMs;
  try {
    const config = await prisma.siteConfig.findUnique({ where: { key: "scanIntervalMs" } });
    if (config) intervalMs = parseInt(config.value) || 1800000;
  } catch {
    // DB might not be ready
  }
  return {
    running: scanInterval !== null,
    isScanning,
    lastScanTime,
    intervalMs,
  };
}
