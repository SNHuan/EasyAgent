import { lazy, type ReactElement, type LazyExoticComponent } from "react"
import type { LucideIcon } from "lucide-react"
import { Layers3 } from "lucide-react"

const RunsPage = lazy(() => import("@/pages/runs"))

export type DashboardRouteId = "runs"

export type DashboardRoute = {
  id: DashboardRouteId
  label: string
  group: string
  icon: LucideIcon
  page: LazyExoticComponent<() => ReactElement>
}

export const dashboardRoutes = [
  {
    id: "runs",
    label: "Runs",
    group: "Observability",
    icon: Layers3,
    page: RunsPage,
  },
] satisfies DashboardRoute[]

export function findDashboardRoute(routeId: DashboardRouteId): DashboardRoute {
  return dashboardRoutes.find((route) => route.id === routeId) ?? dashboardRoutes[0]
}
