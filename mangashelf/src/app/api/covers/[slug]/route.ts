import { NextRequest, NextResponse } from "next/server";
import { readFile, stat } from "fs/promises";
import { join } from "path";
import { getCoversDir } from "@/lib/covers";

export const dynamic = "force-dynamic";

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

  const coverPath = join(getCoversDir(), `${safeSlug}.dat`);

  try {
    const fileStat = await stat(coverPath);
    // ETag based on mtime — changes whenever the .dat file is updated by the scanner
    const etag = `"${fileStat.mtimeMs.toString(16)}"`;

    if (request.headers.get("if-none-match") === etag) {
      return new NextResponse(null, { status: 304 });
    }

    const data = await readFile(coverPath);

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
        // no-cache: browser must revalidate on every request (sends If-None-Match).
        // ETag lets the server return 304 Not Modified when unchanged — no bandwidth
        // wasted, but covers always reflect the latest scan without a 24h delay.
        "Cache-Control": "no-cache",
        "ETag": etag,
      },
    });
  } catch {
    return new NextResponse(null, { status: 404 });
  }
}
