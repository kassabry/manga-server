import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { auth } from "@/lib/auth";
import { access } from "fs/promises";
import { join } from "path";
import { getCoversDir, normalizeSourceForFilename } from "@/lib/covers";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const series = await prisma.series.findUnique({
    where: { id },
    include: {
      chapters: {
        orderBy: { number: "asc" },
        select: {
          id: true,
          number: true,
          title: true,
          pageCount: true,
          createdAt: true,
          source: true,
          sourceUrl: true,
        },
      },
      libraryPaths: {
        select: {
          source: true,
        },
      },
    },
  });

  if (!series) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  // Build list of available source-specific covers that exist on disk
  const coversDir = getCoversDir();
  const safeSlug = series.slug.replace(/[^a-z0-9-]/gi, "");
  const availableCovers: { source: string; url: string }[] = [];

  const seenSources = new Set<string>();
  for (const lp of series.libraryPaths) {
    if (!lp.source || seenSources.has(lp.source)) continue;
    seenSources.add(lp.source);
    const safeSource = normalizeSourceForFilename(lp.source);
    if (!safeSource) continue;
    const sourcePath = join(coversDir, `${safeSlug}-${safeSource}.dat`);
    try {
      await access(sourcePath);
      availableCovers.push({
        source: lp.source,
        url: `/api/covers/${safeSlug}?source=${encodeURIComponent(safeSource)}`,
      });
    } catch {
      // File doesn't exist yet — skip
    }
  }

  return NextResponse.json({ ...series, availableCovers });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const body = await request.json();

  // Only allow updating preferredCoverSource via this route
  const { preferredCoverSource } = body as { preferredCoverSource: string | null };

  await prisma.series.update({
    where: { id },
    data: { preferredCoverSource: preferredCoverSource ?? null },
  });

  return NextResponse.json({ ok: true });
}
