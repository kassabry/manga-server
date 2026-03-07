-- Full schema initialization for MangaShelf (SQLite)
-- Safe to run on an existing database — all statements use IF NOT EXISTS

CREATE TABLE IF NOT EXISTS "User" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "username" TEXT NOT NULL,
    "email" TEXT,
    "passwordHash" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'user',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS "User_username_key" ON "User"("username");
CREATE UNIQUE INDEX IF NOT EXISTS "User_email_key" ON "User"("email");

CREATE TABLE IF NOT EXISTS "UserPreferences" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "theme" TEXT NOT NULL DEFAULT 'midnight',
    "customColors" TEXT,
    "readerLayout" TEXT NOT NULL DEFAULT 'single',
    "readerFit" TEXT NOT NULL DEFAULT 'width',
    "readerDirection" TEXT NOT NULL DEFAULT 'ltr',
    "readerBgColor" TEXT NOT NULL DEFAULT 'black',
    "readerBrightness" INTEGER NOT NULL DEFAULT 100,
    "autoHideToolbar" BOOLEAN NOT NULL DEFAULT false,
    "swipeEnabled" BOOLEAN NOT NULL DEFAULT true,
    "carouselColumns" INTEGER NOT NULL DEFAULT 5,
    CONSTRAINT "UserPreferences_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "UserPreferences_userId_key" ON "UserPreferences"("userId");

CREATE TABLE IF NOT EXISTS "SiteConfig" (
    "key" TEXT NOT NULL PRIMARY KEY,
    "value" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS "InviteCode" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "code" TEXT NOT NULL,
    "createdBy" TEXT NOT NULL,
    "usedBy" TEXT,
    "usedAt" DATETIME,
    "expiresAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS "InviteCode_code_key" ON "InviteCode"("code");

CREATE TABLE IF NOT EXISTS "Series" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "title" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "description" TEXT,
    "author" TEXT,
    "artist" TEXT,
    "status" TEXT,
    "type" TEXT NOT NULL,
    "genres" TEXT,
    "rating" REAL,
    "coverPath" TEXT,
    "libraryPath" TEXT NOT NULL,
    "publisher" TEXT,
    "ageRating" TEXT,
    "chapterCount" INTEGER NOT NULL DEFAULT 0,
    "lastChapterAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS "Series_slug_key" ON "Series"("slug");
CREATE UNIQUE INDEX IF NOT EXISTS "Series_libraryPath_key" ON "Series"("libraryPath");

CREATE TABLE IF NOT EXISTS "SeriesPath" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "seriesId" TEXT NOT NULL,
    "path" TEXT NOT NULL,
    "source" TEXT,
    CONSTRAINT "SeriesPath_seriesId_fkey" FOREIGN KEY ("seriesId") REFERENCES "Series" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "SeriesPath_path_key" ON "SeriesPath"("path");
CREATE INDEX IF NOT EXISTS "SeriesPath_seriesId_idx" ON "SeriesPath"("seriesId");

CREATE TABLE IF NOT EXISTS "Chapter" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "seriesId" TEXT NOT NULL,
    "number" REAL NOT NULL,
    "title" TEXT,
    "pageCount" INTEGER NOT NULL DEFAULT 0,
    "filePath" TEXT NOT NULL,
    "fileSize" INTEGER NOT NULL DEFAULT 0,
    "source" TEXT,
    "sourceUrl" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Chapter_seriesId_fkey" FOREIGN KEY ("seriesId") REFERENCES "Series" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "Chapter_filePath_key" ON "Chapter"("filePath");
CREATE INDEX IF NOT EXISTS "Chapter_seriesId_number_idx" ON "Chapter"("seriesId", "number");

CREATE TABLE IF NOT EXISTS "Follow" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "seriesId" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Follow_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "Follow_seriesId_fkey" FOREIGN KEY ("seriesId") REFERENCES "Series" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "Follow_userId_seriesId_key" ON "Follow"("userId", "seriesId");

CREATE TABLE IF NOT EXISTS "ListEntry" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "seriesId" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "rating" INTEGER,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "ListEntry_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "ListEntry_seriesId_fkey" FOREIGN KEY ("seriesId") REFERENCES "Series" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "ListEntry_userId_seriesId_key" ON "ListEntry"("userId", "seriesId");

CREATE TABLE IF NOT EXISTS "ReadProgress" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "chapterId" TEXT NOT NULL,
    "page" INTEGER NOT NULL DEFAULT 0,
    "completed" BOOLEAN NOT NULL DEFAULT false,
    "readAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ReadProgress_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "ReadProgress_chapterId_fkey" FOREIGN KEY ("chapterId") REFERENCES "Chapter" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "ReadProgress_userId_chapterId_key" ON "ReadProgress"("userId", "chapterId");
