import { useEffect, useRef, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import {
  Search,
  FileCode,
  BrainCircuit,
  ClipboardList,
  Code2,
  TestTube2,
  RefreshCw,
  FileText,
  GitPullRequest,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ShieldAlert,
  Clock,
  Circle,
} from "lucide-react";
import type { WSMessage } from "@/hooks/useAgentWebSocket";
import { cn } from "@/lib/utils";

// ── Phase metadata ───────────────────────────────────────────────────

interface PhaseInfo {
  key: string;
  label: string;
  icon: React.ElementType;
}

const PHASES: PhaseInfo[] = [
  { key: "setup", label: "Setup", icon: ClipboardList },
  { key: "research", label: "Research", icon: Search },
  { key: "analyze", label: "Analyze", icon: BrainCircuit },
  { key: "plan", label: "Plan", icon: ClipboardList },
  { key: "code", label: "Code", icon: Code2 },
  { key: "test", label: "Test", icon: TestTube2 },
  { key: "revise", label: "Revise", icon: RefreshCw },
  { key: "document", label: "Document", icon: FileText },
  { key: "approve_pr", label: "Approve PR", icon: ShieldAlert },
  { key: "create_pr", label: "Pull Request", icon: GitPullRequest },
  { key: "complete", label: "Complete", icon: CheckCircle2 },
  { key: "failed", label: "Failed", icon: XCircle },
];

function getPhaseInfo(key: string): PhaseInfo | undefined {
  return PHASES.find((p) => p.key === key);
}

// ── Types ────────────────────────────────────────────────────────────

interface LogEntry {
  message: string;
  level: string;
  time: string;
}

interface PhaseGroup {
  phase: string;
  logs: LogEntry[];
  status: "done" | "active" | "upcoming" | "failed";
}

interface ApprovalInlineProps {
  approval: WSMessage | null;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

interface ExecutionTimelineProps {
  logs: WSMessage[];
  currentStatus: string;
  progress: number;
  approval: WSMessage | null;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

// ── Extract key highlights from logs ─────────────────────────────────

function extractHighlights(logs: LogEntry[]): string[] {
  const highlights: string[] = [];

  for (const log of logs) {
    const msg = log.message;

    // Research phase
    if (msg.startsWith("Reading (")) {
      const match = msg.match(/Reading \(\d+\/\d+\): (.+)/);
      if (match) highlights.push(`Read: ${match[1]}`);
    } else if (/Gathered \d+ resource/.test(msg)) {
      highlights.push(msg);
    } else if (/Including uploaded document/.test(msg)) {
      highlights.push("Included uploaded document as context");
    } else if (/No search results found/.test(msg)) {
      highlights.push("Proceeding with built-in knowledge");
    }
    // Analyze phase
    else if (/Analysis complete/.test(msg)) {
      highlights.push(msg);
    } else if (/Image analysis complete/.test(msg)) {
      highlights.push("Analyzed attached images for visual context");
    } else if (/Found \d+ files in project/.test(msg)) {
      highlights.push(msg);
    } else if (/Scanning project files/.test(msg)) {
      highlights.push("Scanned project structure");
    }
    // Plan phase
    else if (/Implementation plan ready/.test(msg)) {
      highlights.push("Implementation plan ready for review");
    } else if (/Plan approved/.test(msg)) {
      highlights.push("Plan approved — proceeding to code");
    } else if (/Plan rejected/.test(msg)) {
      highlights.push("Plan rejected by reviewer");
    }
    // Code phase
    else if (/Loaded \d+ existing file/.test(msg)) {
      highlights.push(msg.replace(/\s*as context.*/, " for context"));
    } else if (/Generated \d+ file/.test(msg)) {
      highlights.push(msg);
    } else if (/Wrote: /.test(msg)) {
      const match = msg.match(/Wrote: (.+?)(?:\s+\(|$)/);
      if (match) highlights.push(`Wrote ${match[1]}`);
    } else if (/All files written/.test(msg)) {
      highlights.push("All files written to project");
    } else if (/Regenerating code/.test(msg)) {
      highlights.push(msg.split("—")[0].trim());
    }
    // Test phase
    else if (/All tests passed/.test(msg)) {
      highlights.push("All tests passed");
    } else if (/\d+ test.*failed/i.test(msg)) {
      highlights.push(msg.split(".")[0]);
    } else if (/Executing:/.test(msg)) {
      highlights.push(msg);
    }
    // Document phase
    else if (/Documentation and PR description ready/.test(msg)) {
      highlights.push("Documentation and PR description ready");
    }
    // PR phase
    else if (/Committed:/.test(msg)) {
      highlights.push(msg);
    } else if (/Branch pushed/.test(msg)) {
      highlights.push("Branch pushed to remote");
    } else if (/Pull request created/i.test(msg) || /PR #\d+/.test(msg)) {
      highlights.push(msg);
    } else if (/Staging and committing/.test(msg)) {
      highlights.push("Staged and committed generated files");
    }
    // Setup phase
    else if (/Pulled latest code/.test(msg)) {
      highlights.push(msg.split("and")[0].trim() || msg);
    } else if (/created working branch/.test(msg)) {
      const match = msg.match(/branch: (.+)/);
      highlights.push(match ? `Created branch: ${match[1]}` : "Created working branch");
    }
    // Complete / fail
    else if (/Task completed successfully/.test(msg)) {
      highlights.push("Task completed successfully");
    }
    // Errors (always show)
    else if (log.level === "error") {
      highlights.push(msg.length > 120 ? msg.slice(0, 117) + "..." : msg);
    }
  }

  return highlights;
}

// ── Inline Approval Card ─────────────────────────────────────────────

function InlineApproval({ approval, onApprove, onReject }: ApprovalInlineProps) {
  if (!approval || !approval.approval_id) return null;

  const details = approval.details || {};
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="ml-10 my-3 rounded-lg border-2 border-yellow-500/40 bg-yellow-500/5 p-4 animate-fade-in-up">
      <div className="flex items-start gap-3">
        <ShieldAlert className="h-5 w-5 text-yellow-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-yellow-300">Approval Required</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400">
              {(approval.approval_type || "").replace("_", " ")}
            </span>
          </div>
          <p className="text-sm text-foreground">{approval.title}</p>
          {approval.description && (
            <p className="text-xs text-muted-foreground">{approval.description}</p>
          )}

          {(details.plan || details.pr_description || details.files_changed) && (
            <>
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-xs text-primary hover:underline"
              >
                {expanded ? "Hide details" : "Show details"}
              </button>
              {expanded && (
                <div className="mt-2 space-y-2 text-xs">
                  {details.plan && (
                    <div className="max-h-[300px] overflow-y-auto rounded border border-border bg-background/50 p-3">
                      <pre className="whitespace-pre-wrap font-mono text-muted-foreground">
                        {String(details.plan)}
                      </pre>
                    </div>
                  )}
                  {details.pr_description && (
                    <div className="max-h-[200px] overflow-y-auto rounded border border-border bg-background/50 p-3">
                      <pre className="whitespace-pre-wrap font-mono text-muted-foreground">
                        {String(details.pr_description)}
                      </pre>
                    </div>
                  )}
                  {details.files_changed && Array.isArray(details.files_changed) && (
                    <div>
                      <span className="text-muted-foreground font-medium">
                        Files ({(details.files_changed as string[]).length}):
                      </span>
                      <ul className="mt-1 space-y-0.5 list-none">
                        {(details.files_changed as string[]).map((f, i) => (
                          <li key={i} className="font-mono text-muted-foreground flex items-center gap-1">
                            <FileCode className="h-3 w-3 shrink-0" />
                            {f}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              onClick={() => onApprove(approval.approval_id!)}
              className="h-8 bg-green-600 hover:bg-green-700 text-white"
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onReject(approval.approval_id!)}
              className="h-8 border-red-500/50 text-red-400 hover:bg-red-500/10"
            >
              <XCircle className="h-3.5 w-3.5 mr-1" />
              Reject
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Phase Step (todo-style card) ─────────────────────────────────────

function PhaseStep({
  group,
  isLast,
}: {
  group: PhaseGroup;
  isLast: boolean;
}) {
  const [showLogs, setShowLogs] = useState(false);
  const info = getPhaseInfo(group.phase);
  const highlights = useMemo(() => extractHighlights(group.logs), [group.logs]);

  // Latest message for active phase
  const latestLog = group.status === "active" && group.logs.length > 0
    ? group.logs[group.logs.length - 1].message
    : null;

  const s = {
    done: {
      icon: "text-green-400",
      ring: "ring-green-500/30 bg-green-500/10",
      line: "bg-green-500/40",
      label: "text-foreground",
    },
    active: {
      icon: "text-primary",
      ring: "ring-primary/30 bg-primary/10",
      line: "bg-border",
      label: "text-foreground",
    },
    upcoming: {
      icon: "text-muted-foreground/40",
      ring: "ring-border bg-muted/20",
      line: "bg-border/50",
      label: "text-muted-foreground",
    },
    failed: {
      icon: "text-red-400",
      ring: "ring-red-500/30 bg-red-500/10",
      line: "bg-red-500/40",
      label: "text-red-400",
    },
  }[group.status];

  return (
    <div className="flex gap-3">
      {/* Vertical timeline connector */}
      <div className="flex flex-col items-center">
        <div className={cn("h-7 w-7 rounded-full flex items-center justify-center ring-2 shrink-0", s.ring)}>
          {group.status === "active" ? (
            <Loader2 className={cn("h-3.5 w-3.5 animate-spin", s.icon)} />
          ) : group.status === "done" ? (
            <CheckCircle2 className={cn("h-3.5 w-3.5", s.icon)} />
          ) : group.status === "failed" ? (
            <XCircle className={cn("h-3.5 w-3.5", s.icon)} />
          ) : (
            <Circle className={cn("h-3 w-3", s.icon)} />
          )}
        </div>
        {!isLast && <div className={cn("w-px flex-1 min-h-[16px]", s.line)} />}
      </div>

      {/* Content */}
      <div className={cn("flex-1 min-w-0 pb-5", isLast && "pb-1")}>
        {/* Phase title row */}
        <div className="flex items-center gap-2 h-7">
          <span className={cn("text-sm font-medium", s.label)}>
            {info?.label || group.phase}
          </span>
          {group.status === "done" && (
            <span className="text-[10px] text-green-400/70 font-medium">Done</span>
          )}
          {group.status === "active" && (
            <span className="text-[10px] text-primary/70 font-medium animate-pulse">In Progress</span>
          )}
          {group.status === "failed" && (
            <span className="text-[10px] text-red-400/70 font-medium">Failed</span>
          )}
        </div>

        {/* Active: show current activity */}
        {group.status === "active" && latestLog && (
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed animate-fade-in-up">
            {latestLog}
          </p>
        )}

        {/* Completed: show highlight summary */}
        {group.status === "done" && highlights.length > 0 && (
          <div className="mt-1.5 space-y-1">
            {highlights.slice(0, 4).map((h, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <CheckCircle2 className="h-3 w-3 text-green-400/60 mt-0.5 shrink-0" />
                <span className="text-xs text-muted-foreground leading-relaxed">{h}</span>
              </div>
            ))}
            {highlights.length > 4 && (
              <button
                onClick={() => setShowLogs(!showLogs)}
                className="text-[11px] text-primary/70 hover:text-primary ml-[18px] flex items-center gap-0.5"
              >
                +{highlights.length - 4} more
                <ChevronDown className={cn("h-3 w-3 transition-transform", showLogs && "rotate-180")} />
              </button>
            )}
            {showLogs && highlights.slice(4).map((h, i) => (
              <div key={`more-${i}`} className="flex items-start gap-1.5">
                <CheckCircle2 className="h-3 w-3 text-green-400/60 mt-0.5 shrink-0" />
                <span className="text-xs text-muted-foreground leading-relaxed">{h}</span>
              </div>
            ))}
          </div>
        )}

        {/* Completed phase with no highlights — show one-liner */}
        {group.status === "done" && highlights.length === 0 && group.logs.length > 0 && (
          <p className="text-xs text-muted-foreground/60 mt-0.5">
            {group.logs[group.logs.length - 1].message}
          </p>
        )}

        {/* Failed: show errors */}
        {group.status === "failed" && (
          <div className="mt-1.5 space-y-1">
            {group.logs
              .filter((l) => l.level === "error" || l.level === "warning")
              .slice(-3)
              .map((log, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  {log.level === "error" ? (
                    <XCircle className="h-3 w-3 text-red-400/60 mt-0.5 shrink-0" />
                  ) : (
                    <AlertTriangle className="h-3 w-3 text-yellow-400/60 mt-0.5 shrink-0" />
                  )}
                  <span className="text-xs text-muted-foreground leading-relaxed">
                    {log.message.length > 150 ? log.message.slice(0, 147) + "..." : log.message}
                  </span>
                </div>
              ))}
          </div>
        )}

        {/* Expandable raw logs */}
        {(group.status === "done" || group.status === "failed") && group.logs.length > 0 && (
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="text-[11px] text-muted-foreground/40 hover:text-muted-foreground mt-1.5 flex items-center gap-0.5 transition-colors"
          >
            {showLogs ? "Hide logs" : `View ${group.logs.length} log entries`}
            <ChevronDown className={cn("h-3 w-3 transition-transform", showLogs && "rotate-180")} />
          </button>
        )}
        {showLogs && (group.status === "done" || group.status === "failed") && (
          <div className="mt-2 space-y-0.5 pl-1 border-l-2 border-border/50">
            {group.logs.map((log, i) => (
              <div key={i} className="flex items-start gap-2 py-0.5 pl-2">
                <span className="text-[10px] text-muted-foreground/50 shrink-0 tabular-nums w-[60px]">
                  {log.time}
                </span>
                <span className={cn(
                  "text-[11px] leading-relaxed",
                  log.level === "error" ? "text-red-400/80" :
                  log.level === "warning" ? "text-yellow-400/80" :
                  log.level === "success" ? "text-green-400/80" :
                  "text-muted-foreground/60"
                )}>
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────

export function ExecutionTimeline({
  logs,
  currentStatus,
  progress,
  approval,
  onApprove,
  onReject,
}: ExecutionTimelineProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Current phase from latest log
  const currentPhase = useMemo(() => {
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].phase) return logs[i].phase!;
    }
    return "";
  }, [logs]);

  // Group logs by phase
  const phaseGroups: PhaseGroup[] = useMemo(() => {
    const groups: PhaseGroup[] = [];
    let currentGroupPhase = "";

    for (const log of logs) {
      const phase = log.phase || currentGroupPhase;
      if (!phase) continue;

      if (phase !== currentGroupPhase) {
        groups.push({ phase, logs: [], status: "active" });
        currentGroupPhase = phase;
      }

      const group = groups[groups.length - 1];
      if (group) {
        group.logs.push({
          message: log.message || "",
          level: log.level || "info",
          time: log.timestamp
            ? new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
            : "",
        });
      }
    }

    // Set statuses
    const activePhaseIdx = groups.findIndex((g) => g.phase === currentPhase);
    const isCompleted = currentStatus === "completed";
    const isFailed = currentStatus === "failed";

    groups.forEach((g, idx) => {
      if (isCompleted) {
        g.status = "done";
      } else if (isFailed) {
        g.status = idx < activePhaseIdx ? "done" : idx === activePhaseIdx ? "failed" : "upcoming";
      } else {
        g.status = idx < activePhaseIdx ? "done" : idx === activePhaseIdx ? "active" : "upcoming";
      }
    });

    return groups;
  }, [logs, currentPhase, currentStatus]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, autoScroll, approval]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };

  const isEmpty = logs.length === 0;
  const isActive = !["idle", "completed", "failed"].includes(currentStatus);

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      {/* Header */}
      <div className="border-b bg-muted/30 px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Execution Pipeline</h3>
            {isActive && (
              <span className="flex items-center gap-1 text-xs text-primary">
                <Loader2 className="h-3 w-3 animate-spin" />
                Running
              </span>
            )}
            {currentStatus === "completed" && (
              <span className="flex items-center gap-1 text-xs text-green-400">
                <CheckCircle2 className="h-3 w-3" />
                Completed
              </span>
            )}
            {currentStatus === "failed" && (
              <span className="flex items-center gap-1 text-xs text-red-400">
                <XCircle className="h-3 w-3" />
                Failed
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground tabular-nums">{progress}%</span>
        </div>

        {/* Progress bar */}
        <div className="h-1 rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500 ease-out",
              currentStatus === "failed" ? "bg-red-500" :
              currentStatus === "completed" ? "bg-green-500" : "bg-primary"
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Timeline body */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="max-h-[500px] overflow-y-auto"
      >
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
            <Clock className="h-8 w-8 opacity-40" />
            <p className="text-sm">Waiting for task execution...</p>
          </div>
        ) : (
          <div className="px-4 py-4">
            {phaseGroups.map((group, idx) => (
              <PhaseStep
                key={`${group.phase}-${idx}`}
                group={group}
                isLast={idx === phaseGroups.length - 1 && !approval && !isActive}
              />
            ))}

            {/* Inline approval */}
            {approval && (
              <InlineApproval approval={approval} onApprove={onApprove} onReject={onReject} />
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Scroll-to-bottom */}
      {!autoScroll && logs.length > 0 && (
        <div className="border-t px-4 py-1.5 bg-muted/30 flex justify-center">
          <button
            onClick={() => {
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
              setAutoScroll(true);
            }}
            className="text-xs text-primary hover:underline flex items-center gap-1"
          >
            ↓ New activity below
          </button>
        </div>
      )}
    </div>
  );
}
