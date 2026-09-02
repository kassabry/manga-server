"use client";

/**
 * Fallback served by the service worker when a page is requested with no
 * network and nothing cached for it. Deliberately dependency-free.
 */

import Link from "next/link";

export default function OfflinePage() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <svg
        className="mx-auto h-12 w-12 text-text-secondary/50"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.3}
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 3l18 18" />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M8.5 16.5a5 5 0 017 0M5 13a9 9 0 013.5-2.2M19 13a9 9 0 00-6.9-2.95M2 8.8A14 14 0 0110.5 5.1M21.9 8.8a14 14 0 00-5.4-3.3M12 20h.01"
        />
      </svg>
      <h1 className="mt-4 text-xl font-bold">You&apos;re offline</h1>
      <p className="mt-2 text-sm text-text-secondary">
        This page needs the server. Chapters you downloaded are still available.
      </p>
      <Link
        href="/downloads"
        className="mt-6 inline-block rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
      >
        Go to Downloads
      </Link>
    </div>
  );
}
