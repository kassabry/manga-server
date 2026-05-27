import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const follows = await prisma.follow.findMany({
    where: { userId: session.user.id },
    include: {
      series: {
        select: {
          id: true,
          title: true,
          slug: true,
          type: true,
          coverPath: true,
          chapterCount: true,
          status: true,
        },
      },
    },
    orderBy: { createdAt: "desc" },
  });

  const seriesIds = follows.map((f) => f.seriesId);
  let displayCountMap = new Map<string, number>();
  if (seriesIds.length > 0) {
    const rows = await prisma.$queryRaw<{ seriesId: string; cnt: bigint }[]>(
      Prisma.sql`SELECT seriesId, COUNT(DISTINCT number) AS cnt FROM "Chapter" WHERE seriesId IN (${Prisma.join(seriesIds)}) GROUP BY seriesId`
    );
    displayCountMap = new Map(rows.map((r) => [r.seriesId, Number(r.cnt)]));
  }

  return NextResponse.json(follows.map((f) => ({
    seriesId: f.seriesId,
    followedAt: f.createdAt,
    series: {
      ...f.series,
      displayChapterCount: displayCountMap.get(f.seriesId) ?? f.series.chapterCount,
    },
  })));
}
