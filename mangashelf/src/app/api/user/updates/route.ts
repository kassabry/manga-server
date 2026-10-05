import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

function toUTCDateStr(d: Date): string {
  return d.toISOString().slice(0, 10); // "YYYY-MM-DD"
}

const key = (seriesId: string, number: number) => `${seriesId}:${number}`;

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const limit = parseInt(request.nextUrl.searchParams.get("limit") || "50");
  const grouped = request.nextUrl.searchParams.get("grouped") === "true";

  const follows = await prisma.follow.findMany({
    where: { userId: session.user.id },
    select: { seriesId: true, createdAt: true },
  });

  if (follows.length === 0) {
    return NextResponse.json({ updates: [], seriesGroups: [] });
  }

  const followedAtMap = new Map(follows.map((f) => [f.seriesId, f.createdAt]));
  const seriesIds = follows.map((f) => f.seriesId);

  // One row per (series, chapter number) with the FIRST upload time of that number
  // across every source. This replaces loading every post-follow chapter row: that
  // query was ordered oldest-first under a 20000-row cap, so once followed series had
  // accumulated enough chapters the cap cut off exactly the newest ones and the feed
  // stopped showing new releases. Grouping keeps the result proportional to distinct
  // chapter numbers and needs no cap.
  //
  // A number counts as "new" only if its first upload came after the user followed the
  // series. That also covers the old pre-follow check: if ANY source had the number at
  // or before follow time, the minimum is at or before follow time too, so a newly
  // added source can't surface backlog chapters as new.
  const firstUploads = await prisma.chapter.groupBy({
    by: ["seriesId", "number"],
    where: { seriesId: { in: seriesIds } },
    _min: { createdAt: true },
  });

  type NewNumber = { number: number; firstAt: Date };
  const newBySeries = new Map<string, NewNumber[]>();
  for (const row of firstUploads) {
    const firstAt = row._min.createdAt;
    const followedAt = followedAtMap.get(row.seriesId);
    if (!firstAt || !followedAt || firstAt <= followedAt) continue;
    const list = newBySeries.get(row.seriesId) ?? [];
    list.push({ number: row.number, firstAt });
    newBySeries.set(row.seriesId, list);
  }

  // When a series is re-imported (e.g. directory renamed, scanner wipes and recreates
  // chapters), every chapter gets a fresh createdAt on the same day and lands in the
  // anchor-day batch, flooding the feed. Cap each series' visible batch to the
  // MAX_BATCH_PER_SERIES highest-numbered chapters so a flood shows at most a handful
  // of entries rather than the entire back-catalogue. Genuine same-day releases (a
  // handful of chapters) are unaffected.
  const MAX_BATCH_PER_SERIES = 5;

  // For each series: anchor the batch on the HIGHEST-NUMBERED new chapter, then keep
  // only chapters first released on that same calendar day. Anchoring on the highest
  // number (rather than the latest createdAt across all sources) is critical for
  // multi-source series: a slow mirror re-uploading an OLD chapter (e.g. Ch.135) days
  // after the newest one (Ch.137) must NOT make Ch.135's day the "latest", which would
  // hide the genuinely-new Ch.137 from the feed.
  type Batch = { seriesId: string; numbers: NewNumber[]; latestDate: Date };
  const batches: Batch[] = [];
  for (const [seriesId, nums] of newBySeries) {
    const anchor = nums.reduce((hi, n) => (n.number > hi.number ? n : hi));
    const anchorDay = toUTCDateStr(anchor.firstAt);
    const numbers = nums
      .filter((n) => toUTCDateStr(n.firstAt) === anchorDay)
      .sort((a, b) => b.number - a.number)
      .slice(0, MAX_BATCH_PER_SERIES);
    batches.push({ seriesId, numbers, latestDate: anchor.firstAt });
  }

  if (batches.length === 0) {
    return NextResponse.json({ updates: [], seriesGroups: [] });
  }

  const batchSeriesIds = batches.map((b) => b.seriesId);
  const batchNumbers = [...new Set(batches.flatMap((b) => b.numbers.map((n) => n.number)))];
  const wanted = new Set(batches.flatMap((b) => b.numbers.map((n) => key(b.seriesId, n.number))));

  // Resolve each batch number to its first-uploaded chapter row (the one the feed links
  // to). Ascending order means the first row seen per key is the first upload.
  const candidateRows = await prisma.chapter.findMany({
    where: { seriesId: { in: batchSeriesIds }, number: { in: batchNumbers } },
    orderBy: { createdAt: "asc" },
    include: {
      series: {
        select: { id: true, title: true, slug: true, coverPath: true, type: true },
      },
    },
  });
  const chapterByKey = new Map<string, (typeof candidateRows)[0]>();
  for (const ch of candidateRows) {
    const k = key(ch.seriesId, ch.number);
    if (wanted.has(k) && !chapterByKey.has(k)) chapterByKey.set(k, ch);
  }

  // Read state is matched by chapter NUMBER, not by chapter id. The feed links to the
  // first-uploaded copy, but the user may well have read the same chapter from another
  // source; checking only the linked copy's id kept already-read chapters in the feed.
  const progressRecords = await prisma.readProgress.findMany({
    where: {
      userId: session.user.id,
      chapter: { seriesId: { in: batchSeriesIds }, number: { in: batchNumbers } },
    },
    select: {
      chapterId: true,
      page: true,
      completed: true,
      chapter: { select: { seriesId: true, number: true } },
    },
  });
  const completedKeys = new Set(
    progressRecords
      .filter((p) => p.completed)
      .map((p) => key(p.chapter.seriesId, p.chapter.number))
  );
  const progressById = new Map(progressRecords.map((p) => [p.chapterId, p]));

  // Build series groups; exclude any series where every batch chapter is completed
  const seriesGroups = batches
    .map(({ seriesId, numbers, latestDate }) => {
      // numbers is already sorted desc (newest first in list)
      const withProgress = numbers
        .map((n) => chapterByKey.get(key(seriesId, n.number)))
        .filter((ch): ch is NonNullable<typeof ch> => ch !== undefined)
        .map((ch) => {
          const completed = completedKeys.has(key(seriesId, ch.number));
          const prog = progressById.get(ch.id);
          return {
            id: ch.id,
            number: ch.number,
            title: ch.title,
            createdAt: ch.createdAt.toISOString(),
            readProgress: completed || prog ? { completed, page: prog?.page ?? 0 } : null,
          };
        });
      if (withProgress.length === 0) return null;

      // Drop series where every batch chapter has been completed
      if (withProgress.every((ch) => ch.readProgress?.completed)) return null;

      const series = chapterByKey.get(key(seriesId, numbers[0].number))?.series
        ?? candidateRows.find((c) => c.seriesId === seriesId)!.series;

      // Navigate to the oldest (lowest number) chapter in the batch
      const firstChapterId = withProgress[withProgress.length - 1].id;

      return {
        series,
        latestDate: latestDate.toISOString(),
        chapterCount: withProgress.length,
        chapters: withProgress,
        firstChapterId,
      };
    })
    .filter((g): g is NonNullable<typeof g> => g !== null)
    .sort((a, b) => new Date(b.latestDate).getTime() - new Date(a.latestDate).getTime())
    .slice(0, limit);

  if (grouped) {
    // Flat updates list for the home page carousel:
    // one entry per series — the newest chapter is the "headline", but the link
    // goes to the oldest chapter in the batch (so user starts reading in order).
    const updates = seriesGroups.map((g) => {
      const newestChapter = g.chapters[0]; // highest number (sorted desc)
      const oldestChapter = g.chapters[g.chapters.length - 1];
      return {
        id: newestChapter.id,
        number: newestChapter.number,
        title: newestChapter.title,
        createdAt: newestChapter.createdAt,
        series: g.series,
        readProgress: newestChapter.readProgress,
        totalNewChapters: g.chapterCount,
        minNewChapter: oldestChapter.number,
        firstChapterId: g.firstChapterId,
      };
    });

    return NextResponse.json({ updates, seriesGroups });
  }

  const updates = seriesGroups
    .flatMap((g) =>
      g.chapters.map((ch) => ({
        ...ch,
        series: g.series,
        totalNewChapters: g.chapterCount,
        minNewChapter: g.chapters[g.chapters.length - 1].number,
        firstChapterId: g.firstChapterId,
      }))
    )
    .slice(0, limit);

  return NextResponse.json({ updates, seriesGroups: [] });
}
