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

export async function extractCover(
  seriesSlug: string,
  seriesDirPath: string,
  firstCbzPath?: string
): Promise<string | null> {
  const coverOutputPath = join(COVERS_DIR, `${seriesSlug}.dat`);

  await ensureDir(COVERS_DIR);

  // Strategy 1: Look for cover.jpg/cover.png in series directory (always preferred)
  const coverExtensions = [".jpg", ".jpeg", ".png", ".webp"];
  for (const ext of coverExtensions) {
    const coverPath = join(seriesDirPath, `cover${ext}`);
    try {
      await access(coverPath);
      // Check if series cover is newer than cached version
      const srcMtime = await getMtime(coverPath);
      const cacheMtime = await getMtime(coverOutputPath);
      if (srcMtime > cacheMtime || cacheMtime === 0) {
        const coverData = await readFile(coverPath);
        await writeFile(coverOutputPath, coverData);
      }
      return `/api/covers/${seriesSlug}`;
    } catch {
      continue;
    }
  }

  // If cached version exists and no cover.* in series dir, use it
  if (await fileExists(coverOutputPath)) {
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
        await writeFile(coverOutputPath, imgData);
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
  coverData: Buffer
): Promise<string | null> {
  try {
    const coverOutputPath = join(COVERS_DIR, `${seriesSlug}.dat`);
    await ensureDir(COVERS_DIR);
    await writeFile(coverOutputPath, coverData);
    return `/api/covers/${seriesSlug}`;
  } catch {
    return null;
  }
}

export function getCoverUrl(seriesSlug: string): string {
  return `/api/covers/${seriesSlug}`;
}
