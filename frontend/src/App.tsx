import { useState } from "react";
import { Dashboard } from "@/components/Dashboard";
import { TaskHistory } from "@/components/TaskHistory";
import { MCPSettings } from "@/components/MCPSettings";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Bot, PanelLeftClose, PanelLeft, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLocalStorage } from "@/hooks/useLocalStorage";

function App() {
  const [sidebarOpen, setSidebarOpen] = useLocalStorage("sidebar-open", true);
  const [_selectedTaskId, setSelectedTaskId] = useState<number | undefined>();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex h-14 items-center px-4 gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen((prev) => !prev)}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-5 w-5" />
            ) : (
              <PanelLeft className="h-5 w-5" />
            )}
          </Button>

          <div className="flex items-center gap-2">
            <Bot className="h-6 w-6 text-primary" />
            <h1 className="text-lg font-bold">ASaaP Jr. Software Developer</h1>
          </div>

          <div className="flex-1" />

          <Button
            variant="ghost"
            size="icon"
            onClick={() => setShowSettings(!showSettings)}
            className={showSettings ? "text-primary" : ""}
            title="MCP Connector Settings"
          >
            <Settings className="h-5 w-5" />
          </Button>
          <ThemeToggle />
        </div>
      </header>

      {/* Main Layout */}
      <div className="flex">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-80 border-r bg-card h-[calc(100vh-3.5rem)] sticky top-14">
            <TaskHistory
              onSelectTask={(id) => { setSelectedTaskId(id); setShowSettings(false); }}
              selectedTaskId={_selectedTaskId}
            />
          </aside>
        )}

        {/* Main Content */}
        <main className="flex-1 max-w-5xl mx-auto">
          {showSettings ? (
            <div className="h-[calc(100vh-3.5rem)]">
              <MCPSettings onClose={() => setShowSettings(false)} />
            </div>
          ) : (
            <div className="p-6">
              <Dashboard
                selectedTaskId={_selectedTaskId}
                onTaskStarted={setSelectedTaskId}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
