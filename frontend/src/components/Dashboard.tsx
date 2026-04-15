import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ExecutionTimeline } from "@/components/ExecutionTimeline";
import { GitWorkflow } from "@/components/GitWorkflow";
import { useAgentWebSocket, type WSMessage } from "@/hooks/useAgentWebSocket";
import { statusBadgeClasses } from "@/lib/utils";
import {
  Bot,
  Send,
  Loader2,
  Wifi,
  WifiOff,
  CheckCircle2,
  XCircle,
  GitBranch,
  FolderGit2,
  ChevronDown,
  ChevronUp,
  User,
  Sparkles,
  Plus,
  Paperclip,
  X,
  Search,
  Lock,
  Globe,
} from "lucide-react";

interface GitHubRepo {
  full_name: string;
  html_url: string;
  description: string | null;
  private: boolean;
  default_branch: string;
  updated_at: string;
}

// ── Types ────────────────────────────────────────────────────────────

type TaskType = "feature" | "bugfix" | "test" | "enhancement" | "refactor" | "docs";

interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: Date;
  taskId?: number;
  taskType?: TaskType;
  repoUrl?: string;
  repoName?: string;
}

interface DashboardProps {
  selectedTaskId?: number;
  onTaskStarted?: (taskId: number) => void;
}

const TASK_TYPES: { value: TaskType; label: string; emoji: string }[] = [
  { value: "feature", label: "Feature", emoji: "✨" },
  { value: "bugfix", label: "Bug Fix", emoji: "🐛" },
  { value: "test", label: "Tests", emoji: "🧪" },
  { value: "enhancement", label: "Enhancement", emoji: "⚡" },
  { value: "refactor", label: "Refactor", emoji: "♻️" },
  { value: "docs", label: "Docs", emoji: "📝" },
];

// ── Dashboard (Chat Interface) ──────────────────────────────────────

