import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ progress: [] });
  }

  const { seriesId } = await params;

  const progress = await prisma.readProgress.findMany({
    where: {
      userId: session.user.id,
      chapter: { seriesId },
    },
    include: {
      chapter: {
        select: { id: true, number: true },
      },
    },
    orderBy: { chapter: { number: "asc" } },
  });

  return NextResponse.json({ progress });
}
