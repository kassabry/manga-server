"use client";

import { useRef, useState, useEffect, ReactNode } from "react";

interface NavigationCarouselProps {
  children: ReactNode;
  columns?: number;
  className?: string;
}

export function NavigationCarousel({ children, columns = 5, className = "" }: NavigationCarouselProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  function checkScroll() {
    if (!scrollRef.current) return;
    const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
    setCanScrollLeft(scrollLeft > 4);
    setCanScrollRight(scrollLeft + clientWidth < scrollWidth - 4);
  }

  useEffect(() => {
    checkScroll();
    const el = scrollRef.current;
    if (el) {
      el.addEventListener("scroll", checkScroll, { passive: true });
      const observer = new ResizeObserver(checkScroll);
      observer.observe(el);
      return () => { el.removeEventListener("scroll", checkScroll); observer.disconnect(); };
    }
  }, [children]);

  function scroll(dir: "left" | "right") {
    if (!scrollRef.current) return;
    const amount = scrollRef.current.clientWidth * 0.8;
    scrollRef.current.scrollBy({ left: dir === "left" ? -amount : amount, behavior: "smooth" });
  }

  return (
    <div className={`group/carousel relative ${className}`}>
      {canScrollLeft && (
        <button
          onClick={() => scroll("left")}
          className="absolute -left-2 top-1/2 z-10 -translate-y-1/2 rounded-full border border-border bg-bg-secondary/95 p-1.5 shadow-lg backdrop-blur transition hover:bg-bg-hover sm:-left-4"
          aria-label="Scroll left"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      )}

      {canScrollRight && (
        <button
          onClick={() => scroll("right")}
          className="absolute -right-2 top-1/2 z-10 -translate-y-1/2 rounded-full border border-border bg-bg-secondary/95 p-1.5 shadow-lg backdrop-blur transition hover:bg-bg-hover sm:-right-4"
          aria-label="Scroll right"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      )}

      <div
        ref={scrollRef}
        className="overflow-x-auto"
        style={{
          display: "grid",
          gridAutoFlow: "column",
          gridAutoColumns: `max(140px, calc((100% - ${(columns - 1) * 16}px) / ${columns}))`,
          gap: "16px",
          scrollbarWidth: "none",
          scrollSnapType: "x mandatory",
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function CarouselItem({ children }: { children: ReactNode }) {
  return (
    <div className="snap-start min-w-0">
      {children}
    </div>
  );
}
