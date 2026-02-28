"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, inviteCode }),
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
        <h1 className="mb-6 text-2xl font-bold">Register</h1>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-lg bg-red-500/10 px-4 py-2 text-sm text-red-400">
              {error}
            </div>
          )}
          <div>
            <label className="mb-1 block text-sm text-text-secondary">Invite Code</label>
            <input
              type="text"
              required
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
              placeholder="Enter invite code"
              className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm uppercase tracking-wider focus:border-accent focus:outline-none"
            />
          </div>
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
          <button
            type="submit"
            className="w-full rounded-lg bg-accent py-2.5 font-medium text-white hover:bg-accent-hover"
          >
            Create Account
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-text-secondary">
          Already have an account?{" "}
          <Link href="/login" className="text-accent hover:text-accent-hover">
            Sign In
          </Link>
        </p>
      </div>
    </div>
  );
}
