import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

/**
 * Everything the Continue Reading row needs, in two queries.
 *
 * The component used to fetch the reading list and then loop over it awaiting
 * /api/user/progress/{seriesId} one series at a time — up to 21 serial
 * authenticated round trips before the row could render, each decoding the
 * session and hitting SQLite. That cost grew with every series added to the
 * list, which is a large part of why start-up got slower over time.
 */

/**
 * Cap on incomplete progress rows considered. Only 20 series are ever shown and
 * rows arrive newest-first, so this is far more than enough — it exists to stop
 * a long reading history from loading every partially-read chapter ever.
 */
const PROGRESS_SCAN_LIMIT = 500;
const MAX_ITEMS = 20;

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ items: [] });
  }

  const userId = session.user.id;

  const [progress, manualEntries] = await Promise.all([
    prisma.readProgress.findMany({
      where: { userId, completed: false },
      orderBy: { readAt: "desc" },
      take: PROGRESS_SCAN_LIMIT,
      select: {
        chapterId: true,
        page: true,
        pageOffset: true,
        chapter: {
          select: {
            number: true,
            series: { select: { id: true, title: true, coverPath: true } },
          },
        },
      },
    }),
    prisma.listEntry.findMany({
      where: { userId, status: "reading" },
      orderBy: { updatedAt: "desc" },
      select: { seriesId: true },
    }),
  ]);

  // Newest incomplete chapter per series. Rows are already readAt-desc, so the
  // first one seen for a series is the one to resume.
  const latestBySeries = new Map<
    string,
    {
      chapterId: string;
      chapterNumber: number;
      page: number;
      pageOffset: number;
      seriesId: string;
      seriesTitle: string;
      coverPath: string | null;
    }
  >();

  for (const row of progress) {
    const series = row.chapter.series;
    if (latestBySeries.has(series.id)) continue;
    latestBySeries.set(series.id, {
      chapterId: row.chapterId,
      chapterNumber: row.chapter.number,
      page: row.page,
      pageOffset: row.pageOffset ?? 0,
      seriesId: series.id,
      seriesTitle: series.title,
      coverPath: series.coverPath,
    });
  }

  // Manually-marked "reading" series lead, in the order they were marked; the
  // rest follow by how recently they were read. A series with no unfinished
  // chapter has nothing to continue, so it doesn't appear either way.
  const items: Array<NonNullable<ReturnType<typeof latestBySeries.get>>> = [];
  const seen = new Set<string>();

  for (const { seriesId } of manualEntries) {
    const item = latestBySeries.get(seriesId);
    if (item && !seen.has(seriesId)) {
      seen.add(seriesId);
      items.push(item);
    }
  }
  for (const [seriesId, item] of latestBySeries) {
    if (seen.has(seriesId)) continue;
    seen.add(seriesId);
    items.push(item);
  }

  return NextResponse.json(
    { items: items.slice(0, MAX_ITEMS) },
    { headers: { "Cache-Control": "private, max-age=15" } }
  );
}
