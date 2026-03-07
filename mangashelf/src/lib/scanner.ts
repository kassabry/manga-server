import { readdir, stat } from "fs/promises";
import { join, resolve } from "path";
import { prisma } from "./db";
import { extractComicInfo, getPageCount } from "./cbz";
import { extractEpubMetadata, getEpubPageCount, extractEpubCover } from "./epub";
import { extractCover, extractCoverFromBuffer } from "./covers";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function parseChapterNumber(filename: string): number {
  // Match "Chapter X" pattern
  const match = filename.match(/Chapter\s+(\d+(?:\.\d+)?)/i);
  if (match) return parseFloat(match[1]);

  // Match "Vol. X" pattern for light novels
  const volMatch = filename.match(/Vol\.?\s*(\d+(?:\.\d+)?)/i);
  if (volMatch) return parseFloat(volMatch[1]);

  // Fallback: look for any number pattern before extension
  const numMatch = filename.match(/(\d+(?:\.\d+)?)\s*\.(cbz|epub)$/i);
  if (numMatch) return parseFloat(numMatch[1]);

  return 0;
}

function isBookFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  return lower.endsWith(".cbz") || lower.endsWith(".epub");
}

function isEpub(filename: string): boolean {
  return filename.toLowerCase().endsWith(".epub");
}

// Normalize source tag casing so "Manhuato" and "ManhuaTo" are treated the same
const SOURCE_NORMALIZE: Record<string, string> = {
  manhuato: "ManhuaTo",
  asura: "AsuraScans",
  asurascans: "AsuraScans",
  flame: "FlameComics",
  flamecomics: "FlameComics",
  drake: "DrakeComic",
  drakecomic: "DrakeComic",
  mangadex: "MangaDex",
  lightnovelpub: "LightNovelPub",
  novelbin: "NovelBin",
  webtoon: "Webtoon",
};

function normalizeSource(raw: string): string {
  return SOURCE_NORMALIZE[raw.toLowerCase()] || raw;
}

// Strip [Source] prefix from a title string (e.g. from ComicInfo.xml metadata)
function stripSourcePrefix(title: string): string {
  return title.replace(/^\[[^\]]+\]\s*/, "");
}

/**
 * Detect a more accurate type (Manga/Manhwa/Manhua) from genre tags
 * and/or the series description. ManhuaTo hosts all types but files
 * end up in the Manhua/ directory.
 *
 * Checks in order:
 * 1. Genre tags (explicit type labels like "Manga", "Manhwa")
 * 2. Description text (e.g. "Dungeon Odyssey Manhwa The descendants...")
 */
function detectTypeFromMetadata(
  genres: string | null,
  description: string | null,
  fallback: string
): string {
  // Check genre tags first (most reliable)
  if (genres) {
    const tags = genres.toLowerCase().split(",").map((g) => g.trim());
    if (tags.includes("manga")) return "Manga";
    if (tags.includes("manhwa")) return "Manhwa";
    if (tags.includes("manhua")) return "Manhua";
  }

  // Check description text for type keywords near the start
  // Many ManhuaTo descriptions begin with "{Title} Manhwa ..." or "{Title} Manga ..."
  if (description) {
    const descStart = description.slice(0, 200).toLowerCase();
    // Look for standalone type words (word boundary match)
    if (/\bmanhwa\b/.test(descStart)) return "Manhwa";
    if (/\bmanga\b/.test(descStart)) return "Manga";
    if (/\bmanhua\b/.test(descStart)) return "Manhua";
  }

  return fallback;
}

/**
 * Sanitize author/artist values that are obviously garbage from scraping.
 * Examples: "s:", "s", single chars, just punctuation, etc.
 */
