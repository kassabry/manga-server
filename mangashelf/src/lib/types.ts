import "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      name: string;
      email?: string | null;
      role: string;
    };
  }
}

export interface ComicInfo {
  Series?: string;
  Number?: string;
  Title?: string;
  Genre?: string;
  Tags?: string;
  Summary?: string;
  CommunityRating?: string;
  Writer?: string;
  Penciller?: string;
  Publisher?: string;
  Web?: string;
  Manga?: string;
  LanguageISO?: string;
  Format?: string;
  AgeRating?: string;
  Notes?: string;
  Count?: string;
}

export type ListStatus =
  | "reading"
  | "plan_to_read"
  | "completed"
  | "dropped"
  | "on_hold";

export const LIST_STATUS_LABELS: Record<ListStatus, string> = {
  reading: "Reading",
  plan_to_read: "Plan to Read",
  completed: "Completed",
  dropped: "Dropped",
  on_hold: "On Hold",
};
