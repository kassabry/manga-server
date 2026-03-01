import { readFile, writeFile, access, mkdir, stat } from "fs/promises";
import { join, dirname } from "path";
import JSZip from "jszip";

const COVERS_DIR = join(process.cwd(), "public", "covers");

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

export async function extractCover(
  seriesSlug: string,
  seriesDirPath: string,
  firstCbzPath?: string
): Promise<string | null> {
  const coverOutputPath = join(COVERS_DIR, `${seriesSlug}.jpg`);

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
      return `/covers/${seriesSlug}.jpg`;
    } catch {
      continue;
    }
  }

  // If cached version exists and no cover.* in series dir, use it
  if (await fileExists(coverOutputPath)) {
    return `/covers/${seriesSlug}.jpg`;
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
        return `/covers/${seriesSlug}.jpg`;
      }
    } catch {
      // Fall through
    }
  }

  return null;
}

export function getCoverUrl(seriesSlug: string): string {
  return `/covers/${seriesSlug}.jpg`;
}
