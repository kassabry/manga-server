import { NextRequest, NextResponse } from "next/server";
import { access } from "fs/promises";
import { prisma } from "@/lib/db";
import { getPageList, extractPage } from "@/lib/cbz";
import { getEpubChapterList, extractEpubChapter } from "@/lib/epub";

function isEpubFile(filePath: string): boolean {
  return filePath.toLowerCase().endsWith(".epub");
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; page: string }> }
) {
  const { id, page: pageStr } = await params;
  const pageIndex = parseInt(pageStr);

  const chapter = await prisma.chapter.findUnique({ where: { id } });
  if (!chapter) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  // Check if the file exists on disk
  try {
    await access(chapter.filePath);
  } catch {
    return NextResponse.json(
      { error: "Chapter file missing from disk" },
      { status: 410 }
    );
  }

  if (isEpubFile(chapter.filePath)) {
    // EPUB: serve HTML chapter content
    const chapterList = await getEpubChapterList(chapter.filePath);
    if (pageIndex < 0 || pageIndex >= chapterList.length) {
      return NextResponse.json({ error: "Page not found" }, { status: 404 });
    }

    const result = await extractEpubChapter(chapter.filePath, chapterList[pageIndex]);
    if (!result) {
      return NextResponse.json({ error: "Failed to extract chapter" }, { status: 500 });
    }

    return new NextResponse(result.html, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=86400, immutable",
      },
    });
  }

  // CBZ: serve image page
  const pages = await getPageList(chapter.filePath);
  if (pageIndex < 0 || pageIndex >= pages.length) {
    return NextResponse.json({ error: "Page not found" }, { status: 404 });
  }

  const result = await extractPage(chapter.filePath, pages[pageIndex]);
  if (!result) {
    return NextResponse.json({ error: "Failed to extract page" }, { status: 500 });
  }

  return new NextResponse(new Uint8Array(result.data), {
    headers: {
      "Content-Type": result.mimeType,
      "Cache-Control": "public, max-age=86400, immutable",
    },
  });
}
