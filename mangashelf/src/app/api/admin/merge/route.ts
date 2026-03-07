import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

// POST /api/admin/merge — merge two series (source into target)
export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user || (session.user as { role: string }).role !== "admin") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  const body = await req.json();
  const { sourceId, targetId } = body;

  if (!sourceId || !targetId) {
    return NextResponse.json(
      { error: "sourceId and targetId are required" },
      { status: 400 }
    );
  }

  if (sourceId === targetId) {
    return NextResponse.json(
      { error: "Cannot merge a series into itself" },
      { status: 400 }
    );
  }

  const [source, target] = await Promise.all([
    prisma.series.findUnique({
      where: { id: sourceId },
      include: { _count: { select: { chapters: true } } },
    }),
    prisma.series.findUnique({
      where: { id: targetId },
      include: { _count: { select: { chapters: true } } },
    }),
  ]);

  if (!source) {
    return NextResponse.json({ error: "Source series not found" }, { status: 404 });
  }
  if (!target) {
    return NextResponse.json({ error: "Target series not found" }, { status: 404 });
  }

  // Move chapters from source to target
  const movedChapters = await prisma.chapter.updateMany({
    where: { seriesId: sourceId },
    data: { seriesId: targetId },
  });

  // Move SeriesPath entries
  await prisma.seriesPath.updateMany({
    where: { seriesId: sourceId },
    data: { seriesId: targetId },
  }).catch(() => {});

  // Delete conflicting follows (user follows both series — keep target's)
  const targetFollowUsers = await prisma.follow.findMany({
    where: { seriesId: targetId },
    select: { userId: true },
  });
  const followUserIds = targetFollowUsers.map((f) => f.userId);
  if (followUserIds.length > 0) {
    await prisma.follow.deleteMany({
      where: { seriesId: sourceId, userId: { in: followUserIds } },
    });
  }
  await prisma.follow.updateMany({
    where: { seriesId: sourceId },
    data: { seriesId: targetId },
  });

  // Delete conflicting list entries, move remaining
  const targetListUsers = await prisma.listEntry.findMany({
    where: { seriesId: targetId },
    select: { userId: true },
  });
  const listUserIds = targetListUsers.map((l) => l.userId);
  if (listUserIds.length > 0) {
    await prisma.listEntry.deleteMany({
      where: { seriesId: sourceId, userId: { in: listUserIds } },
    });
  }
  await prisma.listEntry.updateMany({
    where: { seriesId: sourceId },
    data: { seriesId: targetId },
  });

  // Delete the source series (any remaining relations cascade)
  await prisma.series.delete({ where: { id: sourceId } });

  // Update target's chapter count
  const totalChapters = await prisma.chapter.count({
    where: { seriesId: targetId },
  });
  await prisma.series.update({
    where: { id: targetId },
    data: { chapterCount: totalChapters },
  });

  return NextResponse.json({
    message: `Merged "${source.title}" into "${target.title}"`,
    chaptersMoved: movedChapters.count,
    totalChapters,
  });
}
