"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";

interface ScanStatus {
  running: boolean;
  isScanning: boolean;
  lastScanTime: string | null;
  intervalMs: number;
}

export default function AdminPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [scanResult, setScanResult] = useState<{
    seriesAdded: number;
    seriesUpdated: number;
    chaptersAdded: number;
    errors: string[];
  } | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") router.push("/login");
    if (
      status === "authenticated" &&
      (session?.user as { role: string })?.role !== "admin"
    ) {
      router.push("/");
    }
  }, [status, session, router]);

  useEffect(() => {
    if (status !== "authenticated") return;
    fetch("/api/library/scan")
      .then((r) => r.json())
      .then(setScanStatus)
      .catch(() => {});
  }, [status]);

  if (status !== "authenticated") return null;

  async function handleScan() {
    setScanning(true);
    setScanResult(null);
    try {
      const res = await fetch("/api/library/scan", { method: "POST" });
      const data = await res.json();
      setScanResult(data);
      // Refresh status
      const statusRes = await fetch("/api/library/scan");
      setScanStatus(await statusRes.json());
    } catch {
      setScanResult({
        seriesAdded: 0,
        seriesUpdated: 0,
        chaptersAdded: 0,
        errors: ["Scan failed"],
      });
    }
    setScanning(false);
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Admin Panel</h1>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {/* Library Scan */}
        <div className="rounded-xl border border-border bg-bg-secondary p-6">
          <h2 className="mb-2 text-lg font-semibold">Library Scanner</h2>

          {/* Auto-scan status */}
          {scanStatus && (
            <div className="mb-4 rounded-lg border border-border bg-bg-primary p-3 text-xs">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    scanStatus.intervalMs > 0 ? "bg-green-500" : "bg-red-500"
                  }`}
                />
                <span>
                  Auto-scan:{" "}
                  {scanStatus.intervalMs > 0
                    ? `every ${scanStatus.intervalMs / 60000} min`
                    : "disabled"}
                </span>
              </div>
              {scanStatus.lastScanTime && (
                <div className="mt-1 text-text-secondary">
                  Last scan:{" "}
                  {new Date(scanStatus.lastScanTime).toLocaleString()}
                </div>
              )}
              {scanStatus.isScanning && (
                <div className="mt-1 text-accent">Scanning now...</div>
              )}
            </div>
          )}

          {/* Scan Interval Setting */}
          <div className="mb-4">
            <label className="mb-1.5 block text-xs text-text-secondary">Auto-Scan Interval</label>
            <select
              value={scanStatus?.intervalMs ?? 1800000}
              onChange={async (e) => {
                const val = parseInt(e.target.value);
                await fetch("/api/admin/config", {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ key: "scanIntervalMs", value: String(val) }),
                });
                // Refresh status
                const res = await fetch("/api/library/scan");
                setScanStatus(await res.json());
              }}
              className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm focus:border-accent focus:outline-none"
            >
              <option value="300000">5 minutes</option>
              <option value="900000">15 minutes</option>
              <option value="1800000">30 minutes</option>
              <option value="3600000">1 hour</option>
              <option value="7200000">2 hours</option>
              <option value="21600000">6 hours</option>
              <option value="0">Disabled</option>
            </select>
          </div>

          <p className="mb-4 text-sm text-text-secondary">
            Library is scanned automatically. Use this button for an immediate
            scan.
          </p>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="w-full rounded-lg bg-accent py-2 font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {scanning ? "Scanning..." : "Scan Now"}
          </button>
          {scanResult && (
            <div className="mt-4 space-y-1 text-sm">
              <p className="text-green-400">
                +{scanResult.seriesAdded} series, +{scanResult.chaptersAdded}{" "}
                chapters
              </p>
              <p className="text-text-secondary">
                {scanResult.seriesUpdated} updated
              </p>
              {scanResult.errors.length > 0 && (
                <div className="mt-2 text-red-400">
                  {scanResult.errors.map((e, i) => (
                    <p key={i}>{e}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* User Management */}
        <Link
          href="/admin/users"
          className="rounded-xl border border-border bg-bg-secondary p-6 hover:border-accent"
        >
          <h2 className="mb-2 text-lg font-semibold">User Management</h2>
          <p className="text-sm text-text-secondary">
            Create accounts, manage users, and generate invite codes.
          </p>
        </Link>

        {/* Library Info */}
        <Link
          href="/admin/library"
          className="rounded-xl border border-border bg-bg-secondary p-6 hover:border-accent"
        >
          <h2 className="mb-2 text-lg font-semibold">Library Info</h2>
          <p className="text-sm text-text-secondary">
            View library statistics and manage series data.
          </p>
        </Link>
      </div>
    </div>
  );
}
