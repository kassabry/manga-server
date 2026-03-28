import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

// POST /api/series/[id]/dedup
// Finds duplicate chapters (same seriesId + number + source) and removes all but
// the best copy (highest page count). Returns { removed: N }.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // Fetch all chapters for this series, best copies first (most pages)
  const chapters = await prisma.chapter.findMany({
    where: { seriesId: id },
    orderBy: [{ number: "asc" }, { pageCount: "desc" }],
    select: { id: true, number: true, source: true, pageCount: true },
  });

  // Walk through in order — first occurrence of (number, source) is the keeper
  const kept = new Set<string>();
  const toDelete: string[] = [];

  for (const ch of chapters) {
    const key = `${ch.number}:${ch.source ?? ""}`;
    if (kept.has(key)) {
      toDelete.push(ch.id);
    } else {
      kept.add(key);
    }
  }

  if (toDelete.length > 0) {
    await prisma.chapter.deleteMany({ where: { id: { in: toDelete } } });

    // Recalculate and update the series chapterCount
    const remaining = await prisma.chapter.count({ where: { seriesId: id } });
    await prisma.series.update({
      where: { id },
      data: { chapterCount: remaining },
    });
  }

  return NextResponse.json({ removed: toDelete.length });
}
