import JSZip from "jszip";
import { readFile } from "fs/promises";
import { XMLParser } from "fast-xml-parser";
import type { ComicInfo } from "./types";

const xmlParser = new XMLParser({
  ignoreAttributes: false,
  trimValues: true,
});

// LRU cache for loaded EPUB ZIP objects
const EPUB_CACHE_MAX = 5;
const epubCache = new Map<string, { zip: JSZip; lastAccess: number }>();

async function getEpubZip(epubPath: string): Promise<JSZip> {
  const cached = epubCache.get(epubPath);
  if (cached) {
    cached.lastAccess = Date.now();
    return cached.zip;
  }

  const data = await readFile(epubPath);
  const zip = await JSZip.loadAsync(data);

  // Evict oldest entry if cache is full
  if (epubCache.size >= EPUB_CACHE_MAX) {
    let oldestKey = "";
    let oldestTime = Infinity;
    for (const [key, entry] of epubCache) {
      if (entry.lastAccess < oldestTime) {
        oldestTime = entry.lastAccess;
        oldestKey = key;
      }
    }
    if (oldestKey) epubCache.delete(oldestKey);
  }

  epubCache.set(epubPath, { zip, lastAccess: Date.now() });
  return zip;
}

/**
 * Find the OPF content file path from the EPUB's container.xml
 */
async function findOpfPath(zip: JSZip): Promise<string | null> {
  const containerFile = zip.file("META-INF/container.xml");
  if (!containerFile) return null;

  const xml = await containerFile.async("string");
  const parsed = xmlParser.parse(xml);

  // Navigate: container > rootfiles > rootfile > @_full-path
  const rootfiles = parsed?.container?.rootfiles?.rootfile;
  if (!rootfiles) return null;

  if (Array.isArray(rootfiles)) {
    return rootfiles[0]?.["@_full-path"] || null;
  }
  return rootfiles["@_full-path"] || null;
}

/**
 * Parse OPF metadata into a ComicInfo-compatible format
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseOpfMetadata(opf: any): ComicInfo {
  const metadata = (opf?.package?.metadata || opf?.["opf:package"]?.metadata || {}) as Record<string, unknown>;
  const info: ComicInfo = {};

  // dc:title -> Series
  const title = getMetaValue(metadata, "dc:title");
  if (title) info.Series = title;

  // dc:creator -> Writer
  const creator = getMetaValue(metadata, "dc:creator");
  if (creator) info.Writer = creator;

  // dc:description -> Summary
  const desc = getMetaValue(metadata, "dc:description");
  if (desc) info.Summary = desc;

  // dc:publisher -> Publisher
  const pub = getMetaValue(metadata, "dc:publisher");
  if (pub) info.Publisher = pub;

  // dc:subject -> Genre (join multiple)
  const subjects = getMetaValues(metadata, "dc:subject");
  if (subjects.length > 0) info.Genre = subjects.join(", ");

  // calibre:series -> Series name (overrides dc:title for series grouping)
  const metas = getMetaArray(metadata);
  for (const meta of metas) {
    const name = meta["@_name"] || "";
    const content = meta["@_content"] || meta["#text"] || "";
    if (name === "calibre:series" && content) {
      info.Series = content;
    }
    if (name === "calibre:rating" && content) {
      info.CommunityRating = content;
    }
    if (name === "calibre:user_metadata:status" && content) {
      info.Notes = `Status: ${content}`;
    }
  }

  return info;
}

/**
 * Get a single metadata value from the OPF metadata object
 */
function getMetaValue(metadata: Record<string, unknown>, key: string): string | null {
  const val = metadata[key];
  if (!val) return null;
  if (typeof val === "string") return val;
  if (typeof val === "object" && val !== null && "#text" in val) {
    return String((val as Record<string, unknown>)["#text"]);
  }
  if (Array.isArray(val)) {
    const first = val[0];
    if (typeof first === "string") return first;
    if (typeof first === "object" && first !== null && "#text" in first) {
      return String(first["#text"]);
    }
  }
  return null;
}

/**
 * Get multiple metadata values (for dc:subject which can repeat)
 */
