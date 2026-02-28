import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { hash } from "bcryptjs";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { username, password, inviteCode } = body;

  if (!username || !password || !inviteCode) {
    return NextResponse.json(
      { error: "Username, password, and invite code required" },
      { status: 400 }
    );
  }

  if (password.length < 6) {
    return NextResponse.json(
      { error: "Password must be at least 6 characters" },
      { status: 400 }
    );
  }

  // Validate invite code
  const invite = await prisma.inviteCode.findUnique({
    where: { code: inviteCode },
  });

  if (!invite) {
    return NextResponse.json({ error: "Invalid invite code" }, { status: 400 });
  }

  if (invite.usedBy) {
    return NextResponse.json(
      { error: "Invite code already used" },
      { status: 400 }
    );
  }

  if (invite.expiresAt && invite.expiresAt < new Date()) {
    return NextResponse.json(
      { error: "Invite code expired" },
      { status: 400 }
    );
  }

  const normalizedUsername = username.toLowerCase();

  // Check username
  const existing = await prisma.user.findUnique({ where: { username: normalizedUsername } });
  if (existing) {
    return NextResponse.json(
      { error: "Username already taken" },
      { status: 409 }
    );
  }

  const passwordHash = await hash(password, 12);

  const user = await prisma.user.create({
    data: {
      username: normalizedUsername,
      passwordHash,
      role: "user",
    },
  });

  // Mark invite as used
  await prisma.inviteCode.update({
    where: { id: invite.id },
    data: { usedBy: user.id, usedAt: new Date() },
  });

  return NextResponse.json({ success: true }, { status: 201 });
}
