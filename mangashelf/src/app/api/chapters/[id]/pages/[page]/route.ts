import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { getPageList, extractPage } from "@/lib/cbz";

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
