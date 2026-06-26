import type { ReactNode } from "react"
import { PanelLeftClose, PanelLeftOpen, Sparkles } from "lucide-react"

import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { DashboardRoute, DashboardRouteId } from "./navigation"

type DashboardShellProps = {
  routes: DashboardRoute[]
  activeRouteId: DashboardRouteId
  sidebarCollapsed: boolean
  onRouteChange: (routeId: DashboardRouteId) => void
  onSidebarCollapsedChange: (collapsed: boolean) => void
  children: ReactNode
}

export function DashboardShell({
  routes,
  activeRouteId,
  sidebarCollapsed,
  onRouteChange,
  onSidebarCollapsedChange,
  children,
}: DashboardShellProps) {
  const routeGroups = groupRoutes(routes)

  return (
    <div className="dashboard-shell h-screen min-w-[1440px] overflow-hidden text-foreground">
      <div
        className={cn(
          "grid h-screen min-h-0 transition-[grid-template-columns]",
          sidebarCollapsed ? "grid-cols-[72px_minmax(0,1fr)]" : "grid-cols-[246px_minmax(0,1fr)]",
        )}
      >
        <aside className="sidebar-surface min-h-0 border-r">
          <div className="flex h-full min-h-0 flex-col p-3">
            <div
              className={cn(
                "flex shrink-0 items-center py-3",
                sidebarCollapsed ? "justify-center px-0" : "gap-2 px-2",
              )}
            >
              {sidebarCollapsed ? (
                <button
                  className="brand-mark group flex size-8 shrink-0 items-center justify-center rounded-md transition"
                  type="button"
                  aria-label="Expand navigation"
                  title="Expand navigation"
                  onClick={() => onSidebarCollapsedChange(false)}
                >
                  <Sparkles className="group-hover:hidden" data-icon="inline-start" />
                  <PanelLeftOpen className="hidden group-hover:block" data-icon="inline-start" />
                </button>
              ) : (
                <>
                  <div className="brand-mark flex size-8 shrink-0 items-center justify-center rounded-md">
                    <Sparkles data-icon="inline-start" />
                  </div>
                  <span className="min-w-0 flex-1 text-xl font-semibold tracking-tight">EasyAgent</span>
                  <button
                    className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted/70 hover:text-foreground"
                    type="button"
                    aria-label="Collapse navigation"
                    onClick={() => onSidebarCollapsedChange(true)}
                  >
                    <PanelLeftClose data-icon="inline-start" />
                  </button>
                </>
              )}
            </div>

            <ScrollArea className={cn("mt-3 min-h-0 flex-1", sidebarCollapsed ? "pr-0" : "pr-1")}>
              <div className="flex flex-col gap-5">
                {routeGroups.map((group) => (
                  <div key={group.title} className="flex flex-col gap-1">
                    {!sidebarCollapsed && (
                      <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {group.title}
                      </div>
                    )}
                    {group.routes.map((route) => {
                      const Icon = route.icon
                      const active = route.id === activeRouteId
                      return (
                        <button
                          key={route.id}
                          className={cn(
                            "flex h-9 items-center rounded-md text-sm transition",
                            sidebarCollapsed ? "justify-center px-0" : "gap-2 px-2",
                            active
                              ? "nav-active font-medium text-foreground"
                              : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                          )}
                          type="button"
                          title={sidebarCollapsed ? route.label : undefined}
                          onClick={() => onRouteChange(route.id)}
                        >
                          <Icon data-icon="inline-start" />
                          {!sidebarCollapsed && route.label}
                        </button>
                      )
                    })}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </aside>

        {children}
      </div>
    </div>
  )
}

function groupRoutes(routes: DashboardRoute[]): Array<{ title: string; routes: DashboardRoute[] }> {
  return routes.reduce<Array<{ title: string; routes: DashboardRoute[] }>>((groups, route) => {
    const group = groups.find((candidate) => candidate.title === route.group)
    if (group) {
      group.routes.push(route)
    } else {
      groups.push({ title: route.group, routes: [route] })
    }
    return groups
  }, [])
}
