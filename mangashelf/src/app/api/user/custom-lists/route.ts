import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const lists = await prisma.customList.findMany({
    where: { userId: session.user.id },
    include: {
      entries: {
        select: { seriesId: true },
      },
    },
    orderBy: { updatedAt: "desc" },
  });

  return NextResponse.json(
    lists.map((l) => ({ ...l, entryCount: l.entries.length }))
  );
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { name } = await request.json();
  if (!name?.trim()) {
    return NextResponse.json({ error: "Name required" }, { status: 400 });
  }

  const list = await prisma.customList.create({
    data: { userId: session.user.id, name: name.trim() },
  });

  return NextResponse.json(list);
}
