import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET() {
  // Get all unique genres from all series
  const series = await prisma.series.findMany({
    where: { genres: { not: null } },
    select: { genres: true },
  });

  const genreCount = new Map<string, number>();
  for (const s of series) {
    if (!s.genres) continue;
    const genres = s.genres.split(",").map((g) => g.trim()).filter(Boolean);
    for (const g of genres) {
      genreCount.set(g, (genreCount.get(g) || 0) + 1);
    }
  }

  // Also get all unique publishers, statuses, types
  const [publishers, statuses, types] = await Promise.all([
    prisma.series.findMany({
      where: { publisher: { not: null } },
      select: { publisher: true },
      distinct: ["publisher"],
    }),
    prisma.series.findMany({
      where: { status: { not: null } },
      select: { status: true },
      distinct: ["status"],
    }),
    prisma.series.findMany({
      select: { type: true },
      distinct: ["type"],
    }),
  ]);

  const genreList = Array.from(genreCount.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);

  return NextResponse.json({
    genres: genreList,
    publishers: publishers.map((p) => p.publisher).filter(Boolean),
    statuses: statuses.map((s) => s.status).filter(Boolean),
    types: types.map((t) => t.type).filter(Boolean),
  });
}
