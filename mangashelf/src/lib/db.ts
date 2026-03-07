import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient;
  prismaReady: boolean;
};

export const prisma = globalForPrisma.prisma || new PrismaClient();

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;

// Set SQLite PRAGMAs for better concurrency on first use
if (!globalForPrisma.prismaReady) {
  globalForPrisma.prismaReady = true;
  // busy_timeout: wait up to 10s when DB is locked instead of failing immediately
  // WAL mode is set in start.sh but busy_timeout must be set per-connection
  prisma.$executeRawUnsafe("PRAGMA busy_timeout = 10000").catch(() => {});
}
