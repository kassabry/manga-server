import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";
import { randomBytes } from "crypto";

export async function GET() {
  const session = await auth();
  if (!session?.user || (session.user as { role: string }).role !== "admin") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  const codes = await prisma.inviteCode.findMany({
    orderBy: { createdAt: "desc" },
  });

  return NextResponse.json(codes);
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user || (session.user as { role: string }).role !== "admin") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  const body = await request.json().catch(() => ({}));
  const expiresInDays = (body as { expiresInDays?: number }).expiresInDays;

  const code = randomBytes(4).toString("hex").toUpperCase();

  const invite = await prisma.inviteCode.create({
    data: {
      code,
      createdBy: session.user.id,
      expiresAt: expiresInDays
        ? new Date(Date.now() + expiresInDays * 86400000)
        : null,
    },
  });

  return NextResponse.json(invite, { status: 201 });
}