function sanitizePersonName(name: string | null | undefined): string | null {
  if (!name) return null;
  // Strip leading/trailing whitespace
  const trimmed = name.trim();
  // Reject if too short (single char + optional punctuation)
  if (trimmed.length <= 2) return null;
  // Reject if it's just punctuation/symbols
  if (/^[\W_]+$/.test(trimmed)) return null;
  return trimmed;
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
      const dirSourceTag = prefixMatch ? normalizeSource(prefixMatch[1]) : null;
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
  // Find all book files (CBZ + EPUB) in this directory
  const files = await readdir(seriesDirPath);
  const bookFiles = files
    .filter((f) => isBookFile(f))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  if (bookFiles.length === 0) return;

  // Look up series by slug (primary merge key for cross-source merging)
  let series = await prisma.series.findUnique({
    where: { slug: seriesSlug },
    include: { chapters: true },
  });

  // Fallback: look up by libraryPath for backward compatibility
  // Old DB entries may have slugs that include [Source] prefix (e.g. "asura-solo-leveling")
  // while the new scanner generates stripped slugs (e.g. "solo-leveling")
  if (!series) {
    const existingByPath = await prisma.series.findFirst({
      where: { libraryPath: seriesDirPath },
      include: { chapters: true },
    });

    if (existingByPath) {
      // Found by path but not by slug — migrate to new stripped slug/title
      try {
        await prisma.series.update({
          where: { id: existingByPath.id },
          data: { slug: seriesSlug, title: seriesTitle },
        });
        console.log(`Migrated series: "${existingByPath.title}" → "${seriesTitle}" (slug: ${existingByPath.slug} → ${seriesSlug})`);
        existingByPath.slug = seriesSlug;
        existingByPath.title = seriesTitle;
        series = existingByPath;
      } catch {
        // Slug collision: another series already has this slug (e.g. from a different source dir)
        // Merge this series' chapters into that canonical series
        const canonical = await prisma.series.findUnique({
          where: { slug: seriesSlug },
          include: { chapters: true },
        });
        if (canonical) {
          console.log(`Merging duplicate series "${existingByPath.title}" into "${canonical.title}"`);
          // Move chapters from old series to canonical
          await prisma.chapter.updateMany({
            where: { seriesId: existingByPath.id },
            data: { seriesId: canonical.id },
          });
          // Move SeriesPath entries
          await prisma.seriesPath.updateMany({
            where: { seriesId: existingByPath.id },
            data: { seriesId: canonical.id },
          }).catch(() => {});
          // Delete old duplicate (cascades remaining relations)
          await prisma.series.delete({ where: { id: existingByPath.id } });
          // Refresh canonical with merged chapters
          series = await prisma.series.findUnique({
            where: { id: canonical.id },
            include: { chapters: true },
          });
        } else {
          // Shouldn't happen, but use the existing series as-is
          series = existingByPath;
        }
      }
    }
  }

  // Count chapters from THIS directory only (for accurate change detection)
  const thisDirectoryChapters = series?.chapters.filter(
    (c) => c.filePath.startsWith(seriesDirPath)
  ) ?? [];

  // Quick check: if same number of book files as chapters from this directory, skip heavy work
  const hasNewChapters = !series || bookFiles.length !== thisDirectoryChapters.length;

  // Only read metadata from first book when needed:
  // - New series (need all metadata)
  // - Series missing key metadata (backfill)
  const needsMetadataRead = !series ||
    !series.genres || !series.description;

  const firstBookPath = join(seriesDirPath, bookFiles[0]);
  const firstIsEpub = isEpub(bookFiles[0]);

  // Extract metadata from first book (CBZ ComicInfo.xml or EPUB OPF)
  const comicInfo = needsMetadataRead
    ? (firstIsEpub
      ? await extractEpubMetadata(firstBookPath)
      : await extractComicInfo(firstBookPath))
    : null;

  // Re-extract cover when there are new chapters, series is new, or cover
  // still uses the old /covers/ static path (migrate to /api/covers/)
  const needsCoverUpdate = hasNewChapters ||
    !series?.coverPath ||
    series?.coverPath?.startsWith("/covers/");

  let coverPath = series?.coverPath ?? null;
  if (needsCoverUpdate) {
    if (firstIsEpub) {
      // Extract cover from EPUB
      const coverBuffer = await extractEpubCover(firstBookPath);
      if (coverBuffer) {
        coverPath = await extractCoverFromBuffer(seriesSlug, coverBuffer);
      } else {
        // Try directory-level cover files only
        coverPath = await extractCover(seriesSlug, seriesDirPath);
      }
    } else {
      coverPath = await extractCover(seriesSlug, seriesDirPath, firstBookPath);
    }
  }

  // Force-update title if it still has a [Source] prefix (from old scans or ComicInfo metadata)
  if (series && /^\[.+\]/.test(series.title) && series.title !== seriesTitle) {
    await prisma.series.update({
      where: { id: series.id },
      data: { title: seriesTitle },
    });
    series.title = seriesTitle;
  }

  // Detect accurate type from genre tags and description (e.g. ManhuaTo puts
  // everything in Manhua/ but genres or description may say "Manga" or "Manhwa")
  const genreStr = comicInfo?.Genre || series?.genres || null;
  const descStr = comicInfo?.Summary || series?.description || null;
  const detectedType = detectTypeFromMetadata(genreStr, descStr, type);

  // Sanitize author/artist from metadata (scraper sometimes produces garbage like "s:")
  const cleanAuthor = sanitizePersonName(comicInfo?.Writer);
  const cleanArtist = sanitizePersonName(comicInfo?.Penciller);

  // Normalize the publisher/source tag
  const normalizedPublisher = sourceTag
    ? normalizeSource(sourceTag)
    : comicInfo?.Publisher
      ? normalizeSource(comicInfo.Publisher)
      : null;

  if (!series) {
    // Brand new series — create it
    const cleanMetaTitle = comicInfo?.Series ? stripSourcePrefix(comicInfo.Series) : null;
    series = await prisma.series.create({
      data: {
        title: cleanMetaTitle || seriesTitle,
        slug: seriesSlug,
        description: comicInfo?.Summary || null,
        author: cleanAuthor,
        artist: cleanArtist,
        status: parseStatus(comicInfo?.Notes),
        type: detectedType,
        genres: comicInfo?.Genre || null,
        rating: comicInfo?.CommunityRating
          ? parseFloat(comicInfo.CommunityRating)
          : null,
        coverPath,
        libraryPath: seriesDirPath,
        publisher: normalizedPublisher,
        ageRating: comicInfo?.AgeRating || null,
        chapterCount: bookFiles.length,
        lastChapterAt: new Date(),
      },
      include: { chapters: true },
    });
    result.seriesAdded++;
  } else {
    // Existing series — build correction fields that always apply
    const corrections: Record<string, unknown> = {};

    // Force-correct type if genre tags indicate a different type
    // (e.g. series is in Manhua/ dir but genres say "Manga")
    if (detectedType !== series.type) {
      corrections.type = detectedType;
    }

    // Force-normalize publisher if stale casing (e.g. "Manhuato" → "ManhuaTo")
    if (normalizedPublisher && series.publisher !== normalizedPublisher) {
      corrections.publisher = normalizedPublisher;
    }

    // Fix garbage author/artist (e.g. "s:", single chars) — replace with clean value or null
    if (!sanitizePersonName(series.author)) {
      corrections.author = cleanAuthor;
    }
    if (!sanitizePersonName(series.artist)) {
      corrections.artist = cleanArtist;
    }

    if (hasNewChapters || needsMetadataRead) {
      // Backfill lastChapterAt for series that existed before this field was added
      if (!series.lastChapterAt) {
        try {
          const lastBook = join(seriesDirPath, bookFiles[bookFiles.length - 1]);
          const lastStat = await stat(lastBook);
          corrections.lastChapterAt = lastStat.mtime;
        } catch {}
      }

      // Backfill missing metadata from ComicInfo
      if (comicInfo?.Summary && !series.description) corrections.description = comicInfo.Summary;
      if (comicInfo?.Genre && !series.genres) corrections.genres = comicInfo.Genre;

      corrections.title = seriesTitle;
      corrections.coverPath = coverPath || series.coverPath;
    }

    // Only write to DB if there are actual corrections
    if (Object.keys(corrections).length > 0) {
      await prisma.series.update({
        where: { id: series.id },
        data: corrections,
      });
      result.seriesUpdated++;
    }
  }

  // Track this directory as a source path for the series
  const normalizedSourceTag = sourceTag ? normalizeSource(sourceTag) : null;
  await prisma.seriesPath.upsert({
    where: { path: seriesDirPath },
    create: {
      seriesId: series.id,
      path: seriesDirPath,
      source: normalizedSourceTag,
    },
    update: {
      seriesId: series.id,
      source: normalizedSourceTag,
    },
  });

  // Clean up chapters whose files no longer exist on disk
  const diskFiles = new Set(bookFiles.map((f) => join(seriesDirPath, f)));
  const staleChapters = series.chapters.filter(
    (c) => c.filePath.startsWith(seriesDirPath) && !diskFiles.has(c.filePath)
  );
  if (staleChapters.length > 0) {
    const staleIds = staleChapters.map((c) => c.id);
    // Delete read progress first (foreign key constraint)
    await prisma.readProgress.deleteMany({ where: { chapterId: { in: staleIds } } });
    await prisma.chapter.deleteMany({ where: { id: { in: staleIds } } });
    console.log(
      `Removed ${staleChapters.length} chapters with missing files from "${seriesTitle}": ${staleChapters.map((c) => `Ch.${c.number}`).join(", ")}`
    );
  }

  // If no new chapters from this directory, skip the per-chapter loop
  if (!hasNewChapters && staleChapters.length === 0) return;

  // Scan chapters — only match by filePath (not by number)
  // This allows same chapter number from different sources to coexist
  const existingPaths = new Set(series.chapters.filter((c) => !staleChapters.includes(c)).map((c) => c.filePath));
  let seriesChaptersAdded = 0;

  for (const bookFile of bookFiles) {
    const bookPath = join(seriesDirPath, bookFile);
    const chapterNumber = parseChapterNumber(bookFile);
    const bookIsEpub = isEpub(bookFile);

    // Skip if this exact file is already in the DB
    if (existingPaths.has(bookPath)) continue;

    // Extract metadata and page count based on file type
    const chapterMeta = bookIsEpub
      ? await extractEpubMetadata(bookPath)
      : await extractComicInfo(bookPath);

    const pageCount = bookIsEpub
      ? await getEpubPageCount(bookPath)
      : await getPageCount(bookPath);

    const fileStat = await stat(bookPath);

    let source: string | null = sourceTag ? normalizeSource(sourceTag) : null;
    let sourceUrl: string | null = null;
    if (chapterMeta?.Web) {
      sourceUrl = String(chapterMeta.Web);
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
          "lightnovelpub.com": "LightNovelPub",
          "novelbin.com": "NovelBin",
        };
        source = domainMap[domain] || source || domain;
      } catch {
        // Keep sourceTag as source
      }
    }

    // Use publisher from EPUB metadata as source if no other source
    if (!source && bookIsEpub && chapterMeta?.Publisher) {
      source = chapterMeta.Publisher;
    }

    await prisma.chapter.upsert({
      where: { filePath: bookPath },
      create: {
        seriesId: series.id,
        number: chapterNumber,
        title: chapterMeta?.Title != null ? String(chapterMeta.Title) : null,
        pageCount,
        filePath: bookPath,
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

  // Normalize source tags on existing chapters from this directory
  // Fixes inconsistent casing like "Manhuato" → "ManhuaTo"
  if (sourceTag) {
    const normalized = normalizeSource(sourceTag);
    await prisma.chapter.updateMany({
      where: {
        seriesId: series.id,
        filePath: { startsWith: seriesDirPath },
        source: { not: normalized },
      },
      data: { source: normalized },
    });
  }

  // Update chapterCount to reflect total chapters across ALL source directories
  if (seriesChaptersAdded > 0 || staleChapters.length > 0) {
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
