"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

interface UserData {
  id: string;
  username: string;
  email: string | null;
  role: string;
  createdAt: string;
}

interface InviteData {
  id: string;
  code: string;
  usedBy: string | null;
  usedAt: string | null;
  expiresAt: string | null;
  createdAt: string;
}

export default function AdminUsersPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [users, setUsers] = useState<UserData[]>([]);
  const [invites, setInvites] = useState<InviteData[]>([]);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

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
    if (!session?.user) return;
    fetchUsers();
    fetchInvites();
  }, [session]);

  async function fetchUsers() {
    const res = await fetch("/api/admin/users");
    setUsers(await res.json());
  }

  async function fetchInvites() {
    const res = await fetch("/api/admin/invite");
    setInvites(await res.json());
  }

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");

    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: newUsername,
        password: newPassword,
        role: newRole,
      }),
    });

    if (res.ok) {
      setSuccess(`User "${newUsername}" created`);
      setNewUsername("");
      setNewPassword("");
      fetchUsers();
    } else {
      const data = await res.json();
      setError(data.error);
    }
  }

  async function deleteUser(userId: string, username: string) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;

    await fetch("/api/admin/users", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId }),
    });
    fetchUsers();
  }

  async function generateInvite() {
    const res = await fetch("/api/admin/invite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expiresInDays: 7 }),
    });
    if (res.ok) fetchInvites();
  }

  if (status !== "authenticated") return null;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">User Management</h1>

      {/* Create User */}
      <div className="rounded-xl border border-border bg-bg-secondary p-6">
        <h2 className="mb-4 text-lg font-semibold">Create User</h2>
        <form onSubmit={createUser} className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Username"
            required
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm focus:border-accent focus:outline-none"
          />
          <input
            type="password"
            placeholder="Password"
            required
            minLength={6}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm focus:border-accent focus:outline-none"
          />
          <select
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            className="rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm focus:border-accent focus:outline-none"
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
          <button
            type="submit"
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Create
          </button>
        </form>
        {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        {success && <p className="mt-2 text-sm text-green-400">{success}</p>}
      </div>

      {/* Users List */}
      <div className="rounded-xl border border-border bg-bg-secondary p-6">
        <h2 className="mb-4 text-lg font-semibold">Users</h2>
        <div className="space-y-2">
          {users.map((user) => (
            <div
              key={user.id}
              className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
            >
              <div>
                <span className="font-medium">{user.username}</span>
                <span className="ml-2 rounded bg-bg-card px-2 py-0.5 text-xs">
                  {user.role}
                </span>
                {user.email && (
                  <span className="ml-2 text-xs text-text-secondary">
                    {user.email}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-text-secondary">
                  {new Date(user.createdAt).toLocaleDateString()}
                </span>
                {user.id !== session?.user?.id && (
                  <button
                    onClick={() => deleteUser(user.id, user.username)}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Invite Codes */}
      <div className="rounded-xl border border-border bg-bg-secondary p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Invite Codes</h2>
          <button
            onClick={generateInvite}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Generate Code
          </button>
        </div>
        <div className="space-y-2">
          {invites.length === 0 ? (
            <p className="text-sm text-text-secondary">
              No invite codes yet. Generate one to let someone register.
            </p>
          ) : (
            invites.map((invite) => (
              <div
                key={invite.id}
                className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
              >
                <div>
                  <code className="font-mono text-sm font-bold tracking-wider">
                    {invite.code}
                  </code>
                  {invite.usedBy && (
                    <span className="ml-2 text-xs text-text-secondary">
                      (used)
                    </span>
                  )}
                </div>
                <div className="text-xs text-text-secondary">
                  {invite.usedBy
                    ? `Used ${new Date(invite.usedAt!).toLocaleDateString()}`
                    : invite.expiresAt
                    ? `Expires ${new Date(invite.expiresAt).toLocaleDateString()}`
                    : "No expiry"}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
