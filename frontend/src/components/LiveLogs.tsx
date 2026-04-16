import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { logLevelColor } from "@/lib/utils";
import type { WSMessage } from "@/hooks/useAgentWebSocket";

interface LiveLogsProps {
  logs: WSMessage[];
}

export function LiveLogs({ logs }: LiveLogsProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  if (logs.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <p>Waiting for activity...</p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[400px] w-full rounded-md border bg-card">
      <div className="p-4 font-mono text-sm space-y-1">
        {logs.map((log, index) => {
          const time = log.timestamp
            ? new Date(log.timestamp).toLocaleTimeString()
            : "";
          const levelColor = logLevelColor(log.level || "info");
          const levelLabel = (log.level || "info").toUpperCase().padEnd(7);

          return (
            <div key={index} className="flex gap-2 leading-relaxed">
              <span className="text-muted-foreground shrink-0 tabular-nums">
                {time}
              </span>
              <span className={`shrink-0 font-bold ${levelColor}`}>
                [{levelLabel}]
              </span>
              {log.phase && (
                <span className="shrink-0 text-primary font-medium">
                  [{log.phase}]
                </span>
              )}
              <span className="text-foreground break-all">{log.message}</span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
