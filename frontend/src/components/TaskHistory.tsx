import { useEffect, useState, useCallback } from "react";
import { relativeTime } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  RefreshCw,
  GitBranch,
  GitPullRequest,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  CircleDot,
  MessageSquare,
  Inbox,
} from "lucide-react";
import { Button } from "@/components/ui/button";

interface TaskItem {
  id: number;
  title: string;
  status: string;
  progress: number;
  branch_name: string | null;
  pr_url: string | null;
  pr_number: number | null;
  repo_name: string | null;
  repo_url: string | null;
  created_at: string;
  updated_at: string;
}

interface TaskHistoryProps {
  onSelectTask?: (taskId: number) => void;
  selectedTaskId?: number;
}

const STATUS_CONFIG: Record<string, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: "text-yellow-500", label: "Pending" },
  planning: { icon: CircleDot, color: "text-blue-400", label: "Planning" },
  researching: { icon: CircleDot, color: "text-cyan-400", label: "Researching" },
  coding: { icon: Loader2, color: "text-purple-400", label: "Coding" },
  testing: { icon: Loader2, color: "text-orange-400", label: "Testing" },
  revising: { icon: Loader2, color: "text-amber-400", label: "Revising" },
  documenting: { icon: CircleDot, color: "text-teal-400", label: "Documenting" },
  awaiting_approval: { icon: Clock, color: "text-yellow-300", label: "Awaiting Approval" },
  creating_pr: { icon: Loader2, color: "text-indigo-400", label: "Creating PR" },
  completed: { icon: CheckCircle2, color: "text-green-500", label: "Completed" },
  failed: { icon: XCircle, color: "text-red-500", label: "Failed" },
  cancelled: { icon: XCircle, color: "text-gray-500", label: "Cancelled" },
};

function StatusIcon({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const Icon = config.icon;
  const isAnimated = ["coding", "testing", "revising", "creating_pr"].includes(status);
  return <Icon className={`h-4 w-4 ${config.color} ${isAnimated ? "animate-spin" : ""} shrink-0`} />;
}

export function TaskHistory({ onSelectTask, selectedTaskId }: TaskHistoryProps) {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/tasks/?limit=50");
      if (response.ok) {
        const data = await response.json();
        setTasks(data);
      }
    } catch {
      // Silent fail - will retry
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 10000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  // Group tasks: active (in-progress) at top, then the rest
  const activeTasks = tasks.filter((t) =>
    ["coding", "testing", "revising", "planning", "researching", "documenting", "creating_pr", "awaiting_approval"].includes(t.status)
  );
  const otherTasks = tasks.filter((t) => !activeTasks.includes(t));

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Sessions</h2>
          <span className="text-[10px] text-muted-foreground bg-muted rounded-full px-1.5 py-0.5 font-medium">
            {tasks.length}
          </span>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={fetchTasks} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="px-2 py-2">
          {/* Empty state */}
          {tasks.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
              <Inbox className="h-10 w-10 opacity-40" />
              <p className="text-sm">No sessions yet</p>
              <p className="text-xs opacity-70">Start a new task to begin</p>
            </div>
          )}

          {/* Active tasks section */}
          {activeTasks.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold px-2 mb-1.5">
                Active
              </p>
              <div className="space-y-0.5">
                {activeTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    selected={selectedTaskId === task.id}
                    onSelect={() => onSelectTask?.(task.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Recent tasks section */}
          {otherTasks.length > 0 && (
            <div>
              {activeTasks.length > 0 && (
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold px-2 mb-1.5">
                  Recent
                </p>
              )}
              <div className="space-y-0.5">
                {otherTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    selected={selectedTaskId === task.id}
                    onSelect={() => onSelectTask?.(task.id)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function TaskCard({
  task,
  selected,
  onSelect,
}: {
  task: TaskItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
  const isActive = ["coding", "testing", "revising", "planning", "researching", "documenting", "creating_pr", "awaiting_approval"].includes(task.status);

  return (
    <button
      onClick={onSelect}
      className={`group w-full text-left px-2.5 py-2 rounded-lg transition-all duration-150 ${
        selected
          ? "bg-accent ring-1 ring-primary/20"
          : "hover:bg-accent/60"
      }`}
    >
      <div className="flex items-start gap-2.5">
        {/* Status icon */}
        <div className="mt-0.5">
          <StatusIcon status={task.status} />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate leading-tight">{task.title}</p>

          <div className="flex items-center gap-2 mt-1">
            {task.repo_name && (
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground font-mono bg-muted/50 rounded px-1.5 py-0.5 truncate max-w-[140px]">
                <GitBranch className="h-2.5 w-2.5 shrink-0" />
                {task.repo_name.split("/").pop()}
              </span>
            )}
            <span className={`text-[10px] font-medium ${config.color}`}>
              {config.label}
            </span>
          </div>

          {/* Progress bar for active tasks */}
          {isActive && task.progress > 0 && task.progress < 100 && (
            <div className="mt-1.5 h-1 bg-secondary/60 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  task.status === "testing" ? "bg-orange-400" :
                  task.status === "coding" ? "bg-purple-400" :
                  "bg-primary"
                }`}
                style={{ width: `${task.progress}%` }}
              />
            </div>
          )}

          {/* Footer: time + PR link */}
          <div className="flex items-center justify-between mt-1">
            <span className="text-[10px] text-muted-foreground/70">
              {relativeTime(task.updated_at)}
            </span>
            {task.pr_url && (
              <a
                href={task.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-[10px] text-primary hover:underline inline-flex items-center gap-0.5"
              >
                <GitPullRequest className="h-2.5 w-2.5" />
                PR #{task.pr_number}
              </a>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}
