import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Plug, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PluginItem {
  id: number;
  name: string;
  description: string;
  endpoint_url: string;
  enabled: boolean;
  tools: Array<{ name: string; description: string }>;
  created_at: string;
}

export function PluginManager() {
  const [plugins, setPlugins] = useState<PluginItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchPlugins = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/plugins/");
      if (response.ok) {
        const data = await response.json();
        setPlugins(data);
      }
    } catch {
      // Silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlugins();
  }, [fetchPlugins]);

  const togglePlugin = async (pluginId: number, enabled: boolean) => {
    try {
      const response = await fetch(`/api/plugins/${pluginId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (response.ok) {
        setPlugins((prev) =>
          prev.map((p) => (p.id === pluginId ? { ...p, enabled } : p))
        );
      }
    } catch {
      // Revert on failure
      setPlugins((prev) =>
        prev.map((p) => (p.id === pluginId ? { ...p, enabled: !enabled } : p))
      );
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg flex items-center gap-2">
          <Plug className="h-5 w-5" />
          MCP Plugins
        </CardTitle>
        <Button variant="ghost" size="icon" onClick={fetchPlugins} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </CardHeader>
      <CardContent>
        {plugins.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No plugins registered. Add MCP plugins to extend functionality.
          </p>
        ) : (
          <ScrollArea className="max-h-[300px]">
            <div className="space-y-3">
              {plugins.map((plugin) => (
                <div
                  key={plugin.id}
                  className="flex items-start justify-between gap-3 p-3 rounded-lg border"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-medium">{plugin.name}</h4>
                      <span className="text-xs text-muted-foreground">
                        {plugin.tools.length} tool{plugin.tools.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                    {plugin.description && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {plugin.description}
                      </p>
                    )}
                    {plugin.tools.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {plugin.tools.map((tool, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-xs"
                          >
                            {tool.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={plugin.enabled}
                    onCheckedChange={(checked) => togglePlugin(plugin.id, checked)}
                  />
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