function getMetaValues(metadata: Record<string, unknown>, key: string): string[] {
  const val = metadata[key];
  if (!val) return [];
  if (typeof val === "string") return [val];
  if (Array.isArray(val)) {
    return val.map((v) => {
      if (typeof v === "string") return v;
      if (typeof v === "object" && v !== null && "#text" in v) return String(v["#text"]);
      return String(v);
    });
  }
  if (typeof val === "object" && val !== null && "#text" in val) {
    return [String((val as Record<string, unknown>)["#text"])];
  }
  return [];
}

/**
 * Get all <meta> elements as an array
 */
function getMetaArray(metadata: Record<string, unknown>): Record<string, string>[] {
  const meta = metadata.meta;
  if (!meta) return [];
  if (Array.isArray(meta)) return meta as Record<string, string>[];
  return [meta as Record<string, string>];
}

/**
 * Extract metadata from an EPUB file, returned as ComicInfo for compatibility
 */
export async function extractEpubMetadata(
  epubPath: string
): Promise<ComicInfo | null> {
  try {
    const zip = await getEpubZip(epubPath);
    const opfPath = await findOpfPath(zip);
    if (!opfPath) return null;

    const opfFile = zip.file(opfPath);
    if (!opfFile) return null;

    const opfXml = await opfFile.async("string");
    const opf = xmlParser.parse(opfXml);
    return parseOpfMetadata(opf);
  } catch {
    return null;
  }
}

/**
 * Get the list of content chapters in an EPUB (XHTML files from the spine)
 */
export async function getEpubChapterList(epubPath: string): Promise<string[]> {
  try {
    const zip = await getEpubZip(epubPath);
    const opfPath = await findOpfPath(zip);
    if (!opfPath) return [];

    const opfFile = zip.file(opfPath);
    if (!opfFile) return [];

    const opfXml = await opfFile.async("string");
    const opf = xmlParser.parse(opfXml);

    const pkg = opf?.package || opf?.["opf:package"] || {};
    const manifest = pkg?.manifest?.item || [];
    const spine = pkg?.spine?.itemref || [];

    // Build manifest lookup: id -> { href, properties }
    const manifestMap = new Map<string, { href: string; properties: string }>();
    const items = Array.isArray(manifest) ? manifest : [manifest];
    const opfDir = opfPath.includes("/") ? opfPath.substring(0, opfPath.lastIndexOf("/") + 1) : "";

    for (const item of items) {
      const id = item?.["@_id"];
      const href = item?.["@_href"];
      const properties = (item?.["@_properties"] || "") as string;
      if (id && href) {
        // Resolve relative to OPF directory
        manifestMap.set(id, { href: opfDir + href, properties });
      }
    }

    // Follow spine order to get chapter files
    // Skip navigation documents (properties="nav") and non-linear items (linear="no")
    // These are TOC/cover pages that shouldn't appear as readable content
    const spineItems = Array.isArray(spine) ? spine : [spine];
    const chapters: string[] = [];
    for (const ref of spineItems) {
      const idref = ref?.["@_idref"];
      const linear = ref?.["@_linear"];
      // Skip items explicitly marked as non-linear (cover pages, TOC)
      if (linear === "no") continue;

      const entry = manifestMap.get(idref);
      if (!entry) continue;
      const { href, properties } = entry;

      // Skip EPUB3 navigation documents
      if (properties.includes("nav")) continue;

      if (zip.file(href)) {
        chapters.push(href);
      }
    }

    return chapters;
  } catch {
    return [];
  }
}

/**
 * Get the number of chapters/pages in an EPUB
 */
export async function getEpubPageCount(epubPath: string): Promise<number> {
  const chapters = await getEpubChapterList(epubPath);
  return chapters.length;
}

/**
 * Extract a specific chapter's HTML content from an EPUB
 */
export async function extractEpubChapter(
  epubPath: string,
  chapterFile: string
): Promise<{ html: string; mimeType: string } | null> {
  try {
    const zip = await getEpubZip(epubPath);
    const file = zip.file(chapterFile);
    if (!file) return null;

    let html = await file.async("string");

    // Inline any images referenced in the chapter
    html = await inlineImages(zip, html, chapterFile);

    return { html, mimeType: "text/html" };
  } catch {
    return null;
  }
}

