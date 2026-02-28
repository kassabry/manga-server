import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const status = request.nextUrl.searchParams.get("status");

  if (status === "reading") {
    // Auto-populate: find series with active (non-completed) read progress
    // Union with manual "reading" entries
    const [manualEntries, progressSeries] = await Promise.all([
      prisma.listEntry.findMany({
        where: { userId: session.user.id, status: "reading" },
        include: {
          series: {
            select: {
              id: true, title: true, slug: true, type: true,
              coverPath: true, chapterCount: true, status: true,
            },
          },
        },
        orderBy: { updatedAt: "desc" },
      }),
      // Find series where user has non-completed progress
      prisma.readProgress.findMany({
        where: {
          userId: session.user.id,
          completed: false,
        },
        include: {
          chapter: {
            include: {
              series: {
                select: {
                  id: true, title: true, slug: true, type: true,
                  coverPath: true, chapterCount: true, status: true,
                },
              },
            },
          },
        },
        orderBy: { readAt: "desc" },
      }),
    ]);

    // Merge: manual entries + progress-based entries (deduplicated)
    const seenIds = new Set(manualEntries.map((e) => e.series.id));
    const result = [...manualEntries];

    for (const prog of progressSeries) {
      if (!seenIds.has(prog.chapter.series.id)) {
        seenIds.add(prog.chapter.series.id);
        result.push({
          id: `auto-${prog.chapter.series.id}`,
          userId: session.user.id,
          seriesId: prog.chapter.series.id,
          status: "reading",
          rating: null,
          createdAt: prog.readAt,
          updatedAt: prog.readAt,
          series: prog.chapter.series,
        } as any);
      }
    }

    return NextResponse.json(result);
  }

  const where: Record<string, unknown> = { userId: session.user.id };
  if (status) where.status = status;

  const entries = await prisma.listEntry.findMany({
    where,
    include: {
      series: {
        select: {
          id: true, title: true, slug: true, type: true,
          coverPath: true, chapterCount: true, status: true,
        },
      },
    },
    orderBy: { updatedAt: "desc" },
  });

  return NextResponse.json(entries);
}

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();
  const { seriesId, status, rating } = body;

  if (!seriesId || !status) {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }

  const entry = await prisma.listEntry.upsert({
    where: {
      userId_seriesId: { userId: session.user.id, seriesId },
    },
    update: { status, rating },
    create: {
      userId: session.user.id,
      seriesId,
      status,
      rating,
    },
  });

  return NextResponse.json(entry);
}

export async function DELETE(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const seriesId = request.nextUrl.searchParams.get("seriesId");
  if (!seriesId) {
    return NextResponse.json({ error: "Missing seriesId" }, { status: 400 });
  }

  // Reset all reading progress for this series
  const chapters = await prisma.chapter.findMany({
    where: { seriesId },
    select: { id: true },
  });

  await prisma.readProgress.deleteMany({
    where: {
      userId: session.user.id,
      chapterId: { in: chapters.map((c) => c.id) },
    },
  });

  // Also remove any manual list entry
  await prisma.listEntry.deleteMany({
    where: { userId: session.user.id, seriesId },
  });

  return NextResponse.json({ success: true });
}
