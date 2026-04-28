import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const { seriesId } = await request.json();
  if (!seriesId) {
    return NextResponse.json({ error: "seriesId required" }, { status: 400 });
  }

  // Verify list belongs to user
  const list = await prisma.customList.findFirst({
    where: { id, userId: session.user.id },
  });
  if (!list) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const entry = await prisma.customListEntry.upsert({
    where: { listId_seriesId: { listId: id, seriesId } },
    update: {},
    create: { listId: id, seriesId },
  });

  // Bump updatedAt on the list
  await prisma.customList.update({ where: { id }, data: { updatedAt: new Date() } });

  return NextResponse.json(entry);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const seriesId = request.nextUrl.searchParams.get("seriesId");
  if (!seriesId) {
    return NextResponse.json({ error: "seriesId required" }, { status: 400 });
  }

  // Verify list belongs to user
  const list = await prisma.customList.findFirst({
    where: { id, userId: session.user.id },
  });
  if (!list) return NextResponse.json({ error: "Not found" }, { status: 404 });

  await prisma.customListEntry.deleteMany({
    where: { listId: id, seriesId },
  });

  return NextResponse.json({ success: true });
}
