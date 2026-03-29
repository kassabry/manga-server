"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useState, useEffect, useRef } from "react";
import { SearchBar } from "@/components/ui/SearchBar";

const CATEGORIES = [
  { label: "Manga", href: "/browse?type=Manga" },
  { label: "Manhwa", href: "/browse?type=Manhwa" },
  { label: "Manhua", href: "/browse?type=Manhua" },
  { label: "Light Novels", href: "/browse?type=LightNovels" },
];

export function Navbar() {
  const { data: session } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const [catOpen, setCatOpen] = useState(false);
  const pathname = usePathname();
  const catRef = useRef<HTMLDivElement>(null);

  // Close menus when route changes
  useEffect(() => {
    setMenuOpen(false);
    setCatOpen(false);
  }, [pathname]);

  // Close category dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (catRef.current && !catRef.current.contains(e.target as Node)) {
        setCatOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Hide navbar on reader page
  const isReaderPage = pathname.startsWith("/read/");
  if (isReaderPage) return null;

  return (
    <>
      {/* Top navbar (desktop) */}
      <nav className="sticky top-0 z-50 border-b border-border bg-bg-secondary/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
          <div className="flex items-center gap-5">
            <Link href="/" className="flex items-center gap-2 text-xl font-bold text-accent">
              <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 19.5C4 18.837 4.263 18.201 4.732 17.732C5.201 17.263 5.837 17 6.5 17H20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M6.5 2H20V22H6.5C5.837 22 5.201 21.737 4.732 21.268C4.263 20.799 4 20.163 4 19.5V4.5C4 3.837 4.263 3.201 4.732 2.732C5.201 2.263 5.837 2 6.5 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12 7L14 10H10L12 7Z" fill="currentColor" opacity="0.7"/>
                <circle cx="12" cy="13" r="1" fill="currentColor" opacity="0.5"/>
                <circle cx="9" cy="11" r="0.5" fill="currentColor" opacity="0.3"/>
                <circle cx="15" cy="11" r="0.5" fill="currentColor" opacity="0.3"/>
              </svg>
              ORVault
            </Link>
            <div className="hidden items-center gap-1 md:flex">
              <Link
                href="/browse"
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  pathname === "/browse"
                    ? "bg-accent/10 text-accent"
                    : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                }`}
              >
                Browse
              </Link>

              {/* Categories dropdown */}
              <div ref={catRef} className="relative">
                <button
                  onClick={() => setCatOpen(!catOpen)}
                  className={`flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm ${
                    catOpen
                      ? "bg-accent/10 text-accent"
                      : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                  }`}
                >
                  Categories
                  <svg
                    className={`h-3.5 w-3.5 transition-transform ${catOpen ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {catOpen && (
                  <div className="absolute left-0 top-full mt-1 w-44 rounded-lg border border-border bg-bg-secondary py-1 shadow-xl">
                    {CATEGORIES.map((cat) => (
                      <Link
                        key={cat.label}
                        href={cat.href}
                        className="block px-4 py-2 text-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                      >
                        {cat.label}
                      </Link>
                    ))}
                    <hr className="my-1 border-border" />
                    <Link
                      href="/browse"
                      className="block px-4 py-2 text-sm text-accent hover:bg-bg-hover"
                    >
                      View All
                    </Link>
                  </div>
                )}
              </div>

              {session?.user && (
                <>
                  <Link
                    href="/updates"
                    className={`rounded-lg px-3 py-1.5 text-sm ${
                      pathname === "/updates"
                        ? "bg-accent/10 text-accent"
                        : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                    }`}
                  >
                    Updates
                  </Link>
                  <Link
                    href="/my-list"
                    className={`rounded-lg px-3 py-1.5 text-sm ${
                      pathname === "/my-list"
                        ? "bg-accent/10 text-accent"
                        : "text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                    }`}
                  >
                    My List
                  </Link>
                </>
              )}
            </div>
          </div>

          <div className="hidden flex-1 justify-center px-8 md:flex">
            <SearchBar />
          </div>

          <div className="flex items-center gap-3">
            {session?.user ? (
              <div className="relative">
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm hover:bg-bg-hover"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">
                    {session.user.name?.[0]?.toUpperCase()}
                  </span>
                  <span className="hidden sm:inline">{session.user.name}</span>
                </button>
                {menuOpen && (
                  <div className="absolute right-0 top-full z-[100] mt-1 w-48 rounded-lg border border-border bg-bg-secondary py-1 shadow-xl">
                    <Link href="/my-list" className="block px-4 py-2 text-sm hover:bg-bg-hover">
                      My List
                    </Link>
                    <Link href="/updates" className="block px-4 py-2 text-sm hover:bg-bg-hover">
                      Updates
                    </Link>
                    <Link href="/settings" className="block px-4 py-2 text-sm hover:bg-bg-hover">
                      Settings
                    </Link>
                    {(session.user as { role: string }).role === "admin" && (
                      <>
                        <hr className="my-1 border-border" />
                        <Link href="/admin" className="block px-4 py-2 text-sm hover:bg-bg-hover">
                          Admin Panel
                        </Link>
                      </>
                    )}
                    <hr className="my-1 border-border" />
                    <button
                      onClick={() => signOut()}
                      className="block w-full px-4 py-2 text-left text-sm text-accent hover:bg-bg-hover"
                    >
                      Sign Out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <Link
                href="/login"
                className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
              >
                Sign In
              </Link>
            )}
          </div>
        </div>

        {/* Mobile search bar */}
        <div className="border-t border-border px-4 py-2 md:hidden">
          <SearchBar />
        </div>
      </nav>

    </>
  );
}

/**
 * Mobile bottom navigation bar.
 *
 * Rendered as a plain block element at the bottom of the app shell's flex
 * column (layout.tsx) rather than `position: fixed`.  This prevents the
 * classic iOS Safari jump where `fixed; bottom: 0` repaints whenever the
 * dynamic viewport height changes as the address bar shows / hides.
 */
export function BottomNav() {
  const { data: session } = useSession();
  const pathname = usePathname();

  if (pathname.startsWith("/read/")) return null;

  return (
    <nav className="border-t border-border bg-bg-secondary/95 backdrop-blur sm:hidden shrink-0">
      <div className="flex items-center justify-around py-1 pb-safe">
        <MobileNavItem href="/" icon="home" label="Home" active={pathname === "/"} />
        <MobileNavItem href="/browse" icon="browse" label="Browse" active={pathname.startsWith("/browse")} />
        {session?.user && (
          <>
            <MobileNavItem href="/updates" icon="updates" label="Updates" active={pathname === "/updates"} />
            <MobileNavItem href="/my-list" icon="list" label="My List" active={pathname === "/my-list"} />
          </>
        )}
        <MobileNavItem
          href={session?.user ? "/settings" : "/login"}
          icon="settings"
          label={session?.user ? "More" : "Sign In"}
          active={pathname === "/settings"}
        />
      </div>
    </nav>
  );
}

function MobileNavItem({
  href,
  icon,
  label,
  active,
}: {
  href: string;
  icon: string;
  label: string;
  active: boolean;
}) {
  const iconPaths: Record<string, string> = {
    home: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4",
    browse: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
    updates: "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
    list: "M4 6h16M4 10h16M4 14h16M4 18h16",
    settings: "M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4",
  };

  return (
    <Link
      href={href}
      className={`flex flex-col items-center gap-0.5 px-3 py-1.5 ${
        active ? "text-accent" : "text-text-secondary"
      }`}
    >
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={iconPaths[icon]} />
      </svg>
      <span className="text-[10px]">{label}</span>
    </Link>
  );
}
