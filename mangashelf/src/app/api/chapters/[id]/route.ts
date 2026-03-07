import { NextRequest, NextResponse } from "next/server";
import { dirname } from "path";
import { access } from "fs/promises";
import { prisma } from "@/lib/db";
import { getPageList } from "@/lib/cbz";
import { getEpubChapterList } from "@/lib/epub";

function isEpubFile(filePath: string): boolean {
  return filePath.toLowerCase().endsWith(".epub");
}

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

  // Check if the file actually exists on disk
  try {
    await access(chapter.filePath);
  } catch {
    return NextResponse.json(
      { error: "Chapter file missing from disk", filePath: chapter.filePath },
      { status: 410 }
    );
  }

  // Determine this chapter's source directory for same-source navigation
  const chapterDir = dirname(chapter.filePath);
  const epub = isEpubFile(chapter.filePath);

  // Get page/chapter list based on file type
  let pages: string[];
  try {
    pages = epub
      ? await getEpubChapterList(chapter.filePath)
      : await getPageList(chapter.filePath);
  } catch {
    return NextResponse.json(
      { error: "Failed to read chapter file" },
      { status: 500 }
    );
  }

  const allChapters = await prisma.chapter.findMany({
    where: { seriesId: chapter.seriesId },
    orderBy: { number: "asc" },
    select: { id: true, number: true, title: true, source: true, filePath: true },
  });

  // Find prev/next chapters, preferring same source directory
  const prevChapter = findAdjacentChapter(allChapters, chapter.number, chapterDir, "prev");
  const nextChapter = findAdjacentChapter(allChapters, chapter.number, chapterDir, "next");

  return NextResponse.json(
    {
      ...chapter,
      isEpub: epub,
      pages: pages.map((p, i) => ({
        index: i,
        name: p,
        url: `/api/chapters/${id}/pages/${i}`,
      })),
      prevChapter,
      nextChapter,
      allChapters: allChapters.map(({ filePath, ...rest }) => rest),
    },
    {
      headers: { "Cache-Control": "private, max-age=60" },
    }
  );
}

function findAdjacentChapter(
  allChapters: { id: string; number: number; title: string | null; source: string | null; filePath: string }[],
  currentNumber: number,
  currentDir: string,
  direction: "prev" | "next"
): { id: string; number: number } | null {
  // Filter candidates by direction
  const candidates = direction === "prev"
    ? allChapters.filter((c) => c.number < currentNumber)
    : allChapters.filter((c) => c.number > currentNumber);

  if (candidates.length === 0) return null;

  // Sort by proximity to current chapter
  const sorted = direction === "prev"
    ? [...candidates].sort((a, b) => b.number - a.number) // highest first (closest to current)
    : [...candidates].sort((a, b) => a.number - b.number); // lowest first (closest to current)

  // Group by chapter number (there may be duplicates from different sources)
  const targetNumber = sorted[0].number;
  const sameNumberChapters = sorted.filter((c) => c.number === targetNumber);

  // Prefer same source directory
  const sameSource = sameNumberChapters.find((c) => dirname(c.filePath) === currentDir);
  const pick = sameSource || sameNumberChapters[0];

  return { id: pick.id, number: pick.number };
}
