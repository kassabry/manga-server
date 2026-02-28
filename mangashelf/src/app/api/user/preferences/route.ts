import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let prefs = await prisma.userPreferences.findUnique({
    where: { userId: session.user.id },
  });

  if (!prefs) {
    // Create default preferences
    prefs = await prisma.userPreferences.create({
      data: { userId: session.user.id },
    });
  }

  return NextResponse.json(prefs);
}

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();

  // Only allow updating specific fields
  const allowedFields = [
    "theme", "customColors", "readerLayout", "readerFit",
    "readerDirection", "readerBgColor", "readerBrightness",
    "autoHideToolbar", "swipeEnabled", "carouselColumns",
  ];

  const data: Record<string, unknown> = {};
  for (const field of allowedFields) {
    if (body[field] !== undefined) {
      data[field] = body[field];
    }
  }

  const prefs = await prisma.userPreferences.upsert({
    where: { userId: session.user.id },
    update: data,
    create: { userId: session.user.id, ...data },
  });

  return NextResponse.json(prefs);
}
