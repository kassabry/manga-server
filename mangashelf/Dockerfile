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

RUN apk add --no-cache sqlite
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

# Startup script: ensure all tables exist then start server
RUN printf '#!/bin/sh\necho "Ensuring database schema..."\nif [ -f /app/prisma/full_schema.sql ] && [ -s /app/prisma/full_schema.sql ]; then\n  sqlite3 /app/data/mangashelf.db < /app/prisma/full_schema.sql 2>/dev/null || true\nfi\n# Ensure SeriesPath table exists (critical for scanner)\nsqlite3 /app/data/mangashelf.db "CREATE TABLE IF NOT EXISTS \\\"SeriesPath\\\" (\\\"id\\\" TEXT NOT NULL PRIMARY KEY, \\\"seriesId\\\" TEXT NOT NULL, \\\"path\\\" TEXT NOT NULL, \\\"source\\\" TEXT, CONSTRAINT \\\"SeriesPath_seriesId_fkey\\\" FOREIGN KEY (\\\"seriesId\\\") REFERENCES \\\"Series\\\" (\\\"id\\\") ON DELETE CASCADE ON UPDATE CASCADE); CREATE UNIQUE INDEX IF NOT EXISTS \\\"SeriesPath_path_key\\\" ON \\\"SeriesPath\\\"(\\\"path\\\"); CREATE INDEX IF NOT EXISTS \\\"SeriesPath_seriesId_idx\\\" ON \\\"SeriesPath\\\"(\\\"seriesId\\\");" 2>/dev/null || true\necho "Database ready"\nexec node server.js\n' > /app/start.sh && chmod +x /app/start.sh

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["/app/start.sh"]
