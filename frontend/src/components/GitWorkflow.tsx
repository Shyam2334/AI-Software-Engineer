import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  GitBranch,
  GitCommit,
  GitPullRequest,
  TestTube2,
  CheckCircle2,
  XCircle,
  ArrowUpCircle,
  ExternalLink,
  ShieldCheck,
  Clock,
} from "lucide-react";

export interface GitEvent {
  type: "git_event" | "test_results";
  event?: string;
  branch_name?: string;
  repo_name?: string;
  commit_sha?: string;
  commit_message?: string;
  files_changed?: string[];
  pr_url?: string;
  pr_number?: number;
  passed?: boolean;
  output?: string;
  attempt?: number;
  max_retries?: number;
  timestamp?: string;
}

interface GitWorkflowProps {
  events: GitEvent[];
  repoName?: string;
  branchName?: string;
  prUrl?: string;
  testOutput?: string;
  testsPassed?: boolean;
}

export function GitWorkflow({
  events,
  repoName,
  branchName,
  prUrl,
  testsPassed,
}: GitWorkflowProps) {
  if (events.length === 0 && !repoName) return null;

  // Derive workflow steps from events
  const branchCreated = events.some((e) => e.event === "branch_created");
  const committed = events.some((e) => e.event === "code_committed");
  const pushed = events.some((e) => e.event === "branch_pushed");
  const prCreated = events.some((e) => e.event === "pr_created");
  const testResults = events.filter((e) => e.type === "test_results");
  const latestTest = testResults.length > 0 ? testResults[testResults.length - 1] : null;
  const commitEvent = events.find((e) => e.event === "code_committed");
  const prEvent = events.find((e) => e.event === "pr_created");

  // Workflow steps for the pipeline visualization
  const steps = [
    {
      label: "Branch",
      icon: GitBranch,
      done: branchCreated,
      detail: branchName || "",
    },
    {
      label: "Tests",
      icon: TestTube2,
      done: latestTest?.passed ?? testsPassed ?? false,
      failed: latestTest ? !latestTest.passed : false,
      detail: latestTest
        ? latestTest.passed
          ? "All tests passed"
          : `Failed (attempt ${latestTest.attempt}/${latestTest.max_retries})`
        : "",
    },
    {
      label: "Commit",
      icon: GitCommit,
      done: committed,
      detail: commitEvent?.commit_sha || "",
    },
    {
      label: "Push",
      icon: ArrowUpCircle,
      done: pushed,
      detail: pushed ? "Pushed to remote" : "",
    },
    {
      label: "Pull Request",
      icon: GitPullRequest,
      done: prCreated,
      detail: prEvent?.pr_url || prUrl || "",
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-primary" />
          Git Workflow
        </CardTitle>
        {repoName && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
            <ShieldCheck className="h-3 w-3 text-green-500" />
            <span>Connected to: </span>
            <a
              href={`https://github.com/${repoName}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline font-mono inline-flex items-center gap-1"
            >
              {repoName}
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Pipeline Visualization */}
        <div className="flex items-center justify-between gap-1">
          {steps.map((step, i) => {
            const Icon = step.icon;
            const isActive =
              !step.done && !("failed" in step && step.failed) && i > 0
                ? steps[i - 1].done
                : i === 0 && !step.done;

            return (
              <div key={step.label} className="flex items-center flex-1">
                <div className="flex flex-col items-center gap-1 flex-1">
                  <div
                    className={`rounded-full p-2 transition-colors ${
                      step.done
                        ? "bg-green-500/20 text-green-500"
                        : "failed" in step && step.failed
                        ? "bg-red-500/20 text-red-500"
                        : isActive
                        ? "bg-blue-500/20 text-blue-500 animate-pulse"
                        : "bg-secondary text-muted-foreground"
                    }`}
                  >
                    {step.done ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : "failed" in step && step.failed ? (
                      <XCircle className="h-5 w-5" />
                    ) : isActive ? (
                      <Clock className="h-5 w-5" />
                    ) : (
                      <Icon className="h-5 w-5" />
                    )}
                  </div>
                  <span
                    className={`text-xs font-medium ${
                      step.done
                        ? "text-green-500"
                        : "failed" in step && step.failed
                        ? "text-red-500"
                        : "text-muted-foreground"
                    }`}
                  >
                    {step.label}
                  </span>
                  {step.detail && (
                    <span className="text-[10px] text-muted-foreground truncate max-w-[80px] text-center">
                      {step.detail}
                    </span>
                  )}
                </div>
                {i < steps.length - 1 && (
                  <div
                    className={`h-0.5 flex-1 mx-1 rounded ${
                      steps[i + 1].done || steps[i].done
                        ? "bg-green-500/50"
                        : "bg-border"
                    }`}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Event Timeline */}
        {events.length > 0 && (
          <div className="border-t pt-3">
            <h4 className="text-sm font-medium mb-2">Activity</h4>
            <ScrollArea className="max-h-[200px]">
              <div className="space-y-2">
                {events.map((event, i) => {
                  const time = event.timestamp
                    ? new Date(event.timestamp).toLocaleTimeString()
                    : "";

                  let icon = <GitBranch className="h-3.5 w-3.5" />;
                  let label = "";
                  let color = "text-muted-foreground";

                  if (event.type === "test_results") {
                    icon = <TestTube2 className="h-3.5 w-3.5" />;
                    label = event.passed
                      ? "Tests passed"
                      : `Tests failed (attempt ${event.attempt}/${event.max_retries})`;
                    color = event.passed ? "text-green-500" : "text-red-500";
                  } else {
                    switch (event.event) {
                      case "branch_created":
                        icon = <GitBranch className="h-3.5 w-3.5" />;
                        label = `Branch created: ${event.branch_name}`;
                        color = "text-blue-400";
                        break;
                      case "code_committed":
                        icon = <GitCommit className="h-3.5 w-3.5" />;
                        label = `Committed ${event.commit_sha}: ${event.commit_message}`;
                        color = "text-purple-400";
                        break;
                      case "branch_pushed":
                        icon = <ArrowUpCircle className="h-3.5 w-3.5" />;
                        label = `Pushed ${event.branch_name} to remote`;
                        color = "text-cyan-400";
                        break;
                      case "pr_created":
                        icon = <GitPullRequest className="h-3.5 w-3.5" />;
                        label = `PR #${event.pr_number} created`;
                        color = "text-green-500";
                        break;
                    }
                  }

                  return (
                    <div
                      key={i}
                      className={`flex items-start gap-2 text-xs ${color}`}
                    >
                      <span className="mt-0.5 shrink-0">{icon}</span>
                      <span className="flex-1">{label}</span>
                      <span className="text-muted-foreground shrink-0 tabular-nums">
                        {time}
                      </span>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </div>
        )}

        {/* Test Coverage Section */}
        {latestTest?.output && (
          <div className="border-t pt-3">
            <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
              <TestTube2 className="h-4 w-4" />
              Test Results & Coverage
            </h4>
            <ScrollArea className="h-[150px] rounded-md border bg-card">
              <pre className="p-3 text-xs font-mono whitespace-pre-wrap text-muted-foreground">
                {latestTest.output}
              </pre>
            </ScrollArea>
          </div>
        )}

        {/* PR Link */}
        {(prEvent?.pr_url || prUrl) && (
          <div className="border-t pt-3">
            <a
              href={prEvent?.pr_url || prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
            >
              <GitPullRequest className="h-4 w-4" />
              View Pull Request
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
