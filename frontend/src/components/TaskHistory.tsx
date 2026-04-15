import { useEffect, useState, useCallback } from "react";
import { relativeTime, statusBadgeClasses } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ExternalLink, RefreshCw, GitBranch, GitPullRequest } from "lucide-react";
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
    const interval = setInterval(fetchTasks, 10000); // Refresh every 10s
    return () => clearInterval(interval);
  }, [fetchTasks]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-lg font-semibold">Task History</h2>
        <Button variant="ghost" size="icon" onClick={fetchTasks} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {tasks.length === 0 && !loading && (
            <p className="text-sm text-center text-muted-foreground py-8">
              No tasks yet. Create one to get started.
            </p>
          )}

          {tasks.map((task) => (
            <button
              key={task.id}
              onClick={() => onSelectTask?.(task.id)}
              className={`w-full text-left p-3 rounded-lg transition-colors hover:bg-accent ${
                selectedTaskId === task.id ? "bg-accent" : ""
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{task.title}</p>
                  {task.repo_name && (
                    <p className="text-[10px] text-muted-foreground font-mono mt-0.5 truncate">
                      {task.repo_name}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground mt-1">
                    {relativeTime(task.updated_at)}
                  </p>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className={statusBadgeClasses(task.status)}>
                    {task.status.replace("_", " ")}
                  </span>

                  {task.branch_name && (
                    <span className="text-[10px] text-muted-foreground inline-flex items-center gap-0.5">
                      <GitBranch className="h-2.5 w-2.5" />
                      {task.branch_name.replace("ai/", "")}
                    </span>
                  )}

                  {task.pr_url && (
                    <a
                      href={task.pr_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                    >
                      <GitPullRequest className="h-3 w-3" />
                      PR #{task.pr_number}
                    </a>
                  )}
                </div>
              </div>

              {task.progress > 0 && task.progress < 100 && (
                <div className="mt-2 h-1.5 bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-300"
                    style={{ width: `${task.progress}%` }}
                  />
                </div>
              )}
            </button>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
