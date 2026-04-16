import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Github,
  ExternalLink,
  Eye,
  EyeOff,
  Unplug,
  PlugZap,
  Info,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────

interface ConnectorStatus {
  provider: string;
  connected: boolean;
  details: {
    owner?: string;
    login?: string;
    base_url?: string;
    email?: string;
    display_name?: string;
    project_key?: string;
    setup_instructions?: string[];
    required_fields?: string[];
  };
}

interface MCPSettingsProps {
  onClose: () => void;
}

// ── Component ────────────────────────────────────────────────────────

export function MCPSettings({ onClose }: MCPSettingsProps) {
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [loading, setLoading] = useState(true);

  // GitHub form
  const [ghToken, setGhToken] = useState("");
  const [ghOwner, setGhOwner] = useState("");
  const [ghSubmitting, setGhSubmitting] = useState(false);
  const [ghError, setGhError] = useState("");
  const [showGhToken, setShowGhToken] = useState(false);

  // Jira form
  const [jiraUrl, setJiraUrl] = useState("");
  const [jiraEmail, setJiraEmail] = useState("");
  const [jiraToken, setJiraToken] = useState("");
  const [jiraProject, setJiraProject] = useState("");
  const [jiraSubmitting, setJiraSubmitting] = useState(false);
  const [jiraError, setJiraError] = useState("");
  const [showJiraToken, setShowJiraToken] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/connectors/status");
      if (res.ok) {
        const data = await res.json();
        setConnectors(data);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const github = connectors.find((c) => c.provider === "github");
  const jira = connectors.find((c) => c.provider === "jira");

  // ── GitHub connect ─────────────────────────────────────────────

  const connectGithub = async () => {
    if (!ghToken.trim()) {
      setGhError("Token is required");
      return;
    }
    setGhSubmitting(true);
    setGhError("");
    try {
      const res = await fetch("/api/connectors/github/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: ghToken.trim(), owner: ghOwner.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        setGhError(err.detail || "Connection failed");
      } else {
        setGhToken("");
        setGhOwner("");
        await fetchStatus();
      }
    } catch {
      setGhError("Network error");
    } finally {
      setGhSubmitting(false);
    }
  };

  const disconnectGithub = async () => {
    await fetch("/api/connectors/github/disconnect", { method: "POST" });
    await fetchStatus();
  };

  // ── Jira connect ───────────────────────────────────────────────

  const connectJira = async () => {
    if (!jiraUrl.trim() || !jiraEmail.trim() || !jiraToken.trim()) {
      setJiraError("Base URL, email, and API token are all required");
      return;
    }
    setJiraSubmitting(true);
    setJiraError("");
    try {
      const res = await fetch("/api/connectors/jira/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: jiraUrl.trim(),
          email: jiraEmail.trim(),
          api_token: jiraToken.trim(),
          project_key: jiraProject.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        setJiraError(err.detail || "Connection failed");
      } else {
        setJiraToken("");
        await fetchStatus();
      }
    } catch {
      setJiraError("Network error");
    } finally {
      setJiraSubmitting(false);
    }
  };

  const disconnectJira = async () => {
    await fetch("/api/connectors/jira/disconnect", { method: "POST" });
    await fetchStatus();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-6 space-y-8 max-w-2xl mx-auto">
        <div>
          <h2 className="text-xl font-bold">MCP Connectors</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Connect external services so ASaaP Jr. can interact with your repos, issues, and workflows.
          </p>
        </div>

        {/* ── GitHub ──────────────────────────────────────────── */}
        <section className="rounded-xl border bg-card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b bg-muted/30">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-[#24292f] text-white">
                <Github className="h-5 w-5" />
              </div>
              <div>
                <h3 className="font-semibold">GitHub</h3>
                <p className="text-xs text-muted-foreground">Repository access, PRs, code push</p>
              </div>
            </div>
            {github?.connected ? (
              <span className="flex items-center gap-1.5 text-xs font-medium text-green-600 bg-green-500/10 px-2.5 py-1 rounded-full">
                <CheckCircle2 className="h-3.5 w-3.5" /> Connected
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground bg-muted px-2.5 py-1 rounded-full">
                <XCircle className="h-3.5 w-3.5" /> Not connected
              </span>
            )}
          </div>

          <div className="p-5 space-y-4">
            {github?.connected ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm">
                      Owner: <span className="font-mono font-medium">{github.details.owner}</span>
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={disconnectGithub} className="text-red-500 hover:text-red-600">
                    <Unplug className="h-3.5 w-3.5 mr-1.5" /> Disconnect
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Setup instructions */}
                <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
                  <div className="flex items-start gap-2">
                    <Info className="h-4 w-4 text-blue-500 mt-0.5 shrink-0" />
                    <div className="space-y-1.5">
                      <p className="text-sm font-medium text-blue-700 dark:text-blue-400">Setup Instructions</p>
                      <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                        <li>
                          Go to{" "}
                          <a href="https://github.com/settings/tokens" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">
                            GitHub Settings &rarr; Tokens <ExternalLink className="h-2.5 w-2.5" />
                          </a>
                        </li>
                        <li>Create a <strong>Fine-grained PAT</strong> (recommended)</li>
                        <li>Select target repos, grant <strong>Contents: Read & Write</strong> and <strong>Pull Requests: Read & Write</strong></li>
                        <li>Copy the token and paste it below</li>
                      </ol>
                    </div>
                  </div>
                </div>

                {/* Token input */}
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Personal Access Token *</label>
                  <div className="relative">
                    <input
                      type={showGhToken ? "text" : "password"}
                      placeholder="ghp_... or github_pat_..."
                      value={ghToken}
                      onChange={(e) => setGhToken(e.target.value)}
                      className="w-full px-3 py-2 pr-10 rounded-lg border bg-background text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                    <button
                      type="button"
                      onClick={() => setShowGhToken(!showGhToken)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showGhToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">GitHub Username / Org</label>
                  <input
                    type="text"
                    placeholder="e.g., octocat"
                    value={ghOwner}
                    onChange={(e) => setGhOwner(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                  <p className="text-[10px] text-muted-foreground">Leave empty to auto-detect from token.</p>
                </div>

                {ghError && <p className="text-xs text-red-500">{ghError}</p>}

                <Button onClick={connectGithub} disabled={ghSubmitting} size="sm" className="w-full">
                  {ghSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <PlugZap className="h-4 w-4 mr-2" />}
                  Connect GitHub
                </Button>
              </div>
            )}
          </div>
        </section>

        {/* ── Jira ───────────────────────────────────────────── */}
        <section className="rounded-xl border bg-card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b bg-muted/30">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-[#0052CC] text-white">
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M11.571 11.513H0a5.218 5.218 0 005.232 5.215h2.13v2.057A5.215 5.215 0 0012.575 24V12.518a1.005 1.005 0 00-1.005-1.005z" />
                  <path d="M6.348 6.349H17.92a5.218 5.218 0 00-5.233-5.215h-2.13V-.924A5.215 5.215 0 005.345 4.29v11.482a1.005 1.005 0 001.005 1.005h11.57a5.218 5.218 0 00-5.232-5.215H10.56V9.507a5.215 5.215 0 00-5.213-5.215V6.35z" opacity="0.4" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold">Jira</h3>
                <p className="text-xs text-muted-foreground">Issue tracking, sprint management</p>
              </div>
            </div>
            {jira?.connected ? (
              <span className="flex items-center gap-1.5 text-xs font-medium text-green-600 bg-green-500/10 px-2.5 py-1 rounded-full">
                <CheckCircle2 className="h-3.5 w-3.5" /> Connected
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground bg-muted px-2.5 py-1 rounded-full">
                <XCircle className="h-3.5 w-3.5" /> Not connected
              </span>
            )}
          </div>

          <div className="p-5 space-y-4">
            {jira?.connected ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <p className="text-sm">
                      Instance: <span className="font-mono font-medium">{jira.details.base_url}</span>
                    </p>
                    {jira.details.display_name && (
                      <p className="text-xs text-muted-foreground">Signed in as {jira.details.display_name}</p>
                    )}
                    {jira.details.project_key && (
                      <p className="text-xs text-muted-foreground">
                        Project: <span className="font-mono">{jira.details.project_key}</span>
                      </p>
                    )}
                  </div>
                  <Button variant="outline" size="sm" onClick={disconnectJira} className="text-red-500 hover:text-red-600">
                    <Unplug className="h-3.5 w-3.5 mr-1.5" /> Disconnect
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Setup instructions */}
                <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
                  <div className="flex items-start gap-2">
                    <Info className="h-4 w-4 text-blue-500 mt-0.5 shrink-0" />
                    <div className="space-y-1.5">
                      <p className="text-sm font-medium text-blue-700 dark:text-blue-400">Setup Instructions</p>
                      <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                        <li>
                          Go to{" "}
                          <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">
                            Atlassian API Tokens <ExternalLink className="h-2.5 w-2.5" />
                          </a>
                        </li>
                        <li>Click <strong>"Create API token"</strong> and give it a label</li>
                        <li>Your Base URL is your Jira domain (e.g., <code className="bg-muted px-1 rounded">https://yourteam.atlassian.net</code>)</li>
                        <li>Use your Atlassian account email</li>
                      </ol>
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Jira Base URL *</label>
                  <input
                    type="text"
                    placeholder="https://yourteam.atlassian.net"
                    value={jiraUrl}
                    onChange={(e) => setJiraUrl(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Email *</label>
                  <input
                    type="email"
                    placeholder="you@example.com"
                    value={jiraEmail}
                    onChange={(e) => setJiraEmail(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">API Token *</label>
                  <div className="relative">
                    <input
                      type={showJiraToken ? "text" : "password"}
                      placeholder="Paste your Jira API token"
                      value={jiraToken}
                      onChange={(e) => setJiraToken(e.target.value)}
                      className="w-full px-3 py-2 pr-10 rounded-lg border bg-background text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                    <button
                      type="button"
                      onClick={() => setShowJiraToken(!showJiraToken)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showJiraToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Default Project Key (optional)</label>
                  <input
                    type="text"
                    placeholder="e.g., PROJ"
                    value={jiraProject}
                    onChange={(e) => setJiraProject(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border bg-background text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </div>

                {jiraError && <p className="text-xs text-red-500">{jiraError}</p>}

                <Button onClick={connectJira} disabled={jiraSubmitting} size="sm" className="w-full">
                  {jiraSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <PlugZap className="h-4 w-4 mr-2" />}
                  Connect Jira
                </Button>
              </div>
            )}
          </div>
        </section>

        <div className="pb-6" />
      </div>
    </ScrollArea>
  );
}
