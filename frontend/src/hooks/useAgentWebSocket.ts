import { useCallback, useEffect, useRef, useState } from "react";
import type { GitEvent } from "@/components/GitWorkflow";

export interface WSMessage {
  type: string;
  task_id?: number;
  message?: string;
  level?: string;
  phase?: string;
  progress?: number;
  status?: string;
  timestamp?: string;
  approval_id?: number;
  approval_type?: string;
  title?: string;
  description?: string;
  details?: Record<string, unknown>;
  pr_url?: string;
  error?: string;
  // Git event fields
  event?: string;
  branch_name?: string;
  repo_name?: string;
  commit_sha?: string;
  commit_message?: string;
  files_changed?: string[];
  pr_number?: number;
  // Test results fields
  passed?: boolean;
  output?: string;
  attempt?: number;
  max_retries?: number;
}

interface UseAgentWebSocketReturn {
  connected: boolean;
  messages: WSMessage[];
  logs: WSMessage[];
  gitEvents: GitEvent[];
  currentStatus: string;
  progress: number;
  approvalRequest: WSMessage | null;
  branchName: string;
  repoName: string;
  prUrl: string;
  testsPassed: boolean | null;
  sendMessage: (msg: Record<string, unknown>) => void;
  respondToApproval: (approvalId: number, approved: boolean, message?: string) => void;
  clearMessages: () => void;
}

export function useAgentWebSocket(taskId?: number): UseAgentWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [logs, setLogs] = useState<WSMessage[]>([]);
  const [gitEvents, setGitEvents] = useState<GitEvent[]>([]);
  const [currentStatus, setCurrentStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [approvalRequest, setApprovalRequest] = useState<WSMessage | null>(null);
  const [branchName, setBranchName] = useState("");
  const [repoName, setRepoName] = useState("");
  const [prUrl, setPrUrl] = useState("");
  const [testsPassed, setTestsPassed] = useState<boolean | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 10;

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const path = taskId ? `/ws/${taskId}` : "/ws";
    const url = `${protocol}//${host}${path}`;

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setConnected(true);
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);

          // Skip heartbeats from list
          if (msg.type === "heartbeat") return;

          setMessages((prev) => [...prev, msg]);

          switch (msg.type) {
            case "log":
              setLogs((prev) => [...prev, msg]);
              if (msg.progress !== undefined) setProgress(msg.progress);
              break;
            case "status":
              if (msg.status) setCurrentStatus(msg.status);
              break;
            case "approval_request":
              setApprovalRequest(msg);
              setCurrentStatus("awaiting_approval");
              break;
            case "approval_confirmed":
            case "approval_resolved":
              setApprovalRequest(null);
              break;
            case "git_event":
              setGitEvents((prev) => [...prev, msg as GitEvent]);
              if (msg.event === "branch_created" && msg.branch_name) {
                setBranchName(msg.branch_name);
              }
              if (msg.event === "branch_created" && msg.repo_name) {
                setRepoName(msg.repo_name);
              }
              if (msg.event === "pr_created" && msg.pr_url) {
                setPrUrl(msg.pr_url);
              }
              break;
            case "test_results":
              setGitEvents((prev) => [...prev, msg as GitEvent]);
              if (msg.passed !== undefined) setTestsPassed(msg.passed);
              break;
            case "completed":
              setCurrentStatus("completed");
              setProgress(100);
              break;
            case "failed":
              setCurrentStatus("failed");
              break;
          }
        } catch {
          // Ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;

        // Reconnect with exponential backoff
        if (reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttempts.current++;
            connect();
          }, delay);
        }
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      // Connection failed, will retry
    }
  }, [taskId]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on unmount
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const respondToApproval = useCallback(
    (approvalId: number, approved: boolean, message = "") => {
      sendMessage({
        type: "approval_response",
        approval_id: approvalId,
        approved,
        message,
      });
      setApprovalRequest(null);
    },
    [sendMessage]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setLogs([]);
    setGitEvents([]);
    setProgress(0);
    setCurrentStatus("idle");
    setApprovalRequest(null);
    setBranchName("");
    setRepoName("");
    setPrUrl("");
    setTestsPassed(null);
  }, []);

  return {
    connected,
    messages,
    logs,
    gitEvents,
    currentStatus,
    progress,
    approvalRequest,
    branchName,
    repoName,
    prUrl,
    testsPassed,
    sendMessage,
    respondToApproval,
    clearMessages,
  };
}
