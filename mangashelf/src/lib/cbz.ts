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

/**
 * Read image width from the raw file header bytes (no external deps needed).
 * Supports PNG, JPEG, WebP, GIF.
 */
function getImageWidth(buf: Buffer): number {
  if (buf.length < 30) return 0;

  // PNG: bytes 16-19 = width (big-endian)
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return buf.readUInt32BE(16);
  }

  // GIF: bytes 6-7 = width (little-endian)
  if (buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46) {
    return buf.readUInt16LE(6);
  }

  // WebP: RIFF....WEBP
  if (
    buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46 &&
    buf[8] === 0x57 && buf[9] === 0x45 && buf[10] === 0x42 && buf[11] === 0x50
  ) {
    // VP8 (lossy)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x20) {
      if (buf.length > 27) return buf.readUInt16LE(26) & 0x3fff;
    }
    // VP8L (lossless)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x4c) {
      if (buf.length > 24) {
        const bits = buf.readUInt32LE(21);
        return (bits & 0x3fff) + 1;
      }
    }
    // VP8X (extended)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x58) {
      if (buf.length > 26) return (buf[24] | (buf[25] << 8) | (buf[26] << 16)) + 1;
    }
  }

  // JPEG: scan for SOF marker
  if (buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset < buf.length - 8) {
      if (buf[offset] !== 0xff) { offset++; continue; }
      const marker = buf[offset + 1];
      // SOF markers (0xC0-0xCF except 0xC4 DHT and 0xCC DAC)
      if (
        marker >= 0xc0 && marker <= 0xcf &&
        marker !== 0xc4 && marker !== 0xcc
      ) {
        return buf.readUInt16BE(offset + 7);
      }
      if (marker === 0xd9) break; // EOI
      if (marker === 0xda) break; // SOS — no SOF found before scan data
      const segLen = buf.readUInt16BE(offset + 2);
      offset += 2 + segLen;
    }
  }

  return 0;
}

/**
 * Filter out promotional/cover images from other series that got scraped
 * alongside chapter pages. Works by comparing image widths — chapter pages
 * share a consistent width, while promo covers are typically different.
 *
 * Safety rules:
 *  - Only runs when 5+ images exist (needs enough to detect outliers)
 *  - The dominant width group must account for ≥60% of images (otherwise
 *    the chapter genuinely has mixed-width content and we skip filtering)
 *  - Never removes more than 20% of total images (prevents over-filtering
 *    on chapters that legitimately have some double-page spreads or title
 *    pages with different widths)
 */
async function filterOutlierImages(
  zip: JSZip,
  pages: string[]
): Promise<string[]> {
  if (pages.length < 5) return pages;

  // Read width of each image from its header bytes (only first 512 bytes needed)
  const entries: { name: string; width: number }[] = [];
  for (const page of pages) {
    const file = zip.file(page);
    if (!file) continue;
    const buf = Buffer.from(await file.async("arraybuffer"));
    entries.push({ name: page, width: getImageWidth(buf) });
  }

  const validEntries = entries.filter((e) => e.width > 0);
  if (validEntries.length < 5) return pages;

  // Group images by width (±5% tolerance buckets)
  const widthGroups = new Map<number, number>(); // representative width → count
  for (const e of validEntries) {
    let matched = false;
    for (const [rep, count] of widthGroups) {
      if (Math.abs(e.width - rep) / rep <= 0.05) {
        widthGroups.set(rep, count + 1);
        matched = true;
        break;
      }
    }
    if (!matched) widthGroups.set(e.width, 1);
  }

  // Find the dominant width group
  let dominantWidth = 0;
  let dominantCount = 0;
  for (const [width, count] of widthGroups) {
    if (count > dominantCount) {
      dominantCount = count;
      dominantWidth = width;
    }
  }

  // Safety: if the dominant group is less than 60% of valid images, the chapter
  // has genuinely mixed-width content — skip filtering entirely
  if (dominantCount / validEntries.length < 0.6) {
    return pages;
  }

  // Keep images within 30% of the dominant width (or those we couldn't read)
  const filtered = entries
    .filter((e) => e.width === 0 || Math.abs(e.width - dominantWidth) / dominantWidth <= 0.3)
    .map((e) => e.name);

  const removed = pages.length - filtered.length;

  // Safety cap: never remove more than 20% of total images
  if (removed > pages.length * 0.2) {
    console.log(
      `CBZ outlier filter: would remove ${removed}/${pages.length} images (${Math.round(removed / pages.length * 100)}%) — too aggressive, skipping (dominant ${dominantWidth}px)`
    );
    return pages;
  }

  if (removed > 0) {
    console.log(
      `CBZ outlier filter: removed ${removed}/${pages.length} images with non-matching widths (dominant ${dominantWidth}px)`
    );
  }

  return filtered;
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
      !relativePath.includes("ComicInfo") &&
      !relativePath.toLowerCase().includes("cover")
    ) {
      pages.push(relativePath);
    }
  });

  pages.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  // Filter outlier images by dimension (removes promo covers from other series)
  const filtered = await filterOutlierImages(zip, pages);

  pageListCache.set(cbzPath, filtered);
  return filtered;
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
    return pages.length;
  } catch {
    return 0;
  }
}
