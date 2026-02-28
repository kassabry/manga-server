import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();
  const { chapterId, page, completed } = body;

  if (!chapterId) {
    return NextResponse.json({ error: "Missing chapterId" }, { status: 400 });
  }

  const progress = await prisma.readProgress.upsert({
    where: {
      userId_chapterId: { userId: session.user.id, chapterId },
    },
    update: {
      page: page ?? 0,
      completed: completed ?? false,
      readAt: new Date(),
    },
    create: {
      userId: session.user.id,
      chapterId,
      page: page ?? 0,
      completed: completed ?? false,
    },
  });

  return NextResponse.json(progress);
}
