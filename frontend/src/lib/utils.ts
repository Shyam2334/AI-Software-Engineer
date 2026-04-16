import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { formatDistanceToNow } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function relativeTime(dateString: string): string {
  try {
    return formatDistanceToNow(new Date(dateString), { addSuffix: true });
  } catch {
    return dateString;
  }
}

export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: "text-yellow-500",
    planning: "text-blue-400",
    researching: "text-cyan-400",
    coding: "text-purple-400",
    testing: "text-orange-400",
    revising: "text-amber-500",
    documenting: "text-teal-400",
    awaiting_approval: "text-yellow-300",
    creating_pr: "text-indigo-400",
    completed: "text-green-500",
    failed: "text-red-500",
    cancelled: "text-gray-500",
  };
  return colors[status] || "text-gray-400";
}

export function statusBadgeClasses(status: string): string {
  const base = "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium";
  const variants: Record<string, string> = {
    pending: `${base} bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400`,
    planning: `${base} bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400`,
    researching: `${base} bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-400`,
    coding: `${base} bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400`,
    testing: `${base} bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400`,
    revising: `${base} bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400`,
    documenting: `${base} bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-400`,
    awaiting_approval: `${base} bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300`,
    creating_pr: `${base} bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400`,
    completed: `${base} bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400`,
    failed: `${base} bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400`,
    cancelled: `${base} bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400`,
  };
  return variants[status] || `${base} bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400`;
}

export function logLevelColor(level: string): string {
  const colors: Record<string, string> = {
    debug: "text-gray-400",
    info: "text-blue-400",
    warning: "text-yellow-400",
    error: "text-red-400",
    success: "text-green-400",
  };
  return colors[level] || "text-gray-400";
}
