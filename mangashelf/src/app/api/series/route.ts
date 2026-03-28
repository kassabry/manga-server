import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const page = parseInt(searchParams.get("page") || "1");
  const limit = parseInt(searchParams.get("limit") || "24");
  const search = searchParams.get("search") || "";
  const type = searchParams.get("type") || "";
  const genre = searchParams.get("genre") || "";
  const status = searchParams.get("status") || "";
  const publisher = searchParams.get("publisher") || "";
  const sort = searchParams.get("sort") || "title";
  const excludeType = searchParams.get("excludeType") || "";

  // Build AND conditions array for more complex filtering
  const andConditions: Record<string, unknown>[] = [];

  if (search) {
    // Split into tokens so "solo leveling" matches in any word order
    const tokens = search.trim().split(/\s+/).filter(Boolean);
    for (const token of tokens) {
      andConditions.push({
        OR: [
          { title: { contains: token } },
          { author: { contains: token } },
          { artist: { contains: token } },
        ],
      });
    }
  }
  if (type) {
    andConditions.push({ type });
  }
  if (genre) {
    // Support multiple genres separated by comma
    const genres = genre.split(",").map((g) => g.trim()).filter(Boolean);
    for (const g of genres) {
      andConditions.push({ genres: { contains: g } });
    }
  }
  if (status) {
    andConditions.push({ status });
  }
  if (publisher) {
    andConditions.push({ publisher });
  }
  if (excludeType) {
    andConditions.push({ type: { not: excludeType } });
  }

  const where = andConditions.length > 0 ? { AND: andConditions } : {};

  const orderBy: Record<string, string> = {};
  switch (sort) {
    case "recent":
      orderBy.lastChapterAt = "desc";
      break;
    case "recent_asc":
      orderBy.lastChapterAt = "asc";
      break;
    case "created":
      orderBy.createdAt = "desc";
      break;
    case "created_asc":
      orderBy.createdAt = "asc";
      break;
    case "title":
      orderBy.title = "asc";
      break;
    case "title_desc":
      orderBy.title = "desc";
      break;
    case "rating":
      orderBy.rating = "desc";
      break;
    case "rating_asc":
      orderBy.rating = "asc";
      break;
    case "chapters":
      orderBy.chapterCount = "desc";
      break;
    case "chapters_asc":
      orderBy.chapterCount = "asc";
      break;
    default:
      orderBy.title = "asc";
  }

  const [series, total] = await Promise.all([
    prisma.series.findMany({
      where,
      orderBy,
      skip: (page - 1) * limit,
      take: limit,
      select: {
        id: true,
        title: true,
        slug: true,
        type: true,
        status: true,
        genres: true,
        rating: true,
        coverPath: true,
        chapterCount: true,
        publisher: true,
        updatedAt: true,
        lastChapterAt: true,
        chapters: {
          orderBy: { number: "desc" },
          take: 1,
          select: { number: true },
        },
      },
    }),
    prisma.series.count({ where }),
  ]);

  // Flatten latest chapter number into each series object
  const seriesWithLatest = series.map((s) => {
    const { chapters, ...rest } = s;
    return {
      ...rest,
      latestChapterNumber: chapters[0]?.number ?? null,
    };
  });

  return NextResponse.json(
    {
      series: seriesWithLatest,
      total,
      page,
      totalPages: Math.ceil(total / limit),
    },
    {
      headers: { "Cache-Control": "private, max-age=30" },
    }
  );
}
