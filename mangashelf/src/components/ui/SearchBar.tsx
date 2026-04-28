"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

interface SearchResult {
  id: string;
  title: string;
  slug: string;
  type: string;
  coverPath: string | null;
}

export function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      const res = await fetch(`/api/series?search=${encodeURIComponent(query)}&limit=6`);
      const data = await res.json();
      setResults(data.series || []);
      setOpen(true);
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function handleOutside(e: MouseEvent | TouchEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside, { passive: true });
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  return (
    <div ref={ref} className="relative w-full max-w-md">
      <input
        type="text"
        placeholder="Search manga..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && query) {
            router.push(`/browse?search=${encodeURIComponent(query)}`);
            setOpen(false);
          }
        }}
        className="w-full rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:border-accent focus:outline-none"
      />
      {open && results.length > 0 && (
        <div className="absolute top-full left-0 z-50 mt-1 w-full rounded-lg border border-border bg-bg-secondary shadow-xl">
          {results.map((item) => (
            <Link
              key={item.id}
              href={`/series/${item.id}`}
              onClick={() => {
                setOpen(false);
                setQuery("");
              }}
              className="flex items-center gap-3 px-4 py-2 hover:bg-bg-hover"
            >
              {item.coverPath ? (
                <img
                  src={item.coverPath}
                  alt=""
                  className="h-10 w-7 rounded object-cover"
                />
              ) : (
                <div className="h-10 w-7 rounded bg-bg-hover" />
              )}
              <div>
                <div className="text-sm font-medium">{item.title}</div>
                <div className="text-xs text-text-secondary">{item.type}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
