import { NextRequest, NextResponse } from "next/server";
import { readFile, stat } from "fs/promises";
import { join } from "path";
import {
  getCoversDir,
  getPreferredCoverSource,
  normalizeSourceForFilename,
} from "@/lib/covers";

// Covers are the bulk of every page's requests — 30+ per screen of the grid.
// Each one is an authenticated round trip that runs the auth middleware, a DB
// lookup and a file read, so the only way to make the grid cheap is for the
// browser to stop asking.
//
// `stale-while-revalidate` is the part that matters for a cold start: the grid
// paints from cache immediately for up to a week and the revalidation happens
// off the critical path, instead of 30 blocking conditional requests before
// anything appears. `max-age` stays short so switching a series' cover in the
// UI shows up on the next load rather than an hour later.
const CACHE_CONTROL = "private, max-age=300, stale-while-revalidate=604800";

async function serveCoverFile(
  filePath: string,
  request: NextRequest
): Promise<NextResponse | null> {
  try {
    const fileStat = await stat(filePath);
    const etag = `"${fileStat.mtimeMs.toString(16)}"`;

    if (request.headers.get("if-none-match") === etag) {
      // The 304 has to repeat the caching headers, or the browser revalidates
      // again on the very next load.
      return new NextResponse(null, {
        status: 304,
        headers: { "Cache-Control": CACHE_CONTROL, ETag: etag },
      });
    }

    const data = await readFile(filePath);

    // Detect actual image format from magic bytes
    let contentType = "image/jpeg";
    if (data[0] === 0x89 && data[1] === 0x50) {
      contentType = "image/png";
    } else if (
      data[0] === 0x52 &&
      data[1] === 0x49 &&
      data[8] === 0x57 &&
      data[9] === 0x45
    ) {
      contentType = "image/webp";
    }

    return new NextResponse(new Uint8Array(data), {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": CACHE_CONTROL,
        "ETag": etag,
      },
    });
  } catch {
    return null;
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;

  // Sanitize slug to prevent path traversal
  const safeSlug = slug.replace(/[^a-z0-9-]/gi, "");
  if (!safeSlug) {
    return new NextResponse(null, { status: 400 });
  }

  const coversDir = getCoversDir();

  // If ?source= is specified, serve that source's cover directly
  const sourceParam = request.nextUrl.searchParams.get("source");
  if (sourceParam) {
    const safeSource = normalizeSourceForFilename(sourceParam);
    if (safeSource) {
      const sourcePath = join(coversDir, `${safeSlug}-${safeSource}.dat`);
      const res = await serveCoverFile(sourcePath, request);
      if (res) return res;
    }
    // Source cover not found — fall through to default
  }

  // Check DB for preferred cover source (only when no explicit source param)
  if (!sourceParam) {
    try {
      const preferred = await getPreferredCoverSource(safeSlug);
      if (preferred) {
        const safeSource = normalizeSourceForFilename(preferred);
        const sourcePath = join(coversDir, `${safeSlug}-${safeSource}.dat`);
        const res = await serveCoverFile(sourcePath, request);
        if (res) return res;
        // Preferred source file missing — fall through to default
      }
    } catch {
      // DB error — fall through to default
    }
  }

  // Serve the main (default) cover
  const coverPath = join(coversDir, `${safeSlug}.dat`);
  const res = await serveCoverFile(coverPath, request);
  if (res) return res;

  return new NextResponse(null, { status: 404 });
}
