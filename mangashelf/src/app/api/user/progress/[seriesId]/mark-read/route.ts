import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { seriesId } = await params;
  const body = await request.json();
  const { upToChapterNumber } = body;

  if (typeof upToChapterNumber !== "number") {
    return NextResponse.json({ error: "Missing upToChapterNumber" }, { status: 400 });
  }

  // Fetch all chapters in this series with number <= upToChapterNumber
  const chapters = await prisma.chapter.findMany({
    where: {
      seriesId,
      number: { lte: upToChapterNumber },
    },
    select: { id: true, pageCount: true },
  });

  if (chapters.length === 0) {
    return NextResponse.json({ marked: 0 });
  }

  // Upsert progress for every matched chapter in a single transaction
  await prisma.$transaction(
    chapters.map((ch) =>
      prisma.readProgress.upsert({
        where: {
          userId_chapterId: { userId: session.user.id, chapterId: ch.id },
        },
        update: {
          completed: true,
          page: Math.max(0, ch.pageCount - 1),
          readAt: new Date(),
        },
        create: {
          userId: session.user.id,
          chapterId: ch.id,
          completed: true,
          page: Math.max(0, ch.pageCount - 1),
        },
      })
    )
  );

  return NextResponse.json({ marked: chapters.length });
}
