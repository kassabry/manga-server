import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

async function upsertProgress(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();
  const { chapterId, page, completed, pageOffset } = body;

  if (!chapterId) {
    return NextResponse.json({ error: "Missing chapterId" }, { status: 400 });
  }

  // Clamp the within-image offset to 0..1; a completed chapter has no meaningful offset.
  const safeOffset = completed
    ? 0
    : Math.min(1, Math.max(0, typeof pageOffset === "number" ? pageOffset : 0));

  const progress = await prisma.readProgress.upsert({
    where: {
      userId_chapterId: { userId: session.user.id, chapterId },
    },
    update: {
      page: page ?? 0,
      pageOffset: safeOffset,
      completed: completed ?? false,
      readAt: new Date(),
    },
    create: {
      userId: session.user.id,
      chapterId,
      page: page ?? 0,
      pageOffset: safeOffset,
      completed: completed ?? false,
    },
  });

  return NextResponse.json(progress);
}

export const PUT = upsertProgress;
// sendBeacon always sends POST — alias so tab-close saves aren't lost
export const POST = upsertProgress;
