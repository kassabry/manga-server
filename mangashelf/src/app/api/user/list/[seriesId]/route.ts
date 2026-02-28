import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { seriesId } = await params;

  await prisma.listEntry.deleteMany({
    where: { userId: session.user.id, seriesId },
  });

  return NextResponse.json({ success: true });
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ entry: null });
  }

  const { seriesId } = await params;

  const entry = await prisma.listEntry.findUnique({
    where: { userId_seriesId: { userId: session.user.id, seriesId } },
  });

  return NextResponse.json({ entry });
}
