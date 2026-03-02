import { NextRequest, NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";
import { getCoversDir } from "@/lib/covers";

export async function GET(
  _request: NextRequest,
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
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
      },
    });
  } catch {
    return new NextResponse(null, { status: 404 });
  }
}
