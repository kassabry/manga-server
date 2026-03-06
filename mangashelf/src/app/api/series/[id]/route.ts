import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

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

  return NextResponse.json(series);
}
