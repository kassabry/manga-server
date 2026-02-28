import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";
import { updateScanInterval } from "@/lib/autoscan";

export async function GET() {
  const session = await auth();
  if (!session?.user || (session.user as { role: string }).role !== "admin") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  const configs = await prisma.siteConfig.findMany();
  const configMap: Record<string, string> = {};
  for (const c of configs) configMap[c.key] = c.value;

  return NextResponse.json(configMap);
}

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user || (session.user as { role: string }).role !== "admin") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 403 });
  }

  const body = await request.json();
  const { key, value } = body;

  if (!key || value === undefined) {
    return NextResponse.json({ error: "Missing key or value" }, { status: 400 });
  }

  // Handle specific config keys
  if (key === "scanIntervalMs") {
    const ms = parseInt(value);
    if (isNaN(ms) || ms < 0) {
      return NextResponse.json({ error: "Invalid interval" }, { status: 400 });
    }
    await updateScanInterval(ms);
  } else {
    await prisma.siteConfig.upsert({
      where: { key },
      update: { value: String(value) },
      create: { key, value: String(value) },
    });
  }

  return NextResponse.json({ success: true });
}
