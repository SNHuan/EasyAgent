import { Suspense, useState } from "react"

import { DashboardShell } from "./DashboardShell"
import { dashboardRoutes, findDashboardRoute, type DashboardRouteId } from "./navigation"

export function DashboardApp() {
  const [activeRouteId, setActiveRouteId] = useState<DashboardRouteId>("runs")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const activeRoute = findDashboardRoute(activeRouteId)
  const ActivePage = activeRoute.page

  return (
    <DashboardShell
      routes={dashboardRoutes}
      activeRouteId={activeRoute.id}
      sidebarCollapsed={sidebarCollapsed}
      onRouteChange={setActiveRouteId}
      onSidebarCollapsedChange={setSidebarCollapsed}
    >
      <Suspense fallback={null}>
        <ActivePage />
      </Suspense>
    </DashboardShell>
  )
}
