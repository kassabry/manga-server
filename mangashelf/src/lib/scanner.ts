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
  pathsRemoved: number;
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

      // Strip [Source] prefix from directory name to get clean title
      // e.g. "[Asura] Solo Leveling" -> title: "Solo Leveling", source: "Asura"
      const prefixMatch = entry.name.match(/^\[([^\]]+)\]\s*(.+)$/);
      const seriesTitle = prefixMatch ? prefixMatch[2] : entry.name;
      const dirSourceTag = prefixMatch ? prefixMatch[1] : null;
      const seriesSlug = slugify(seriesTitle);

      try {
        await scanSeries(seriesDirPath, seriesTitle, seriesSlug, type, result, dirSourceTag);
      } catch (err) {
        result.errors.push(
          `Error scanning ${seriesTitle}: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }
  }

  // Remove series/paths from DB that no longer exist on disk
  const cleanup = await cleanupDeletedSeries(validLibraryPaths);
  if (cleanup.seriesRemoved > 0 || cleanup.pathsRemoved > 0) {
    console.log(
      `Cleanup: removed ${cleanup.pathsRemoved} paths, ${cleanup.seriesRemoved} series (${cleanup.chaptersRemoved} chapters) no longer on disk`
    );
  }

  return result;
}

async function cleanupDeletedSeries(
  validPaths: Set<string>
): Promise<ScanCleanup> {
  let seriesRemoved = 0;
  let chaptersRemoved = 0;
  let pathsRemoved = 0;

  // 1. Clean up SeriesPath entries for directories no longer on disk
  const allSeriesPaths = await prisma.seriesPath.findMany({
    include: { series: { select: { id: true, title: true } } },
  });

  for (const sp of allSeriesPaths) {
    if (!validPaths.has(sp.path)) {
      // Delete chapters from this specific directory
      const deleted = await prisma.chapter.deleteMany({
        where: {
          seriesId: sp.seriesId,
          filePath: { startsWith: sp.path },
        },
      });
      chaptersRemoved += deleted.count;

      console.log(`Removing deleted path: ${sp.path} (${deleted.count} chapters)`);
      await prisma.seriesPath.delete({ where: { id: sp.id } });
      pathsRemoved++;
    }
  }

  // 2. Remove series with no remaining paths whose primary libraryPath is also gone
  // (Keeps legacy series that haven't been scanned yet with new code)
  const orphanSeries = await prisma.series.findMany({
    where: {
      libraryPaths: { none: {} },
    },
    select: { id: true, title: true, libraryPath: true, _count: { select: { chapters: true } } },
  });

  for (const s of orphanSeries) {
    if (!validPaths.has(s.libraryPath)) {
      console.log(`Removing orphan series: ${s.title}`);
      await prisma.series.delete({ where: { id: s.id } });
      seriesRemoved++;
      chaptersRemoved += s._count.chapters;
    }
  }

  return { seriesRemoved, chaptersRemoved, pathsRemoved };
}

async function scanSeries(
  seriesDirPath: string,
  seriesTitle: string,
  seriesSlug: string,
  type: string,
  result: ScanResult,
  sourceTag?: string | null
) {
  // Find all CBZ files in this directory
  const files = await readdir(seriesDirPath);
  const cbzFiles = files
    .filter((f) => f.toLowerCase().endsWith(".cbz"))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  if (cbzFiles.length === 0) return;

  // Look up series by slug (primary merge key)
  let series = await prisma.series.findUnique({
    where: { slug: seriesSlug },
    include: { chapters: true },
  });

  // Count chapters from THIS directory only (for accurate change detection)
  const thisDirectoryChapters = series?.chapters.filter(
    (c) => c.filePath.startsWith(seriesDirPath)
  ) ?? [];

  // Quick check: if same number of CBZ files as chapters from this directory, skip heavy work
  const hasNewChapters = !series || cbzFiles.length !== thisDirectoryChapters.length;

  // Only read ComicInfo from first CBZ when needed:
  // - New series (need all metadata)
  // - Series missing key metadata (backfill from updated CBZ files)
  const needsMetadataRead = !series ||
    !series.genres || !series.description;

  const firstCbzPath = join(seriesDirPath, cbzFiles[0]);
  const comicInfo = needsMetadataRead
    ? await extractComicInfo(firstCbzPath)
    : null;

  // Re-extract cover when there are new chapters, series is new, or cover
  // still uses the old /covers/ static path (migrate to /api/covers/)
  const needsCoverUpdate = hasNewChapters ||
    !series?.coverPath ||
    series?.coverPath?.startsWith("/covers/");
  const coverPath = needsCoverUpdate
    ? await extractCover(seriesSlug, seriesDirPath, firstCbzPath)
    : series?.coverPath ?? null;

  if (!series) {
    // Brand new series — create it
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
        publisher: sourceTag || comicInfo?.Publisher || null,
        ageRating: comicInfo?.AgeRating || null,
        chapterCount: cbzFiles.length,
        lastChapterAt: new Date(),
      },
      include: { chapters: true },
    });
    result.seriesAdded++;
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

    // Update series metadata (don't change libraryPath — keep the primary one)
    await prisma.series.update({
      where: { id: series.id },
      data: {
        title: seriesTitle,
        coverPath: coverPath || series.coverPath,
        ...(sourceTag && !series.publisher
          ? { publisher: sourceTag }
          : {}),
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

  // Track this directory as a source path for the series
  await prisma.seriesPath.upsert({
    where: { path: seriesDirPath },
    create: {
      seriesId: series.id,
      path: seriesDirPath,
      source: sourceTag || null,
    },
    update: {
      seriesId: series.id,
      source: sourceTag || null,
    },
  });

  // If no new chapters from this directory, skip the per-chapter loop
  if (!hasNewChapters) return;

  // Scan chapters — only match by filePath (not by number)
  // This allows same chapter number from different sources to coexist
  const existingPaths = new Set(series.chapters.map((c) => c.filePath));
  let seriesChaptersAdded = 0;

  for (const cbzFile of cbzFiles) {
    const cbzPath = join(seriesDirPath, cbzFile);
    const chapterNumber = parseChapterNumber(cbzFile);

    // Skip if this exact file is already in the DB
    if (existingPaths.has(cbzPath)) continue;

    const chapterComicInfo = await extractComicInfo(cbzPath);
    const pageCount = await getPageCount(cbzPath);
    const fileStat = await stat(cbzPath);

    let source: string | null = sourceTag || null;
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
        source = domainMap[domain] || source || domain;
      } catch {
        // Keep sourceTag as source
      }
    }

    await prisma.chapter.upsert({
      where: { filePath: cbzPath },
      create: {
        seriesId: series.id,
        number: chapterNumber,
        title: chapterComicInfo?.Title != null ? String(chapterComicInfo.Title) : null,
        pageCount,
        filePath: cbzPath,
        fileSize: fileStat.size,
        source,
        sourceUrl,
      },
      update: {
        seriesId: series.id,
        number: chapterNumber,
        pageCount,
        fileSize: fileStat.size,
        source,
      },
    });
    result.chaptersAdded++;
    seriesChaptersAdded++;
  }

  // Update chapterCount to reflect total chapters across ALL source directories
  if (seriesChaptersAdded > 0) {
    const totalChapters = await prisma.chapter.count({
      where: { seriesId: series.id },
    });
    await prisma.series.update({
      where: { id: series.id },
      data: {
        chapterCount: totalChapters,
        lastChapterAt: new Date(),
      },
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
