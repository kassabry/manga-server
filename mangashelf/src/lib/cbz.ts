import JSZip from "jszip";
import { readFile } from "fs/promises";
import { XMLParser } from "fast-xml-parser";
import type { ComicInfo } from "./types";

const xmlParser = new XMLParser({
  ignoreAttributes: false,
  trimValues: true,
});

export async function extractComicInfo(
  cbzPath: string
): Promise<ComicInfo | null> {
  try {
    const data = await readFile(cbzPath);
    const zip = await JSZip.loadAsync(data);
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
  const data = await readFile(cbzPath);
  const zip = await JSZip.loadAsync(data);

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

  return pages.sort((a, b) => {
    // Sort naturally: 001.jpg before 010.jpg, skip cover files to end or beginning
    const aIsCover = a.toLowerCase().includes("cover");
    const bIsCover = b.toLowerCase().includes("cover");
    if (aIsCover && !bIsCover) return -1;
    if (!aIsCover && bIsCover) return 1;
    return a.localeCompare(b, undefined, { numeric: true });
  });
}

export async function extractPage(
  cbzPath: string,
  pageName: string
): Promise<{ data: Buffer; mimeType: string } | null> {
  try {
    const fileData = await readFile(cbzPath);
    const zip = await JSZip.loadAsync(fileData);
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
    // Don't count cover images in page count
    return pages.filter((p) => !p.toLowerCase().includes("cover")).length;
  } catch {
    return 0;
  }
}
