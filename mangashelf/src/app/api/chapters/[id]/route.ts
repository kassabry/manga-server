import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getPageList } from "@/lib/cbz";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const chapter = await prisma.chapter.findUnique({
    where: { id },
    include: {
      series: {
        select: { id: true, title: true, slug: true },
      },
    },
  });

  if (!chapter) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const pages = await getPageList(chapter.filePath);

  // Get adjacent chapters for navigation
  const [prevChapter, nextChapter] = await Promise.all([
    prisma.chapter.findFirst({
      where: { seriesId: chapter.seriesId, number: { lt: chapter.number } },
      orderBy: { number: "desc" },
      select: { id: true, number: true },
    }),
    prisma.chapter.findFirst({
      where: { seriesId: chapter.seriesId, number: { gt: chapter.number } },
      orderBy: { number: "asc" },
      select: { id: true, number: true },
    }),
  ]);

  const allChapters = await prisma.chapter.findMany({
    where: { seriesId: chapter.seriesId },
    orderBy: { number: "asc" },
    select: { id: true, number: true, title: true },
  });

  return NextResponse.json({
    ...chapter,
    pages: pages.map((p, i) => ({
      index: i,
      name: p,
      url: `/api/chapters/${id}/pages/${i}`,
    })),
    prevChapter,
    nextChapter,
    allChapters,
  });
}
