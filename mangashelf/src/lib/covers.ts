import { readFile, writeFile, access, mkdir, stat } from "fs/promises";
import { join } from "path";
import JSZip from "jszip";

// Store covers in the data directory (writable, volume-mounted)
// rather than public/ which has permission issues with standalone mode
const COVERS_DIR = join(process.cwd(), "data", "covers");

async function ensureDir(dir: string) {
  try {
    await access(dir);
  } catch {
    await mkdir(dir, { recursive: true });
  }
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function getMtime(path: string): Promise<number> {
  try {
    const s = await stat(path);
    return s.mtimeMs;
  } catch {
    return 0;
  }
}

export function getCoversDir(): string {
  return COVERS_DIR;
}

/** Normalize a source name to a safe filename component (lowercase, alphanumeric only). */
export function normalizeSourceForFilename(source: string): string {
  return source.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Return the filesystem path for a source-specific cover file. */
export function sourceCoverPath(seriesSlug: string, source: string): string {
  return join(COVERS_DIR, `${seriesSlug}-${normalizeSourceForFilename(source)}.dat`);
}

/**
 * Save image data to both the main cover ({slug}.dat) and an optional
 * source-specific cover ({slug}-{source}.dat).
 */
async function writeCoverData(
  seriesSlug: string,
  data: Buffer,
  source?: string | null
): Promise<void> {
  await ensureDir(COVERS_DIR);
  const mainPath = join(COVERS_DIR, `${seriesSlug}.dat`);
  await writeFile(mainPath, data);
  if (source) {
    await writeFile(sourceCoverPath(seriesSlug, source), data);
  }
}

export async function extractCover(
  seriesSlug: string,
  seriesDirPath: string,
  firstCbzPath?: string,
  source?: string | null
): Promise<string | null> {
  const coverOutputPath = join(COVERS_DIR, `${seriesSlug}.dat`);

  await ensureDir(COVERS_DIR);

  // Strategy 1: Look for cover.jpg/cover.png in series directory (always preferred).
  // A directory-level cover is always authoritative — always overwrite the cache so
  // that covers added or replaced after the initial scan are picked up reliably,
  // regardless of file timestamps (which can be stale when files are transferred).
  const coverExtensions = [".jpg", ".jpeg", ".png", ".webp"];
  for (const ext of coverExtensions) {
    const coverPath = join(seriesDirPath, `cover${ext}`);
    try {
      await access(coverPath);
      const coverData = await readFile(coverPath);
      await writeCoverData(seriesSlug, coverData, source);
      return `/api/covers/${seriesSlug}`;
    } catch {
      continue;
    }
  }

  // If cached version exists and no cover.* in series dir, use it
  if (await fileExists(coverOutputPath)) {
    // Still save the source-specific copy if it doesn't exist yet
    if (source) {
      const srcPath = sourceCoverPath(seriesSlug, source);
      if (!(await fileExists(srcPath))) {
        try {
          const existing = await readFile(coverOutputPath);
          await writeFile(srcPath, existing);
        } catch {
          // Non-fatal
        }
      }
    }
    return `/api/covers/${seriesSlug}`;
  }

  // Strategy 2: Extract from first CBZ file (!000_cover.* or first image)
  if (firstCbzPath) {
    try {
      const data = await readFile(firstCbzPath);
      const zip = await JSZip.loadAsync(data);
      const files = Object.keys(zip.files).sort((a, b) =>
        a.localeCompare(b, undefined, { numeric: true })
      );

      // Look for cover image first
      const coverFile = files.find((f) => f.toLowerCase().includes("cover"));
      const targetFile = coverFile || files.find((f) => {
        const ext = f.toLowerCase();
        return (
          (ext.endsWith(".jpg") ||
            ext.endsWith(".jpeg") ||
            ext.endsWith(".png") ||
            ext.endsWith(".webp")) &&
          !ext.includes("comicinfo")
        );
      });

      if (targetFile) {
        const imgData = await zip.file(targetFile)!.async("nodebuffer");
        await writeCoverData(seriesSlug, imgData, source);
        return `/api/covers/${seriesSlug}`;
      }
    } catch {
      // Fall through
    }
  }

  return null;
}

/**
 * Save a cover image from a raw buffer (e.g. extracted from EPUB)
 */
export async function extractCoverFromBuffer(
  seriesSlug: string,
  coverData: Buffer,
  source?: string | null
): Promise<string | null> {
  try {
    await writeCoverData(seriesSlug, coverData, source);
    return `/api/covers/${seriesSlug}`;
  } catch {
    return null;
  }
}

export function getCoverUrl(seriesSlug: string): string {
  return `/api/covers/${seriesSlug}`;
}
