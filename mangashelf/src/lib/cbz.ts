import JSZip from "jszip";
import { readFile } from "fs/promises";
import { XMLParser } from "fast-xml-parser";
import type { ComicInfo } from "./types";

const xmlParser = new XMLParser({
  ignoreAttributes: false,
  trimValues: true,
});

// LRU cache for loaded ZIP objects — avoids re-reading CBZ from disk on every page
const ZIP_CACHE_MAX = 10;
const zipCache = new Map<string, { zip: JSZip; lastAccess: number }>();

async function getZip(cbzPath: string): Promise<JSZip> {
  const cached = zipCache.get(cbzPath);
  if (cached) {
    cached.lastAccess = Date.now();
    return cached.zip;
  }

  const data = await readFile(cbzPath);
  const zip = await JSZip.loadAsync(data);

  // Evict oldest entry if cache is full
  if (zipCache.size >= ZIP_CACHE_MAX) {
    let oldestKey = "";
    let oldestTime = Infinity;
    for (const [key, entry] of zipCache) {
      if (entry.lastAccess < oldestTime) {
        oldestTime = entry.lastAccess;
        oldestKey = key;
      }
    }
    if (oldestKey) zipCache.delete(oldestKey);
  }

  zipCache.set(cbzPath, { zip, lastAccess: Date.now() });
  return zip;
}

// Cache page lists separately (lightweight, can keep more)
const pageListCache = new Map<string, string[]>();

export async function extractComicInfo(
  cbzPath: string
): Promise<ComicInfo | null> {
  try {
    const zip = await getZip(cbzPath);
    const comicInfoFile = zip.file("ComicInfo.xml");
    if (!comicInfoFile) return null;

    const xmlContent = await comicInfoFile.async("string");
    const parsed = xmlParser.parse(xmlContent);
    return parsed.ComicInfo || null;
  } catch {
    return null;
  }
}

export async function getPageList(cbzPath: string): Promise<string[]> {
  const cached = pageListCache.get(cbzPath);
  if (cached) return cached;

  const zip = await getZip(cbzPath);

  const imageExtensions = [".jpg", ".jpeg", ".png", ".webp", ".gif"];
  const pages: string[] = [];

  zip.forEach((relativePath) => {
    const ext = relativePath.toLowerCase().slice(relativePath.lastIndexOf("."));
    if (
      imageExtensions.includes(ext) &&
      !relativePath.startsWith("__MACOSX") &&
      !relativePath.includes("ComicInfo")
    ) {
      pages.push(relativePath);
    }
  });

  const sorted = pages.sort((a, b) => {
    const aIsCover = a.toLowerCase().includes("cover");
    const bIsCover = b.toLowerCase().includes("cover");
    if (aIsCover && !bIsCover) return -1;
    if (!aIsCover && bIsCover) return 1;
    return a.localeCompare(b, undefined, { numeric: true });
  });

  pageListCache.set(cbzPath, sorted);
  return sorted;
}

export async function extractPage(
  cbzPath: string,
  pageName: string
): Promise<{ data: Buffer; mimeType: string } | null> {
  try {
    const zip = await getZip(cbzPath);
    const pageFile = zip.file(pageName);
    if (!pageFile) return null;

    const data = Buffer.from(await pageFile.async("arraybuffer"));
    const ext = pageName.toLowerCase().slice(pageName.lastIndexOf("."));
    const mimeTypes: Record<string, string> = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
      ".gif": "image/gif",
    };

    return { data, mimeType: mimeTypes[ext] || "image/jpeg" };
  } catch {
    return null;
  }
}

export async function getPageCount(cbzPath: string): Promise<number> {
  try {
    const pages = await getPageList(cbzPath);
    return pages.filter((p) => !p.toLowerCase().includes("cover")).length;
  } catch {
    return 0;
  }
}
