/**
 * Reading progress that survives being offline.
 *
 * The reader saves your position every couple of seconds and again on unload.
 * With no network those writes used to be dropped on the floor, so a chapter
 * read on a plane came back on the ground still marked unread. Failed writes
 * are queued in IndexedDB (last position per chapter wins) and replayed as
 * soon as the server is reachable again.
 */

import { clearQueuedProgress, getQueuedProgress, queueProgress } from "./db";

/**
 * next-auth reports "no session" whenever /api/auth/session can't be reached,
 * which offline is always. This flag records that the device has a signed-in
 * user so the reader keeps saving progress on a plane instead of silently
 * discarding it. A queued write that turns out to be unauthorised is rejected
 * by the server on replay and dropped, so a stale flag is harmless.
 */
const SIGNED_IN_KEY = "orvault-signed-in";

export function rememberSignedIn(signedIn: boolean): void {
  try {
    if (signedIn) localStorage.setItem(SIGNED_IN_KEY, "1");
    else localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    /* storage disabled — progress just won't survive a cold offline start */
  }
}

export function wasSignedIn(): boolean {
  try {
    return localStorage.getItem(SIGNED_IN_KEY) === "1";
  } catch {
    return false;
  }
}

export interface ProgressUpdate {
  chapterId: string;
  page: number;
  completed: boolean;
  pageOffset: number;
}

type PutResult = "sent" | "rejected" | "unreachable";

async function putProgress(update: ProgressUpdate): Promise<PutResult> {
  try {
    const res = await fetch("/api/user/progress", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
      credentials: "same-origin",
    });
    if (res.ok) return "sent";
    // A 4xx won't get better by retrying (signed out, chapter deleted) — say so
    // rather than letting one row wedge the queue forever. Anything else is
    // treated as a blip worth retrying.
    return res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429
      ? "rejected"
      : "unreachable";
  } catch {
    return "unreachable";
  }
}

/** Save progress, falling back to the offline queue when the write fails. */
export async function saveProgressResilient(update: ProgressUpdate): Promise<void> {
  if (navigator.onLine && (await putProgress(update)) !== "unreachable") return;
  await queueProgress({ ...update, queuedAt: Date.now() }).catch(() => {});
}

/**
 * Synchronous-ish save for unload handlers. sendBeacon is the only thing that
 * survives the page going away, but it returns false when it can't queue the
 * request (offline, or payload too large) — in that case fall through to the
 * IndexedDB queue, whose write will usually still land before teardown.
 */
export function saveProgressOnUnload(update: ProgressUpdate): void {
  const body = JSON.stringify(update);
  const sent =
    navigator.onLine &&
    navigator.sendBeacon(
      "/api/user/progress",
      new Blob([body], { type: "application/json" })
    );
  if (!sent) void queueProgress({ ...update, queuedAt: Date.now() }).catch(() => {});
}

/** Replay everything queued while offline. Returns how many writes landed. */
export async function flushProgressQueue(): Promise<number> {
  if (!navigator.onLine) return 0;
  const queued = await getQueuedProgress();
  let sent = 0;
  for (const entry of queued) {
    const { chapterId, page, completed, pageOffset } = entry;
    const result = await putProgress({ chapterId, page, completed, pageOffset });
    if (result === "unreachable") {
      // Still no server — stop rather than hammering it once per queued row.
      break;
    }
    await clearQueuedProgress(chapterId).catch(() => {});
    if (result === "sent") sent++;
  }
  return sent;
}
