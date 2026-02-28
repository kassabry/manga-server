import { readdir, stat } from "fs/promises";
import { join, resolve } from "path";
import { prisma } from "./db";
import { extractComicInfo, getPageCount } from "./cbz";
import { extractCover } from "./covers";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function parseChapterNumber(filename: string): number {
  const match = filename.match(/Chapter\s+(\d+(?:\.\d+)?)/i);
  if (match) return parseFloat(match[1]);

  // Fallback: look for any number pattern before .cbz
  const numMatch = filename.match(/(\d+(?:\.\d+)?)\s*\.cbz$/i);
  if (numMatch) return parseFloat(numMatch[1]);

  return 0;
}

const TYPE_DIRS: Record<string, string> = {
  Manga: "Manga",
  Manhwa: "Manhwa",
  Manhua: "Manhua",
  LightNovels: "LightNovels",
};

export interface ScanResult {
  seriesAdded: number;
  seriesUpdated: number;
  chaptersAdded: number;
  errors: string[];
}

export async function scanLibrary(
  libraryPath: string
): Promise<ScanResult> {
  const result: ScanResult = {
    seriesAdded: 0,
    seriesUpdated: 0,
    chaptersAdded: 0,
    errors: [],
  };

  const resolvedPath = resolve(libraryPath);

  for (const [type, dirName] of Object.entries(TYPE_DIRS)) {
    const typePath = join(resolvedPath, dirName);

    let entries;
    try {
      entries = await readdir(typePath, { withFileTypes: true });
    } catch {
      // Directory doesn't exist, skip
      continue;
    }

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const seriesDirPath = join(typePath, entry.name);
      const seriesTitle = entry.name;
      const seriesSlug = slugify(seriesTitle);

      try {
        await scanSeries(seriesDirPath, seriesTitle, seriesSlug, type, result);
      } catch (err) {
        result.errors.push(
          `Error scanning ${seriesTitle}: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }
  }

  return result;
}

async function scanSeries(
  seriesDirPath: string,
  seriesTitle: string,
  seriesSlug: string,
  type: string,
  result: ScanResult
) {
  // Find all CBZ files
  const files = await readdir(seriesDirPath);
  const cbzFiles = files
    .filter((f) => f.toLowerCase().endsWith(".cbz"))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  if (cbzFiles.length === 0) return;

  // Check if series exists
  let series = await prisma.series.findUnique({
    where: { libraryPath: seriesDirPath },
    include: { chapters: true },
  });

  // Extract metadata from first CBZ if new series
  const firstCbzPath = join(seriesDirPath, cbzFiles[0]);
  const comicInfo = await extractComicInfo(firstCbzPath);

  // Extract/cache cover image
  const coverPath = await extractCover(seriesSlug, seriesDirPath, firstCbzPath);

  if (!series) {
    // Create new series
    series = await prisma.series.create({
      data: {
        title: comicInfo?.Series || seriesTitle,
        slug: seriesSlug,
        description: comicInfo?.Summary || null,
        author: comicInfo?.Writer || null,
        artist: comicInfo?.Penciller || null,
        status: parseStatus(comicInfo?.Notes),
        type,
        genres: comicInfo?.Genre || null,
        rating: comicInfo?.CommunityRating
          ? parseFloat(comicInfo.CommunityRating)
          : null,
        coverPath,
        libraryPath: seriesDirPath,
        publisher: comicInfo?.Publisher || null,
        ageRating: comicInfo?.AgeRating || null,
        chapterCount: cbzFiles.length,
        lastChapterAt: new Date(),
      },
      include: { chapters: true },
    });
    result.seriesAdded++;
  } else {
    // Backfill lastChapterAt for series that existed before this field was added
    let backfillLastChapter = undefined;
    if (!series.lastChapterAt) {
      try {
        const lastCbz = join(seriesDirPath, cbzFiles[cbzFiles.length - 1]);
        const lastStat = await stat(lastCbz);
        backfillLastChapter = lastStat.mtime;
      } catch {}
    }

    // Update series metadata
    await prisma.series.update({
      where: { id: series.id },
      data: {
        chapterCount: cbzFiles.length,
        coverPath: coverPath || series.coverPath,
        description: comicInfo?.Summary || series.description,
        author: comicInfo?.Writer || series.author,
        artist: comicInfo?.Penciller || series.artist,
        genres: comicInfo?.Genre || series.genres,
        ...(backfillLastChapter ? { lastChapterAt: backfillLastChapter } : {}),
      },
    });
    result.seriesUpdated++;
  }

  // Scan chapters
  const existingPaths = new Set(series.chapters.map((c) => c.filePath));
  let seriesChaptersAdded = 0;

  for (const cbzFile of cbzFiles) {
    const cbzPath = join(seriesDirPath, cbzFile);

    if (existingPaths.has(cbzPath)) continue;

    const chapterNumber = parseChapterNumber(cbzFile);
    const chapterComicInfo = await extractComicInfo(cbzPath);
    const pageCount = await getPageCount(cbzPath);
    const fileStat = await stat(cbzPath);

    let source: string | null = null;
    let sourceUrl: string | null = null;
    if (chapterComicInfo?.Web) {
      sourceUrl = chapterComicInfo.Web;
      try {
        const url = new URL(chapterComicInfo.Web);
        // Derive source name from domain
        const domain = url.hostname.replace(/^www\./, "");
        const domainMap: Record<string, string> = {
          "manhuato.com": "ManhuaTo",
          "asuracomic.net": "AsuraScans",
          "asurascans.com": "AsuraScans",
          "flamecomics.xyz": "FlameComics",
          "drakecomic.org": "DrakeComic",
          "mangadex.org": "MangaDex",
        };
        source = domainMap[domain] || domain;
      } catch {
        source = null;
      }
    }

    await prisma.chapter.create({
      data: {
        seriesId: series.id,
        number: chapterNumber,
        title: chapterComicInfo?.Title || null,
        pageCount,
        filePath: cbzPath,
        fileSize: fileStat.size,
        source,
        sourceUrl,
      },
    });
    result.chaptersAdded++;
    seriesChaptersAdded++;
  }

  // Update lastChapterAt if new chapters were added
  if (seriesChaptersAdded > 0) {
    await prisma.series.update({
      where: { id: series.id },
      data: { lastChapterAt: new Date() },
    });
  }
}

function parseStatus(notes?: string): string | null {
  if (!notes) return null;
  const statusMatch = notes.match(/Status:\s*(\w+)/i);
  if (statusMatch) {
    const s = statusMatch[1].toLowerCase();
    if (s === "ongoing") return "Ongoing";
    if (s === "completed" || s === "complete") return "Completed";
    if (s === "hiatus") return "Hiatus";
  }
  return null;
}
