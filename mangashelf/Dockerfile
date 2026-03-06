# Stage 1: Install dependencies
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
COPY prisma ./prisma/
RUN npm ci

# Stage 2: Build the app
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
ENV DATABASE_URL="file:../data/mangashelf.db"

RUN chmod +x node_modules/.bin/prisma node_modules/.bin/next 2>/dev/null; npx prisma generate
RUN npm run build

# Stage 3: Production runner
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV DATABASE_URL="file:../data/mangashelf.db"

RUN apk add --no-cache sqlite su-exec
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/node_modules/@prisma ./node_modules/@prisma

# Generate SQL migration script from Prisma schema at build time
COPY --from=builder /app/node_modules/prisma ./node_modules/prisma
RUN node node_modules/prisma/build/index.js migrate diff \
      --from-empty --to-schema-datamodel prisma/schema.prisma \
      --script > /app/prisma/full_schema.sql 2>/dev/null || true

# Create data directory for SQLite and startup script
RUN mkdir -p /app/data /app/public/covers && chown -R nextjs:nodejs /app/data /app/public/covers

# Startup script: fix permissions, run migrations as root, then drop to nextjs
RUN printf '#!/bin/sh\n\n# Fix permissions on mounted volumes (runs as root)\nchown -R nextjs:nodejs /app/data /app/public/covers 2>/dev/null || true\n\necho "Ensuring database schema..."\nif [ -f /app/prisma/full_schema.sql ] && [ -s /app/prisma/full_schema.sql ]; then\n  sqlite3 /app/data/mangashelf.db < /app/prisma/full_schema.sql 2>/dev/null || true\nfi\n\n# Ensure new tables exist (safe to run on existing DB)\nsqlite3 /app/data/mangashelf.db "CREATE TABLE IF NOT EXISTS \\\"SeriesPath\\\" (\\\"id\\\" TEXT NOT NULL PRIMARY KEY, \\\"seriesId\\\" TEXT NOT NULL, \\\"path\\\" TEXT NOT NULL, \\\"source\\\" TEXT, CONSTRAINT \\\"SeriesPath_seriesId_fkey\\\" FOREIGN KEY (\\\"seriesId\\\") REFERENCES \\\"Series\\\" (\\\"id\\\") ON DELETE CASCADE ON UPDATE CASCADE);" 2>/dev/null || true\nsqlite3 /app/data/mangashelf.db "CREATE UNIQUE INDEX IF NOT EXISTS \\\"SeriesPath_path_key\\\" ON \\\"SeriesPath\\\"(\\\"path\\\");" 2>/dev/null || true\nsqlite3 /app/data/mangashelf.db "CREATE INDEX IF NOT EXISTS \\\"SeriesPath_seriesId_idx\\\" ON \\\"SeriesPath\\\"(\\\"seriesId\\\");" 2>/dev/null || true\n\n# Ensure UserPreferences table exists\nsqlite3 /app/data/mangashelf.db "CREATE TABLE IF NOT EXISTS \\\"UserPreferences\\\" (\\\"id\\\" TEXT NOT NULL PRIMARY KEY, \\\"userId\\\" TEXT NOT NULL, \\\"theme\\\" TEXT NOT NULL DEFAULT '\\''midnight'\\'', \\\"customColors\\\" TEXT, \\\"readerLayout\\\" TEXT NOT NULL DEFAULT '\\''single'\\'', \\\"readerFit\\\" TEXT NOT NULL DEFAULT '\\''width'\\'', \\\"readerDirection\\\" TEXT NOT NULL DEFAULT '\\''ltr'\\'', \\\"readerBgColor\\\" TEXT NOT NULL DEFAULT '\\''black'\\'', \\\"readerBrightness\\\" INTEGER NOT NULL DEFAULT 100, \\\"autoHideToolbar\\\" BOOLEAN NOT NULL DEFAULT false, \\\"swipeEnabled\\\" BOOLEAN NOT NULL DEFAULT true, \\\"carouselColumns\\\" INTEGER NOT NULL DEFAULT 5, CONSTRAINT \\\"UserPreferences_userId_fkey\\\" FOREIGN KEY (\\\"userId\\\") REFERENCES \\\"User\\\" (\\\"id\\\") ON DELETE CASCADE ON UPDATE CASCADE);" 2>/dev/null || true\nsqlite3 /app/data/mangashelf.db "CREATE UNIQUE INDEX IF NOT EXISTS \\\"UserPreferences_userId_key\\\" ON \\\"UserPreferences\\\"(\\\"userId\\\");" 2>/dev/null || true\n\n# Ensure SiteConfig table exists\nsqlite3 /app/data/mangashelf.db "CREATE TABLE IF NOT EXISTS \\\"SiteConfig\\\" (\\\"key\\\" TEXT NOT NULL PRIMARY KEY, \\\"value\\\" TEXT NOT NULL);" 2>/dev/null || true\n\n# Add new columns to existing tables (safe if already exist)\nsqlite3 /app/data/mangashelf.db "ALTER TABLE \\\"Series\\\" ADD COLUMN \\\"lastChapterAt\\\" DATETIME;" 2>/dev/null || true\nsqlite3 /app/data/mangashelf.db "ALTER TABLE \\\"Chapter\\\" ADD COLUMN \\\"source\\\" TEXT;" 2>/dev/null || true\nsqlite3 /app/data/mangashelf.db "ALTER TABLE \\\"Chapter\\\" ADD COLUMN \\\"sourceUrl\\\" TEXT;" 2>/dev/null || true\n\n# Make DB writable by nextjs\nchown nextjs:nodejs /app/data/mangashelf.db 2>/dev/null || true\necho "Database ready"\n\n# Drop privileges and start server as nextjs user\nexec su-exec nextjs node server.js\n' > /app/start.sh && chmod +x /app/start.sh

# Note: no USER directive — start.sh runs as root for migrations, then drops to nextjs via su-exec

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["/app/start.sh"]
