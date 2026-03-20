import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const limit = parseInt(request.nextUrl.searchParams.get("limit") || "50");
  const grouped = request.nextUrl.searchParams.get("grouped") === "true";

  // Get chapters from followed series, ordered by most recent.
  // Only chapters added AFTER the user followed the series are "new" —
  // this prevents flooding the feed when following a series with many existing chapters.
  const follows = await prisma.follow.findMany({
    where: { userId: session.user.id },
    select: { seriesId: true, createdAt: true },
  });

  if (follows.length === 0) {
    return NextResponse.json({ updates: [], seriesGroups: [] });
  }

  // Map seriesId -> the datetime the user followed it
  const followedAtMap = new Map(follows.map((f) => [f.seriesId, f.createdAt]));
  const seriesIds = follows.map((f) => f.seriesId);

  // Use the earliest follow date as a lower-bound so we can issue a single
  // DB query, then filter per-series in memory.
  const earliestFollow = follows.reduce(
    (min, f) => (f.createdAt < min ? f.createdAt : min),
    follows[0].createdAt
  );

  const chapters = await prisma.chapter.findMany({
    where: {
      seriesId: { in: seriesIds },
      createdAt: { gte: earliestFollow },
    },
    orderBy: { createdAt: "desc" },
    take: limit * 5,
    include: {
      series: {
        select: {
          id: true,
          title: true,
          slug: true,
          coverPath: true,
          type: true,
        },
      },
    },
  });

  // Filter per-series: only keep chapters added after the user followed that series.
  // A chapter is "new" if it was added to the library after the follow timestamp,
  // so following an old series won't flood the feed with its entire back-catalogue.
  const newChapters = chapters.filter((ch) => {
    const followedAt = followedAtMap.get(ch.seriesId);
    return followedAt ? ch.createdAt > followedAt : true;
  });

  // Also get read progress for these chapters
  const chapterIds = newChapters.map((c) => c.id);
  const progress = await prisma.readProgress.findMany({
    where: {
      userId: session.user.id,
      chapterId: { in: chapterIds },
    },
  });
  const progressMap = new Map(progress.map((p) => [p.chapterId, p]));

  if (grouped) {
    // Group by series — return both a flat "max chapter per series" list
    // AND full seriesGroups with all chapters per series for the Updates page
    const seriesMap = new Map<
      string,
      {
        series: (typeof newChapters)[0]["series"];
        chapters: typeof newChapters;
        maxChapter: (typeof newChapters)[0];
        minChapter: number;
        maxChapterNum: number;
        latestDate: Date;
      }
    >();

    for (const chapter of newChapters) {
      const existing = seriesMap.get(chapter.seriesId);
      if (!existing) {
        seriesMap.set(chapter.seriesId, {
          series: chapter.series,
          chapters: [chapter],
          maxChapter: chapter,
          minChapter: chapter.number,
          maxChapterNum: chapter.number,
          latestDate: new Date(chapter.createdAt),
        });
      } else {
        existing.chapters.push(chapter);
        if (chapter.number > existing.maxChapterNum) {
          existing.maxChapter = chapter;
          existing.maxChapterNum = chapter.number;
        }
        if (chapter.number < existing.minChapter) {
          existing.minChapter = chapter.number;
        }
        const chDate = new Date(chapter.createdAt);
        if (chDate > existing.latestDate) {
          existing.latestDate = chDate;
        }
      }
    }

    // Build flat updates (one per series, max chapter) for carousel
    const updates = Array.from(seriesMap.values())
      .map(({ maxChapter, chapters: chs, minChapter }) => ({
        ...maxChapter,
        readProgress: progressMap.get(maxChapter.id) || null,
        totalNewChapters: chs.length,
        minNewChapter: minChapter,
      }))
      .sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      )
      .slice(0, limit);

    // Build series groups with all chapters (for full Updates page)
    const seriesGroups = Array.from(seriesMap.values())
      .map(({ series, chapters: chs, latestDate }) => ({
        series,
        latestDate: latestDate.toISOString(),
        chapterCount: chs.length,
        chapters: chs
          .sort((a, b) => b.number - a.number)
          .map((ch) => ({
            id: ch.id,
            number: ch.number,
            title: ch.title,
            createdAt: ch.createdAt,
            readProgress: progressMap.get(ch.id)
              ? {
                  completed: progressMap.get(ch.id)!.completed,
                  page: progressMap.get(ch.id)!.page,
                }
              : null,
          })),
      }))
      .sort(
        (a, b) =>
          new Date(b.latestDate).getTime() - new Date(a.latestDate).getTime()
      )
      .slice(0, limit);

    return NextResponse.json({ updates, seriesGroups });
  }

  const updates = newChapters.slice(0, limit).map((chapter) => ({
    ...chapter,
    readProgress: progressMap.get(chapter.id) || null,
    totalNewChapters: 1,
    minNewChapter: chapter.number,
  }));

  return NextResponse.json({ updates, seriesGroups: [] });
}
