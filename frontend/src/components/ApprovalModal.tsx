import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import type { WSMessage } from "@/hooks/useAgentWebSocket";

interface ApprovalModalProps {
  approval: WSMessage | null;
  onApprove: (approvalId: number) => void;
  onReject: (approvalId: number) => void;
}

export function ApprovalModal({ approval, onApprove, onReject }: ApprovalModalProps) {
  if (!approval || !approval.approval_id) return null;

  const approvalId = approval.approval_id;
  const typeLabels: Record<string, string> = {
    plan_review: "Implementation Plan Review",
    pr_creation: "Pull Request Creation",
    destructive_command: "Destructive Command",
    risky_operation: "Risky Operation",
  };
  const typeLabel = typeLabels[approval.approval_type || ""] || "Approval Required";

  const details = approval.details || {};

  return (
    <Dialog open={true}>
      <DialogContent
        className="sm:max-w-[600px]"
        onPointerDownOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-yellow-500" />
            <DialogTitle>{typeLabel}</DialogTitle>
          </div>
          <DialogDescription>{approval.title}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {approval.description && (
            <p className="text-sm text-muted-foreground">{approval.description}</p>
          )}

          {/* Show plan details */}
          {details.plan && (
            <div>
              <h4 className="text-sm font-medium mb-2">Implementation Plan</h4>
              <ScrollArea className="h-[200px] rounded-md border p-3">
                <pre className="text-xs whitespace-pre-wrap font-mono">
                  {String(details.plan)}
                </pre>
              </ScrollArea>
            </div>
          )}

          {/* Show PR description */}
          {details.pr_description && (
            <div>
              <h4 className="text-sm font-medium mb-2">PR Description</h4>
              <ScrollArea className="h-[150px] rounded-md border p-3">
                <pre className="text-xs whitespace-pre-wrap font-mono">
                  {String(details.pr_description)}
                </pre>
              </ScrollArea>
            </div>
          )}

          {/* Show files changed */}
          {details.files_changed && Array.isArray(details.files_changed) && (
            <div>
              <h4 className="text-sm font-medium mb-2">
                Files Changed ({(details.files_changed as string[]).length})
              </h4>
              <ul className="text-xs space-y-1 list-disc list-inside">
                {(details.files_changed as string[]).map((file, i) => (
                  <li key={i} className="text-muted-foreground font-mono">
                    {file}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Show test output */}
          {details.test_output && (
            <div>
              <h4 className="text-sm font-medium mb-2">Test Output</h4>
              <ScrollArea className="h-[100px] rounded-md border p-3">
                <pre className="text-xs whitespace-pre-wrap font-mono text-green-400">
                  {String(details.test_output)}
                </pre>
              </ScrollArea>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="destructive"
            onClick={() => onReject(approvalId)}
            className="gap-1"
          >
            <XCircle className="h-4 w-4" />
            Reject
          </Button>
          <Button onClick={() => onApprove(approvalId)} className="gap-1">
            <CheckCircle className="h-4 w-4" />
            Approve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
