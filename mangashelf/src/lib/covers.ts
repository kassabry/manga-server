import { readFile, writeFile, access, mkdir } from "fs/promises";
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

export async function extractCover(
  seriesSlug: string,
  seriesDirPath: string,
  firstCbzPath?: string
): Promise<string | null> {
  const coverOutputPath = join(COVERS_DIR, `${seriesSlug}.jpg`);

  // Check if already cached
  try {
    await access(coverOutputPath);
    return `/covers/${seriesSlug}.jpg`;
  } catch {
    // Need to extract
  }

  await ensureDir(COVERS_DIR);

  // Strategy 1: Look for cover.jpg/cover.png in series directory
  const coverExtensions = [".jpg", ".jpeg", ".png", ".webp"];
  for (const ext of coverExtensions) {
    const coverPath = join(seriesDirPath, `cover${ext}`);
    try {
      await access(coverPath);
      const coverData = await readFile(coverPath);
      await writeFile(coverOutputPath, coverData);
      return `/covers/${seriesSlug}.jpg`;
    } catch {
      continue;
    }
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
