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

export interface ScanCleanup {
  seriesRemoved: number;
  chaptersRemoved: number;
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

  // Track all valid library paths found on disk
  const validLibraryPaths = new Set<string>();

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
      validLibraryPaths.add(seriesDirPath);
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

  // Remove series from DB that no longer exist on disk
  const cleanup = await cleanupDeletedSeries(validLibraryPaths);
  if (cleanup.seriesRemoved > 0) {
    console.log(
      `Cleanup: removed ${cleanup.seriesRemoved} series (${cleanup.chaptersRemoved} chapters) no longer on disk`
    );
  }

  return result;
}

async function cleanupDeletedSeries(
  validPaths: Set<string>
): Promise<ScanCleanup> {
  const allSeries = await prisma.series.findMany({
    select: { id: true, title: true, libraryPath: true, _count: { select: { chapters: true } } },
  });

  let seriesRemoved = 0;
  let chaptersRemoved = 0;

  for (const series of allSeries) {
    if (!validPaths.has(series.libraryPath)) {
      // Series folder no longer exists — delete from DB (chapters cascade)
      console.log(`Removing deleted series: ${series.title}`);
      await prisma.series.delete({ where: { id: series.id } });
      seriesRemoved++;
      chaptersRemoved += series._count.chapters;
    }
  }

  return { seriesRemoved, chaptersRemoved };
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

  // Quick check: if series exists and chapter count hasn't changed, skip heavy work
  const hasNewChapters = !series || cbzFiles.length !== series.chapters.length;

  // Only read ComicInfo from first CBZ when needed:
  // - New series (need all metadata)
  // - Series missing key metadata (backfill from updated CBZ files)
  const needsMetadataRead = !series ||
    !series.genres || !series.description;

  const firstCbzPath = join(seriesDirPath, cbzFiles[0]);
  const comicInfo = needsMetadataRead
    ? await extractComicInfo(firstCbzPath)
    : null;

  // Only re-extract cover when there are new chapters or series is new
  const coverPath = hasNewChapters
    ? await extractCover(seriesSlug, seriesDirPath, firstCbzPath)
    : series?.coverPath ?? null;

  if (!series) {
    // Create or update series (upsert by slug to handle library path changes)
    const existingBySlug = await prisma.series.findUnique({
      where: { slug: seriesSlug },
      include: { chapters: true },
    });

    if (existingBySlug) {
      // Series exists with different libraryPath (e.g. migrated to new machine)
      await prisma.series.update({
        where: { id: existingBySlug.id },
        data: {
          libraryPath: seriesDirPath,
          chapterCount: cbzFiles.length,
          coverPath: coverPath || existingBySlug.coverPath,
          description: comicInfo?.Summary || existingBySlug.description,
          author: comicInfo?.Writer || existingBySlug.author,
          artist: comicInfo?.Penciller || existingBySlug.artist,
          genres: comicInfo?.Genre || existingBySlug.genres,
        },
      });
      series = { ...existingBySlug, libraryPath: seriesDirPath };
      result.seriesUpdated++;
    } else {
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
    }
  } else if (hasNewChapters || needsMetadataRead) {
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
        ...(comicInfo?.Summary && !series.description
          ? { description: comicInfo.Summary }
          : {}),
        ...(comicInfo?.Writer && !series.author
          ? { author: comicInfo.Writer }
          : {}),
        ...(comicInfo?.Penciller && !series.artist
          ? { artist: comicInfo.Penciller }
          : {}),
        ...(comicInfo?.Genre && !series.genres
          ? { genres: comicInfo.Genre }
          : {}),
        ...(backfillLastChapter ? { lastChapterAt: backfillLastChapter } : {}),
      },
    });
    result.seriesUpdated++;
  }

  // If no new chapters, skip the per-chapter loop entirely
  if (!hasNewChapters) return;

  // Scan chapters — match by number to handle library path migrations
  const existingByNumber = new Map(
    series.chapters.map((c) => [c.number, c])
  );
  const existingPaths = new Set(series.chapters.map((c) => c.filePath));
  let seriesChaptersAdded = 0;

  for (const cbzFile of cbzFiles) {
    const cbzPath = join(seriesDirPath, cbzFile);
    const chapterNumber = parseChapterNumber(cbzFile);

    // Check if chapter already exists (by path or number)
    const existingByPath = existingPaths.has(cbzPath);
    const existingChapter = existingByNumber.get(chapterNumber);

    if (existingByPath || existingChapter) {
      const existing = existingChapter ||
        series.chapters.find((c: { filePath: string }) => c.filePath === cbzPath);
      if (existing) {
        // Only update if the file path changed (library migration)
        if (existing.filePath !== cbzPath) {
          await prisma.chapter.update({
            where: { id: existing.id },
            data: { filePath: cbzPath },
          });
        }
      }
      continue;
    }

    const chapterComicInfo = await extractComicInfo(cbzPath);
    const pageCount = await getPageCount(cbzPath);
    const fileStat = await stat(cbzPath);

    let source: string | null = null;
    let sourceUrl: string | null = null;
    if (chapterComicInfo?.Web) {
      sourceUrl = String(chapterComicInfo.Web);
      try {
        const url = new URL(sourceUrl);
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
        title: chapterComicInfo?.Title != null ? String(chapterComicInfo.Title) : null,
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
