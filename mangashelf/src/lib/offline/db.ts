/**
 * IndexedDB index of what has been downloaded for offline reading.
 *
 * The bytes themselves live in the Cache Storage API (see manager.ts) — this
 * database only holds the metadata needed to render the Downloads screen and
 * to know which chapters are complete, plus a queue of reading progress that
 * couldn't be sent while offline.
 *
 * Hand-rolled rather than pulling in `idb`: the whole surface is five stores
 * worth of get/put/delete and the app has no other client-side DB.
 */

const DB_NAME = "orvault-offline";
const DB_VERSION = 1;

export const STORE_CHAPTERS = "chapters";
export const STORE_PROGRESS = "progressQueue";

export interface OfflineChapter {
  /** Chapter id — same id used by /api/chapters/:id and /read/:id */
  id: string;
  seriesId: string;
  seriesTitle: string;
  seriesSlug: string;
  coverPath: string | null;
  number: number;
  title: string | null;
  source: string | null;
  pageCount: number;
  isEpub: boolean;
  /** Total bytes of page data actually stored, for the storage breakdown */
  bytes: number;
  downloadedAt: number;
}

/** A progress update made while offline, replayed once the server is reachable. */
export interface QueuedProgress {
  chapterId: string;
  page: number;
  completed: boolean;
  pageOffset: number;
  queuedAt: number;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB unavailable"));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_CHAPTERS)) {
        const store = db.createObjectStore(STORE_CHAPTERS, { keyPath: "id" });
        store.createIndex("seriesId", "seriesId", { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_PROGRESS)) {
        // Keyed by chapterId so a later update for the same chapter replaces
        // the earlier one — only the final position is worth replaying.
        db.createObjectStore(STORE_PROGRESS, { keyPath: "chapterId" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  // A failed open (private mode, storage disabled) must not be cached as a
  // permanently rejected promise — let the next call try again.
  dbPromise.catch(() => {
    dbPromise = null;
  });

  return dbPromise;
}

function promisify<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(
  store: string,
  mode: IDBTransactionMode,
  fn: (s: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  const db = await openDb();
  return promisify(fn(db.transaction(store, mode).objectStore(store)));
}

export async function putChapter(record: OfflineChapter): Promise<void> {
  await tx(STORE_CHAPTERS, "readwrite", (s) => s.put(record));
}

export async function getChapter(id: string): Promise<OfflineChapter | undefined> {
  return tx(STORE_CHAPTERS, "readonly", (s) => s.get(id));
}

export async function deleteChapterRecord(id: string): Promise<void> {
  await tx(STORE_CHAPTERS, "readwrite", (s) => s.delete(id));
}

export async function getAllChapters(): Promise<OfflineChapter[]> {
  try {
    const all = await tx<OfflineChapter[]>(STORE_CHAPTERS, "readonly", (s) => s.getAll());
    return all ?? [];
  } catch {
    return [];
  }
}

export async function queueProgress(entry: QueuedProgress): Promise<void> {
  await tx(STORE_PROGRESS, "readwrite", (s) => s.put(entry));
}

export async function getQueuedProgress(): Promise<QueuedProgress[]> {
  try {
    const all = await tx<QueuedProgress[]>(STORE_PROGRESS, "readonly", (s) => s.getAll());
    return all ?? [];
  } catch {
    return [];
  }
}

export async function clearQueuedProgress(chapterId: string): Promise<void> {
  await tx(STORE_PROGRESS, "readwrite", (s) => s.delete(chapterId));
}
