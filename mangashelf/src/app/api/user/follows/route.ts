import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const follows = await prisma.follow.findMany({
    where: { userId: session.user.id },
    include: {
      series: {
        select: {
          id: true,
          title: true,
          slug: true,
          type: true,
          coverPath: true,
          chapterCount: true,
          status: true,
        },
      },
    },
    orderBy: { createdAt: "desc" },
  });

  return NextResponse.json(follows.map((f) => ({
    seriesId: f.seriesId,
    followedAt: f.createdAt,
    series: f.series,
  })));
}
