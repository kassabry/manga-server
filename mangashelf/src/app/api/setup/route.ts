import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { hash } from "bcryptjs";

export async function GET() {
  const userCount = await prisma.user.count();
  return NextResponse.json({ needsSetup: userCount === 0 });
}

export async function POST(request: NextRequest) {
  // Only allow if no users exist
  const userCount = await prisma.user.count();
  if (userCount > 0) {
    return NextResponse.json(
      { error: "Setup already completed" },
      { status: 400 }
    );
  }

  const body = await request.json();
  const { username, password } = body;

  if (!username || !password) {
    return NextResponse.json(
      { error: "Username and password required" },
      { status: 400 }
    );
  }

  if (password.length < 6) {
    return NextResponse.json(
      { error: "Password must be at least 6 characters" },
      { status: 400 }
    );
  }

  const normalizedUsername = username.toLowerCase();
  const passwordHash = await hash(password, 12);

  await prisma.user.create({
    data: {
      username: normalizedUsername,
      passwordHash,
      role: "admin",
    },
  });

  return NextResponse.json({ success: true }, { status: 201 });
}
