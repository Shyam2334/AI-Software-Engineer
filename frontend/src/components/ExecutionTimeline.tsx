import { useEffect, useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  ChevronRight,
  ShieldAlert,
  Clock,
} from "lucide-react";
import type { WSMessage } from "@/hooks/useAgentWebSocket";
import { cn } from "@/lib/utils";

// ── Phase metadata ───────────────────────────────────────────────────

interface PhaseInfo {
  key: string;
  label: string;
  icon: React.ElementType;
  description: string;
}

const PHASES: PhaseInfo[] = [
  { key: "research", label: "Research", icon: Search, description: "Searching codebase and documentation" },
  { key: "analyze", label: "Analyze", icon: BrainCircuit, description: "Understanding task requirements" },
  { key: "plan", label: "Plan", icon: ClipboardList, description: "Creating implementation plan" },
  { key: "code", label: "Code", icon: Code2, description: "Generating code changes" },
  { key: "test", label: "Test", icon: TestTube2, description: "Running tests" },
  { key: "revise", label: "Revise", icon: RefreshCw, description: "Fixing issues from test failures" },
  { key: "document", label: "Document", icon: FileText, description: "Generating documentation" },
  { key: "create_pr", label: "Pull Request", icon: GitPullRequest, description: "Creating pull request" },
];

function getPhaseIndex(phaseKey: string): number {
  return PHASES.findIndex((p) => p.key === phaseKey);
}

// ── Types ────────────────────────────────────────────────────────────

interface TimelineEntry {
  id: number;
  time: string;
  phase: string;
  level: string;
  message: string;
  isPhaseStart?: boolean;
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

// ── Helper: level icon & colours ─────────────────────────────────────

function levelStyles(level: string) {
  switch (level) {
    case "success":
      return { color: "text-green-400", bg: "bg-green-500/10", border: "border-green-500/30" };
    case "error":
      return { color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/30" };
    case "warning":
      return { color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/30" };
    default:
      return { color: "text-blue-400", bg: "bg-blue-500/10", border: "border-blue-500/30" };
  }
}

function levelIcon(level: string) {
  switch (level) {
    case "success":
      return <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />;
    case "error":
      return <XCircle className="h-3.5 w-3.5 text-red-400" />;
    case "warning":
      return <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" />;
    default:
      return <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />;
  }
}

// ── Inline Approval Card ─────────────────────────────────────────────

function InlineApproval({ approval, onApprove, onReject }: ApprovalInlineProps) {
  if (!approval || !approval.approval_id) return null;

  const details = approval.details || {};
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="ml-8 my-3 rounded-lg border-2 border-yellow-500/40 bg-yellow-500/5 p-4 animate-fade-in-up">
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

          {/* Expandable details */}
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
                    <ScrollArea className="max-h-[200px] rounded border border-border bg-background/50 p-3">
                      <pre className="whitespace-pre-wrap font-mono text-muted-foreground">
                        {String(details.plan)}
                      </pre>
                    </ScrollArea>
                  )}
                  {details.pr_description && (
                    <ScrollArea className="max-h-[150px] rounded border border-border bg-background/50 p-3">
                      <pre className="whitespace-pre-wrap font-mono text-muted-foreground">
                        {String(details.pr_description)}
                      </pre>
                    </ScrollArea>
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

          {/* Action buttons */}
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

// ── Workflow Steps (horizontal pipeline) ─────────────────────────────

function WorkflowSteps({ currentPhase, status }: { currentPhase: string; status: string }) {
  const activeIdx = getPhaseIndex(currentPhase);
  const isComplete = status === "completed";
  const isFailed = status === "failed";

  return (
    <div className="flex items-center gap-0.5 overflow-x-auto pb-1 px-1">
      {PHASES.map((phase, idx) => {
        const Icon = phase.icon;
        let state: "done" | "active" | "upcoming" | "failed" = "upcoming";
        if (isComplete) {
          state = "done";
        } else if (isFailed && idx === activeIdx) {
          state = "failed";
        } else if (idx < activeIdx) {
          state = "done";
        } else if (idx === activeIdx) {
          state = "active";
        }

        const stateStyles = {
          done: "bg-green-500/15 border-green-500/40 text-green-400",
          active: "bg-primary/15 border-primary/40 text-primary",
          upcoming: "bg-muted/30 border-border text-muted-foreground",
          failed: "bg-red-500/15 border-red-500/40 text-red-400",
        };

        return (
          <div key={phase.key} className="flex items-center">
            <div
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-300",
                stateStyles[state],
                state === "active" && "ring-1 ring-primary/30 shadow-sm shadow-primary/10"
              )}
              title={phase.description}
            >
              {state === "active" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : state === "done" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : state === "failed" ? (
                <XCircle className="h-3.5 w-3.5" />
              ) : (
                <Icon className="h-3.5 w-3.5" />
              )}
              <span className="hidden sm:inline">{phase.label}</span>
            </div>
            {idx < PHASES.length - 1 && (
              <div
                className={cn(
                  "w-4 h-px mx-0.5",
                  idx < activeIdx || isComplete ? "bg-green-500/50" : "bg-border"
                )}
              />
            )}
          </div>
        );
      })}
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

  // Derive current phase from the latest log with a phase
  const currentPhase = (() => {
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].phase) return logs[i].phase!;
    }
    return "";
  })();

