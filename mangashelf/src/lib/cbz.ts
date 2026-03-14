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
 * Read image dimensions from raw file header bytes (no external deps needed).
 * Supports PNG, JPEG, WebP, GIF.
 */
function getImageDimensions(buf: Buffer): { width: number; height: number } {
  const zero = { width: 0, height: 0 };
  if (buf.length < 30) return zero;

  // PNG: bytes 16-19 = width (BE), 20-23 = height (BE)
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
  }

  // GIF: bytes 6-7 = width (LE), 8-9 = height (LE)
  if (buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46) {
    return { width: buf.readUInt16LE(6), height: buf.readUInt16LE(8) };
  }

  // WebP: RIFF....WEBP
  if (
    buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46 &&
    buf[8] === 0x57 && buf[9] === 0x45 && buf[10] === 0x42 && buf[11] === 0x50
  ) {
    // VP8 (lossy)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x20) {
      if (buf.length > 29) return {
        width: (buf.readUInt16LE(26) & 0x3fff) + 1,
        height: (buf.readUInt16LE(28) & 0x3fff) + 1,
      };
    }
    // VP8L (lossless)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x4c) {
      if (buf.length > 24) {
        const bits = buf.readUInt32LE(21);
        return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 };
      }
    }
    // VP8X (extended)
    if (buf[12] === 0x56 && buf[13] === 0x50 && buf[14] === 0x38 && buf[15] === 0x58) {
      if (buf.length > 29) return {
        width: (buf[24] | (buf[25] << 8) | (buf[26] << 16)) + 1,
        height: (buf[27] | (buf[28] << 8) | (buf[29] << 16)) + 1,
      };
    }
  }

  // JPEG: scan for SOF marker
  if (buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset < buf.length - 8) {
      if (buf[offset] !== 0xff) { offset++; continue; }
      const marker = buf[offset + 1];
      // SOF markers (0xC0-0xCF except 0xC4 DHT and 0xCC DAC)
      if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xcc) {
        return { width: buf.readUInt16BE(offset + 7), height: buf.readUInt16BE(offset + 5) };
      }
      if (marker === 0xd9 || marker === 0xda) break;
      const segLen = buf.readUInt16BE(offset + 2);
      offset += 2 + segLen;
    }
  }

  return zero;
}

/**
 * Filter out promotional/cover images from other series that got scraped
 * alongside chapter pages. Works by comparing image widths — chapter pages
 * share a consistent width, while promo covers have varied different widths.
 *
 * Safety: only filters when there's a clear dominant width group (≥5 images
 * and at least 2x the size of the next-largest group). This ensures we only
 * act when there's strong evidence of a single "chapter width", and avoids
 * filtering chapters that genuinely have mixed-width content.
 */
async function filterOutlierImages(
  zip: JSZip,
  pages: string[]
): Promise<string[]> {
  if (pages.length < 5) return pages;

  // Read dimensions of each image from its header bytes
  const entries: { name: string; width: number; height: number }[] = [];
  for (const page of pages) {
    const file = zip.file(page);
    if (!file) continue;
    const buf = Buffer.from(await file.async("arraybuffer"));
    const { width, height } = getImageDimensions(buf);
    entries.push({ name: page, width, height });
  }

  const validEntries = entries.filter((e) => e.width > 0);
  if (validEntries.length < 5) return pages;

  // Group images by width (±5% tolerance buckets), tracking count and total aspect ratio
  const widthGroups: { rep: number; count: number; totalAspect: number }[] = [];
  for (const e of validEntries) {
    const match = widthGroups.find((g) => Math.abs(e.width - g.rep) / g.rep <= 0.05);
    if (match) {
      match.count++;
      match.totalAspect += e.height / e.width;
    } else {
      widthGroups.push({ rep: e.width, count: 1, totalAspect: e.height / e.width });
    }
  }

  widthGroups.sort((a, b) => b.count - a.count);

  const avgAspect = (g: { count: number; totalAspect: number }) => g.totalAspect / g.count;

  const dominant = widthGroups[0];
  const secondLargest = widthGroups[1]?.count ?? 0;

  // Webtoon strip detection: if a non-dominant group has avg aspect ratio ≥ 5:1
  // (tall vertical strips) and the dominant group is ≤ 3:1 (promo covers / manga pages),
  // prefer the tall-strip group even though it has fewer images.
  // This handles: 4 webtoon strips (800px × 15000px) vs 9 promo covers (2000px × 2800px).
  const webtoonGroup = widthGroups.find((g) => g !== dominant && avgAspect(g) >= 5.0);
  if (webtoonGroup && avgAspect(dominant) < 3.0) {
    const filtered = entries
      .filter((e) => e.width === 0 || Math.abs(e.width - webtoonGroup.rep) / webtoonGroup.rep <= 0.3)
      .map((e) => e.name);
    const removed = pages.length - filtered.length;
    if (removed > 0) {
      console.log(
        `CBZ outlier filter: removed ${removed}/${pages.length} images ` +
        `(webtoon strips ${webtoonGroup.rep}px avg ${avgAspect(webtoonGroup).toFixed(1)}:1 ` +
        `preferred over ${dominant.rep}px avg ${avgAspect(dominant).toFixed(1)}:1)`
      );
    }
    return filtered;
  }

  // Normal case: keep the dominant width group if clearly dominant
  // (≥5 images AND at least 2× the next-largest group)
  if (dominant.count < 5 || dominant.count < secondLargest * 2) {
    return pages;
  }

  const filtered = entries
    .filter((e) => e.width === 0 || Math.abs(e.width - dominant.rep) / dominant.rep <= 0.3)
    .map((e) => e.name);

  const removed = pages.length - filtered.length;
  if (removed > 0) {
    console.log(
      `CBZ outlier filter: removed ${removed}/${pages.length} images (dominant ${dominant.rep}px, ${dominant.count} pages)`
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