/**
 * Replace image src references with inline base64 data URIs
 */
async function inlineImages(
  zip: JSZip,
  html: string,
  chapterPath: string
): Promise<string> {
  // Get the directory of the chapter file for resolving relative paths
  const chapterDir = chapterPath.includes("/")
    ? chapterPath.substring(0, chapterPath.lastIndexOf("/") + 1)
    : "";

  // Match src="..." attributes
  const srcRegex = /src=["']([^"']+)["']/g;
  let match;
  const replacements: [string, string][] = [];

  while ((match = srcRegex.exec(html)) !== null) {
    const src = match[1];
    if (src.startsWith("data:")) continue;

    // Resolve relative path
    let imgPath = src.startsWith("/") ? src.slice(1) : chapterDir + src;
    // Normalize ../ references
    imgPath = normalizePath(imgPath);

    const imgFile = zip.file(imgPath);
    if (imgFile) {
      const imgData = await imgFile.async("base64");
      const ext = imgPath.toLowerCase();
      let mime = "image/jpeg";
      if (ext.endsWith(".png")) mime = "image/png";
      else if (ext.endsWith(".webp")) mime = "image/webp";
      else if (ext.endsWith(".gif")) mime = "image/gif";
      else if (ext.endsWith(".svg")) mime = "image/svg+xml";

      replacements.push([match[0], `src="data:${mime};base64,${imgData}"`]);
    }
  }

  let result = html;
  for (const [original, replacement] of replacements) {
    result = result.replace(original, replacement);
  }
  return result;
}

/**
 * Extract cover image from EPUB
 */
export async function extractEpubCover(
  epubPath: string
): Promise<Buffer | null> {
  try {
    const zip = await getEpubZip(epubPath);
    const opfPath = await findOpfPath(zip);
    if (!opfPath) return null;

    const opfFile = zip.file(opfPath);
    if (!opfFile) return null;

    const opfXml = await opfFile.async("string");
    const opf = xmlParser.parse(opfXml);
    const pkg = opf?.package || opf?.["opf:package"] || {};
    const manifest = pkg?.manifest?.item || [];
    const items = Array.isArray(manifest) ? manifest : [manifest];
    const opfDir = opfPath.includes("/") ? opfPath.substring(0, opfPath.lastIndexOf("/") + 1) : "";

    // Method 1: Look for item with properties="cover-image"
    for (const item of items) {
      if (item?.["@_properties"]?.includes("cover-image")) {
        const href = opfDir + item["@_href"];
        const file = zip.file(href);
        if (file) return Buffer.from(await file.async("arraybuffer"));
      }
    }

    // Method 2: Look for meta cover reference
    const metadata = pkg?.metadata || {};
    const metas = getMetaArray(metadata);
    for (const meta of metas) {
      if (meta["@_name"] === "cover") {
        const coverId = meta["@_content"];
        for (const item of items) {
          if (item?.["@_id"] === coverId) {
            const href = opfDir + item["@_href"];
            const file = zip.file(href);
            if (file) return Buffer.from(await file.async("arraybuffer"));
          }
        }
      }
    }

    // Method 3: Look for file named "cover" in images
    for (const item of items) {
      const id = (item?.["@_id"] || "").toLowerCase();
      const href = (item?.["@_href"] || "").toLowerCase();
      if (id.includes("cover") || href.includes("cover")) {
        const mediaType = item?.["@_media-type"] || "";
        if (mediaType.startsWith("image/")) {
          const fullHref = opfDir + item["@_href"];
          const file = zip.file(fullHref);
          if (file) return Buffer.from(await file.async("arraybuffer"));
        }
      }
    }

    return null;
  } catch {
    return null;
  }
}

function normalizePath(path: string): string {
  const parts = path.split("/");
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === "..") {
      resolved.pop();
    } else if (part !== ".") {
      resolved.push(part);
    }
  }
  return resolved.join("/");
}
