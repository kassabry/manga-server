"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SetupPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    fetch("/api/setup")
      .then((r) => r.json())
      .then((data) => {
        if (!data.needsSetup) router.replace("/");
        else setLoading(false);
      });
  }, [router]);

  if (loading) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }

    const res = await fetch("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    const data = await res.json();
    if (res.ok) {
      router.push("/login");
    } else {
      setError(data.error);
    }
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <div className="w-full max-w-md rounded-xl border border-border bg-bg-secondary p-8">
        <h1 className="mb-2 text-2xl font-bold text-accent">MangaShelf Setup</h1>
        <p className="mb-6 text-sm text-text-secondary">
          Create your admin account to get started.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-lg bg-red-500/10 px-4 py-2 text-sm text-red-400">
              {error}
            </div>
          )}
          <div>
            <label className="mb-1 block text-sm text-text-secondary">Username</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-text-secondary">Password</label>
            <input
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-text-secondary">Confirm Password</label>
            <input
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="w-full rounded-lg bg-accent py-2.5 font-medium text-white hover:bg-accent-hover"
          >
            Create Admin Account
          </button>
        </form>
      </div>
    </div>
  );
}
