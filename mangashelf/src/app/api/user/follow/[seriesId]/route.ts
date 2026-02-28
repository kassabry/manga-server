import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { seriesId } = await params;

  // Toggle follow
  const existing = await prisma.follow.findUnique({
    where: { userId_seriesId: { userId: session.user.id, seriesId } },
  });

  if (existing) {
    await prisma.follow.delete({ where: { id: existing.id } });
    return NextResponse.json({ following: false });
  }

  await prisma.follow.create({
    data: { userId: session.user.id, seriesId },
  });

  return NextResponse.json({ following: true });
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ following: false });
  }

  const { seriesId } = await params;

  const existing = await prisma.follow.findUnique({
    where: { userId_seriesId: { userId: session.user.id, seriesId } },
  });

  return NextResponse.json({ following: !!existing });
}