export function Dashboard({ selectedTaskId, onTaskStarted }: DashboardProps) {
  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [repoNameInput, setRepoNameInput] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("feature");
  const [showRepoInput, setShowRepoInput] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | undefined>();
  const [showGitWorkflow, setShowGitWorkflow] = useState(false);
  const [historicalLogs, setHistoricalLogs] = useState<WSMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [githubRepos, setGithubRepos] = useState<GitHubRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [repoSearch, setRepoSearch] = useState("");
  const [repoDropdownOpen, setRepoDropdownOpen] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    connected,
    logs,
    gitEvents,
    currentStatus,
    progress,
    approvalRequest,
    branchName,
    repoName: wsRepoName,
    prUrl,
    testsPassed,
    respondToApproval,
    clearMessages,
  } = useAgentWebSocket(activeTaskId);

  // ── Load task from history ──────────────────────────────────────

  const loadTaskHistory = useCallback(async (taskId: number) => {
    setLoadingHistory(true);
    try {
      const taskRes = await fetch(`/api/tasks/${taskId}`);
      if (!taskRes.ok) return;
      const task = await taskRes.json();

      const logsRes = await fetch(`/api/tasks/${taskId}/logs?limit=500`);
      const logsData = logsRes.ok ? await logsRes.json() : [];

      const wsLogs: WSMessage[] = logsData.map((log: { message: string; level: string; phase?: string; created_at: string }) => ({
        type: "log",
        task_id: taskId,
        message: log.message,
        level: log.level,
        phase: log.phase || undefined,
        timestamp: log.created_at,
      }));

      setHistoricalLogs(wsLogs);

      const newMessages: ChatMessage[] = [
        {
          id: `task-${taskId}-user`,
          role: "user",
          content: task.title + (task.description ? `\n${task.description}` : ""),
          timestamp: new Date(task.created_at),
          taskId: taskId,
          repoUrl: task.repo_url || undefined,
          repoName: task.repo_name || undefined,
        },
        {
          id: `task-${taskId}-agent`,
          role: "agent",
          content: `Working on task #${taskId}...`,
          timestamp: new Date(task.created_at),
          taskId: taskId,
        },
      ];

      setChatMessages(newMessages);
      if (task.repo_url) setRepoUrl(task.repo_url);
      if (task.repo_name) setRepoNameInput(task.repo_name);
    } catch (err) {
      console.error("Failed to load task history:", err);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (selectedTaskId && selectedTaskId !== activeTaskId) {
      clearMessages();
      setActiveTaskId(selectedTaskId);
      loadTaskHistory(selectedTaskId);
    }
  }, [selectedTaskId, activeTaskId, clearMessages, loadTaskHistory]);

  const allLogs =
    activeTaskId === selectedTaskId && historicalLogs.length > 0 && logs.length === 0
      ? historicalLogs
      : logs.length > 0
        ? logs
        : historicalLogs;

  // ── File upload handler ─────────────────────────────────────

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/tasks/upload-document", {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        // Fetch the full content
        const contentRes = await fetch(`/api/tasks/upload-document/${data.upload_id}`);
        if (contentRes.ok) {
          const contentData = await contentRes.json();
          setUploadedFile({ name: data.filename, content: contentData.content });
        }
      } else {
        const err = await res.json();
        alert(err.detail || "Upload failed");
      }
    } catch {
      alert("Upload failed. Check connection.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // ── Fetch GitHub repos when repo input opens ─────────────────

  const fetchGithubRepos = useCallback(async () => {
    setReposLoading(true);
    try {
      const res = await fetch("/api/connectors/github/repos?per_page=100");
      if (res.ok) {
        setGithubRepos(await res.json());
      }
    } catch {
      // GitHub not connected — dropdown will show manual input hint
    } finally {
      setReposLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showRepoInput && githubRepos.length === 0) {
      fetchGithubRepos();
    }
  }, [showRepoInput, fetchGithubRepos, githubRepos.length]);

  const filteredRepos = githubRepos.filter(
    (r) =>
      r.full_name.toLowerCase().includes(repoSearch.toLowerCase()) ||
      (r.description?.toLowerCase().includes(repoSearch.toLowerCase()) ?? false)
  );

  const selectRepo = (repo: GitHubRepo) => {
    setRepoUrl(repo.html_url);
    setRepoNameInput(repo.full_name);
    setRepoDropdownOpen(false);
    setRepoSearch("");
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, logs, approvalRequest]);

  // ── Submit a new task ───────────────────────────────────────────

  const handleSubmit = async () => {
    const message = inputValue.trim();
    if (!message || submitting) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: message,
      timestamp: new Date(),
      taskType,
      repoUrl: repoUrl || undefined,
      repoName: repoNameInput || undefined,
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setInputValue("");

    if (!activeTaskId) {
      setSubmitting(true);
      clearMessages();
      setHistoricalLogs([]);

      const fullDescription = `[${taskType.toUpperCase()}] ${message}`;

      try {
        const response = await fetch("/api/tasks/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: message.slice(0, 100),
            description: fullDescription,
            repo_url: repoUrl.trim() || undefined,
            repo_name: repoNameInput.trim() || undefined,
            document_context: uploadedFile?.content || undefined,
          }),
        });

        if (response.ok) {
          const task = await response.json();
          setActiveTaskId(task.id);
          onTaskStarted?.(task.id);
          setUploadedFile(null);

          setChatMessages((prev) => [
            ...prev,
            {
              id: `ack-${task.id}`,
              role: "agent",
              content: `Got it! Starting task #${task.id}. I'll research, plan, write code, run tests, and create a pull request.`,
              timestamp: new Date(),
              taskId: task.id,
            },
          ]);
        } else {
          setChatMessages((prev) => [
            ...prev,
            {
              id: `err-${Date.now()}`,
              role: "system",
              content: "Failed to create task. Please try again.",
              timestamp: new Date(),
            },
          ]);
        }
      } catch {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "system",
            content: "Connection error. Make sure the backend is running.",
            timestamp: new Date(),
          },
        ]);
      } finally {
        setSubmitting(false);
      }
    } else {
      // Follow-up on active task: create a new related task
      setSubmitting(true);
      const fullDescription = `[${taskType.toUpperCase()}] Follow-up on task #${activeTaskId}: ${message}`;

      try {
        const response = await fetch("/api/tasks/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: message.slice(0, 100),
            description: fullDescription,
            repo_url: repoUrl.trim() || undefined,
            repo_name: repoNameInput.trim() || undefined,
            document_context: uploadedFile?.content || undefined,
          }),
        });

        if (response.ok) {
          const task = await response.json();
          clearMessages();
          setHistoricalLogs([]);
          setActiveTaskId(task.id);
          onTaskStarted?.(task.id);
          setUploadedFile(null);

          setChatMessages((prev) => [
            ...prev,
            {
              id: `ack-${task.id}`,
              role: "agent",
              content: `Starting follow-up task #${task.id}. I'll work on this right away.`,
              timestamp: new Date(),
              taskId: task.id,
            },
          ]);
        } else {
          setChatMessages((prev) => [
            ...prev,
            {
              id: `err-${Date.now()}`,
              role: "system",
              content: "Failed to create follow-up task.",
              timestamp: new Date(),
            },
          ]);
        }
      } catch {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "system",
            content: "Connection error.",
            timestamp: new Date(),
          },
        ]);
      } finally {
        setSubmitting(false);
      }
    }

    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const startNewChat = () => {
    setChatMessages([]);
    setActiveTaskId(undefined);
    clearMessages();
    setHistoricalLogs([]);
    setRepoUrl("");
    setRepoNameInput("");
    setShowGitWorkflow(false);
    setUploadedFile(null);
    inputRef.current?.focus();
  };

  const displayRepoName =
    wsRepoName || repoNameInput || (repoUrl ? extractRepoName(repoUrl) : "");

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      {/* ── Chat Messages Area ──────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 py-6 space-y-4">
          {/* Welcome state */}
          {chatMessages.length === 0 && !loadingHistory && (
            <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
              <div className="p-4 rounded-full bg-primary/10">
                <Bot className="h-12 w-12 text-primary" />
              </div>
              <h2 className="text-2xl font-bold">ASaaP Jr. Software Developer</h2>
              <p className="text-muted-foreground text-center max-w-md">
                Describe what you want to build, fix, or improve. I'll research,
                plan, write code, run tests, and create a pull request.
              </p>
              <div className="flex flex-wrap gap-2 justify-center mt-4">
                {[
                  "Add dark mode toggle to the app",
                  "Fix the login validation bug",
                  "Write unit tests for the API",
                  "Refactor the database queries",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => {
                      setInputValue(suggestion);
                      inputRef.current?.focus();
                    }}
                    className="text-xs px-3 py-2 rounded-lg border border-border hover:border-primary/50 hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Loading history */}
          {loadingHistory && (
            <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>Loading task session...</span>
            </div>
          )}

          {/* Chat messages */}
          {chatMessages.map((msg) => (
            <div key={msg.id}>
              {msg.role === "user" && (
                <div className="flex gap-3 justify-end">
                  <div className="max-w-[80%]">
                    {msg.taskType && (
                      <div className="flex items-center gap-2 mb-1 justify-end">
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                          {TASK_TYPES.find((t) => t.value === msg.taskType)?.emoji}{" "}
                          {TASK_TYPES.find((t) => t.value === msg.taskType)?.label}
                        </span>
                        {msg.repoName && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-mono">
                            {msg.repoName}
                          </span>
                        )}
                      </div>
                    )}
                    <div className="rounded-2xl rounded-tr-md bg-primary text-primary-foreground px-4 py-2.5">
                      <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1 text-right">
                      {msg.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                  <div className="shrink-0 w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center">
                    <User className="h-4 w-4 text-primary" />
                  </div>
                </div>
              )}

              {msg.role === "agent" && (
                <div className="flex gap-3">
                  <div className="shrink-0 w-8 h-8 rounded-full bg-accent flex items-center justify-center">
                    <Sparkles className="h-4 w-4 text-primary" />
                  </div>
                  <div className="max-w-[90%] min-w-0 flex-1">
                    <div className="rounded-2xl rounded-tl-md bg-card border px-4 py-2.5">
                      <p className="text-sm">{msg.content}</p>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {msg.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              )}

              {msg.role === "system" && (
                <div className="flex justify-center">
                  <span className="text-xs text-muted-foreground bg-muted px-3 py-1 rounded-full">
                    {msg.content}
                  </span>
                </div>
              )}
            </div>
          ))}

          {/* Execution Timeline */}
          {activeTaskId && allLogs.length > 0 && (
            <div className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-full bg-accent flex items-center justify-center">
                <Sparkles className="h-4 w-4 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <ExecutionTimeline
                  logs={allLogs}
                  currentStatus={currentStatus}
                  progress={progress}
                  approval={approvalRequest}
                  onApprove={(id) => respondToApproval(id, true)}
                  onReject={(id) => respondToApproval(id, false)}
                />
              </div>
            </div>
          )}

          {/* Completion */}
          {activeTaskId && currentStatus === "completed" && (
            <div className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-full bg-green-500/20 flex items-center justify-center">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              </div>
              <div className="flex-1">
                <div className="rounded-2xl rounded-tl-md bg-green-500/5 border border-green-500/20 px-4 py-3">
                  <p className="text-sm font-medium text-green-500">Task completed successfully!</p>
                  {prUrl && (
                    <a href={prUrl} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline mt-1 inline-block">
                      View Pull Request →
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Failed */}
          {activeTaskId && currentStatus === "failed" && (
            <div className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
                <XCircle className="h-4 w-4 text-red-500" />
              </div>
              <div className="flex-1">
                <div className="rounded-2xl rounded-tl-md bg-red-500/5 border border-red-500/20 px-4 py-3">
                  <p className="text-sm font-medium text-red-500">Task failed. Check the execution logs above for details.</p>
                </div>
              </div>
            </div>
          )}

          {/* Git workflow (collapsible) */}
          {activeTaskId && gitEvents.length > 0 && (
            <div className="flex gap-3">
              <div className="shrink-0 w-8" />
              <div className="flex-1">
                <button
                  onClick={() => setShowGitWorkflow(!showGitWorkflow)}
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 mb-2"
                >
                  <GitBranch className="h-3 w-3" />
                  Git Activity
                  {showGitWorkflow ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>
                {showGitWorkflow && (
                  <GitWorkflow
                    events={gitEvents}
                    repoName={displayRepoName}
                    branchName={branchName}
                    prUrl={prUrl}
                    testsPassed={testsPassed ?? undefined}
                  />
                )}
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>
      </div>

      {/* ── Bottom Input Area ───────────────────────────────────── */}
      <div className="border-t bg-background/95 backdrop-blur">
        <div className="max-w-4xl mx-auto px-4 py-3 space-y-2">
          {/* Repo selector (toggleable) */}
          {showRepoInput && (
            <div className="rounded-lg border bg-card animate-fade-in-up relative">
              <div className="flex items-center gap-2 p-2">
                <FolderGit2 className="h-4 w-4 text-primary shrink-0" />
                <div className="relative flex-1">
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                      <input
                        type="text"
                        placeholder={githubRepos.length > 0 ? "Search repos or paste URL..." : "Paste GitHub repo URL..."}
                        value={repoSearch || repoUrl}
                        onChange={(e) => {
                          const val = e.target.value;
                          setRepoSearch(val);
                          if (val.includes("github.com/")) {
                            setRepoUrl(val);
                            const name = extractRepoName(val);
                            if (name) setRepoNameInput(name);
                            setRepoDropdownOpen(false);
                          } else if (githubRepos.length > 0) {
                            setRepoDropdownOpen(true);
                          }
                        }}
                        onFocus={() => { if (githubRepos.length > 0) setRepoDropdownOpen(true); }}
                        onBlur={() => { setTimeout(() => setRepoDropdownOpen(false), 200); }}
                        className="w-full pl-8 pr-3 py-1.5 bg-transparent text-sm placeholder:text-muted-foreground focus:outline-none"
                        disabled={submitting || !!activeTaskId}
                      />
                    </div>
                    {githubRepos.length > 0 && !displayRepoName && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs shrink-0"
                        onClick={() => setRepoDropdownOpen(!repoDropdownOpen)}
                      >
                        <ChevronDown className={`h-3 w-3 transition-transform ${repoDropdownOpen ? "rotate-180" : ""}`} />
                      </Button>
                    )}
                    {displayRepoName && (
                      <button
                        onClick={() => { setRepoUrl(""); setRepoNameInput(""); setRepoSearch(""); }}
                        className="text-xs text-green-500 flex items-center gap-1 shrink-0 hover:opacity-70"
                      >
                        <CheckCircle2 className="h-3 w-3" />
                        {displayRepoName}
                        <X className="h-2.5 w-2.5 ml-0.5" />
                      </button>
                    )}
                  </div>

                  {/* Dropdown — opens upward */}
                  {repoDropdownOpen && !activeTaskId && githubRepos.length > 0 && (
                    <div className="absolute left-0 right-0 bottom-full mb-1 z-50 rounded-lg border bg-popover shadow-lg max-h-60 overflow-y-auto">
                      {reposLoading && (
                        <div className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading repos...
                        </div>
                      )}
                      {!reposLoading && filteredRepos.length === 0 && (
                        <div className="p-3 text-xs text-muted-foreground">
                          No repos match "{repoSearch}". Try a different search or paste a URL.
                        </div>
                      )}
                      {!reposLoading && filteredRepos.map((repo) => (
                        <button
                          key={repo.full_name}
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => selectRepo(repo)}
                          className="w-full text-left px-3 py-2 hover:bg-accent flex items-center gap-2.5 border-b border-border/40 last:border-0 transition-colors"
                        >
                          {repo.private ? (
                            <Lock className="h-3.5 w-3.5 text-yellow-500 shrink-0" />
                          ) : (
                            <Globe className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium truncate">{repo.full_name}</p>
                            {repo.description && (
                              <p className="text-[10px] text-muted-foreground truncate">{repo.description}</p>
                            )}
                          </div>
                          <span className="text-[10px] text-muted-foreground shrink-0">{repo.default_branch}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Main input row */}
          <div className="flex items-end gap-2">
            <div className="flex items-center gap-1 pb-1">
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={startNewChat} title="New task">
                <Plus className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={`h-8 w-8 ${showRepoInput ? "text-primary" : ""}`}
                onClick={() => setShowRepoInput(!showRepoInput)}
                title="Repository settings"
              >
                <FolderGit2 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={`h-8 w-8 ${uploadedFile ? "text-primary" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                disabled={submitting || uploading}
                title="Upload document for context"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept=".txt,.md,.py,.js,.ts,.jsx,.tsx,.json,.csv,.yaml,.yml,.xml,.html,.css,.sql,.sh,.bat,.cfg,.ini,.toml,.env,.log"
                onChange={handleFileUpload}
              />
            </div>

            {!activeTaskId && (
              <div className="flex items-center gap-1 pb-1">
                {TASK_TYPES.map((t) => (
                  <button
                    key={t.value}
                    onClick={() => setTaskType(t.value)}
                    className={`text-[11px] px-2 py-1 rounded-full transition-colors ${
                      taskType === t.value
                        ? "bg-primary/15 text-primary font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent"
                    }`}
                    title={t.label}
                  >
                    {t.emoji}
                  </button>
                ))}
              </div>
            )}

            <div className="flex-1 relative">
              {uploadedFile && (
                <div className="flex items-center gap-1 mb-1 ml-1">
                  <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                    <Paperclip className="h-3 w-3" />
                    {uploadedFile.name}
                    <button
                      onClick={() => setUploadedFile(null)}
                      className="ml-0.5 hover:text-red-500 transition-colors"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                </div>
              )}
              <Textarea
                ref={inputRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  activeTaskId
                    ? "Send a follow-up message..."
                    : "Describe what you want to build, fix, or improve..."
                }
                disabled={submitting}
                rows={1}
                className="resize-none min-h-[42px] max-h-[160px] pr-12 rounded-xl border-border/80 bg-card"
              />
              <Button
                size="icon"
                onClick={handleSubmit}
                disabled={!inputValue.trim() || submitting}
                className="absolute right-1.5 bottom-1.5 h-8 w-8 rounded-lg"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>

          {/* Status bar */}
          <div className="flex items-center justify-between text-[11px] text-muted-foreground px-1">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                {connected ? (
                  <><Wifi className="h-3 w-3 text-green-500" /><span className="text-green-500">Connected</span></>
                ) : (
                  <><WifiOff className="h-3 w-3 text-red-500" /><span className="text-red-500">Disconnected</span></>
                )}
              </span>
              {activeTaskId && (
                <span className="flex items-center gap-1">
                  Task #{activeTaskId}
                  <span className={statusBadgeClasses(currentStatus)}>
                    {currentStatus.replace("_", " ")}
                  </span>
                </span>
              )}
            </div>
            <span>Enter to send · Shift+Enter for new line</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function extractRepoName(url: string): string {
  if (!url) return "";
  try {
    const cleaned = url.replace(/\.git$/, "").replace(/\/$/, "");
    const parts = cleaned.split("/");
    if (parts.length >= 2) {
      const repo = parts[parts.length - 1];
      const owner = parts[parts.length - 2];
      if (owner && repo && !owner.includes(".")) {
        return `${owner}/${repo}`;
      }
    }
  } catch {
    // ignore
  }
  return "";
}