  // Build timeline entries with phase grouping
  const entries: TimelineEntry[] = [];
  let lastPhase = "";
  logs.forEach((log, idx) => {
    const phase = log.phase || lastPhase;
    const isPhaseStart = phase !== lastPhase;
    if (phase) lastPhase = phase;

    entries.push({
      id: idx,
      time: log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "",
      phase,
      level: log.level || "info",
      message: log.message || "",
      isPhaseStart,
    });
  });

  // Auto-scroll behaviour
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll, approval]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  };

  const isEmpty = logs.length === 0;
  const isActive = !["idle", "completed", "failed"].includes(currentStatus);

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      {/* Workflow Steps Header */}
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
        <div className="h-1 rounded-full bg-muted overflow-hidden mb-3">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500 ease-out",
              currentStatus === "failed" ? "bg-red-500" :
              currentStatus === "completed" ? "bg-green-500" : "bg-primary"
            )}
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Horizontal step indicators */}
        <WorkflowSteps currentPhase={currentPhase} status={currentStatus} />
      </div>

      {/* Timeline Body */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="h-[420px] overflow-y-auto"
      >
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
            <Clock className="h-8 w-8 opacity-40" />
            <p className="text-sm">Waiting for task execution...</p>
          </div>
        ) : (
          <div className="px-4 py-3 space-y-0">
            {entries.map((entry) => {
              const styles = levelStyles(entry.level);
              const PhaseIcon = PHASES.find((p) => p.key === entry.phase)?.icon;

              return (
                <div key={entry.id}>
                  {/* Phase header */}
                  {entry.isPhaseStart && entry.phase && (
                    <div className="flex items-center gap-2 mt-4 mb-2 first:mt-1">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary uppercase tracking-wider">
                        {PhaseIcon && <PhaseIcon className="h-3.5 w-3.5" />}
                        {entry.phase}
                      </div>
                      <div className="flex-1 h-px bg-border" />
                    </div>
                  )}

                  {/* Log entry */}
                  <div className="flex items-start gap-2 py-1 group">
                    {/* Timestamp */}
                    <span className="text-[11px] text-muted-foreground shrink-0 tabular-nums pt-0.5 w-[70px]">
                      {entry.time}
                    </span>

                    {/* Vertical line + dot */}
                    <div className="flex flex-col items-center shrink-0 pt-1">
                      <div className={cn("h-2 w-2 rounded-full", styles.bg, "ring-1", styles.border)} />
                    </div>

                    {/* Level icon + message */}
                    <div className={cn("flex items-start gap-1.5 text-sm min-w-0 py-0.5 px-2 rounded", "group-hover:bg-muted/30 transition-colors")}>
                      {levelIcon(entry.level)}
                      <span className="break-words text-foreground/90 leading-relaxed">
                        {entry.message}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Inline Approval inside timeline */}
            {approval && (
              <InlineApproval
                approval={approval}
                onApprove={onApprove}
                onReject={onReject}
              />
            )}

            {/* Spinner at bottom while active */}
            {isActive && !approval && (
              <div className="flex items-center gap-2 py-3 pl-20 text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span className="text-xs">Working...</span>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Scroll-to-bottom indicator */}
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
