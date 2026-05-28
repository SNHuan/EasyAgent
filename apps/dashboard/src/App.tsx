import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react"
import hljs from "highlight.js/lib/core"
import json from "highlight.js/lib/languages/json"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  CheckCircle2,
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  Database,
  ListFilter,
  Layers3,
  MessagesSquare,
  PlayCircle,
  Sparkles,
  Wrench,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import traceFixture from "@/data/traces.json"
import { cn } from "@/lib/utils"

hljs.registerLanguage("json", json)

type SessionStatus = "completed" | "failed" | "running"
type StatusFilter = "all" | SessionStatus
type TimeFilter = "all" | "15m" | "1h"

type RawTokenUsage = {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

type RawTraceEvent = {
  event_id: string
  session_id: string
  event_type: string
  timestamp: string
  agent_id: string
  payload: Record<string, unknown>
}

type RawTraceSession = {
  session_id: string
  agent_id: string
  status: string
  started_at: string
  ended_at: string | null
  event_count: number
  token_usage: RawTokenUsage
  metadata: Record<string, unknown>
  event_counts: Record<string, number>
  events: RawTraceEvent[]
}

type TraceApiResponse = {
  db_path?: string
  connected?: boolean
  sessions?: RawTraceSession[]
}

type TraceEvent = {
  id: string
  type: string
  at: string
  summary: string
  latency: string
  inTokens: number
  outTokens: number
  payload: Record<string, unknown>
}

type TraceSession = {
  id: string
  title: string
  status: SessionStatus
  model: string
  user: string
  startedAt: string
  duration: string
  latency: string
  startedAgo: string
  version: string
  traceId: string
  promptTokens: number
  completionTokens: number
  totalTokens: number
  events: TraceEvent[]
  raw: RawTraceSession
}

type MessageRole = "system" | "user" | "assistant" | "tool"

type TraceMessage = {
  id: string
  role: MessageRole
  content: string
  source: string
  at: string
  eventId: string
  tokens?: string
}

type UsageBar = {
  key: string
  hour: string
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

type EventBreakdownItem = {
  type: string
  count: number
  percentage: number
  color: string
}

const rawSessions = traceFixture.sessions as unknown as RawTraceSession[]
const emptySession = toTraceSession({
  session_id: "no_sessions",
  agent_id: "",
  status: "running",
  started_at: "1970-01-01T00:00:00",
  ended_at: null,
  event_count: 0,
  token_usage: {},
  metadata: {},
  event_counts: {},
  events: [],
})
const MIN_SESSIONS_WIDTH = 300
const MAX_SESSIONS_WIDTH = 620
const MIN_DETAILS_WIDTH = 520
const MIN_INSPECTOR_WIDTH = 320
const MAX_INSPECTOR_WIDTH = 680

const sidebarGroups = [
  {
    title: "Observability",
    items: [
      [Layers3, "Sessions"],
    ],
  },
] as const

const statusClass: Record<SessionStatus, string> = {
  completed: "status-completed",
  failed: "status-failed",
  running: "status-running",
}

const eventColors = [
  "oklch(0.64 0.18 247)",
  "oklch(0.66 0.16 150)",
  "oklch(0.72 0.13 75)",
  "oklch(0.62 0.2 25)",
  "oklch(0.52 0.13 290)",
  "oklch(0.58 0.12 200)",
]

function toTraceSession(session: RawTraceSession): TraceSession {
  const started = new Date(session.started_at)
  const ended = session.ended_at ? new Date(session.ended_at) : null
  const model = firstString(
    session.events.map((event) => event.payload.model),
    "unknown",
  )
  const tokenUsage = session.token_usage ?? {}
  const events = session.events.map((event, index) =>
    toTraceEvent(event, session.started_at, session.events[index - 1]?.timestamp),
  )

  return {
    id: formatSessionId(session.session_id),
    title: inferSessionTitle(session),
    status: normalizeStatus(session.status),
    model,
    user: formatActor(session.agent_id),
    startedAt: started.toLocaleString([], {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }),
    duration: formatDuration(started, ended),
    latency: formatDuration(started, ended),
    startedAgo: formatRelativeTime(started),
    version: String(session.metadata.version ?? "local"),
    traceId: `trace_${session.session_id.slice(0, 12)}`,
    promptTokens: tokenUsage.prompt_tokens ?? 0,
    completionTokens: tokenUsage.completion_tokens ?? 0,
    totalTokens: tokenUsage.total_tokens ?? 0,
    events,
    raw: session,
  }
}

function toTraceEvent(event: RawTraceEvent, sessionStartedAt: string, previousTimestamp?: string): TraceEvent {
  const timestamp = new Date(event.timestamp)
  const previous = previousTimestamp ? new Date(previousTimestamp) : new Date(sessionStartedAt)
  const usage = isRecord(event.payload.usage) ? event.payload.usage : {}
  const promptTokens = numberValue(usage.prompt_tokens) || numberValue(usage.input_tokens)
  const completionTokens = numberValue(usage.completion_tokens) || numberValue(usage.output_tokens)

  return {
    id: event.event_id,
    type: event.event_type,
    at: formatOffset(new Date(sessionStartedAt), timestamp),
    summary: eventSummaryText(event),
    latency: formatMilliseconds(Math.max(0, timestamp.getTime() - previous.getTime())),
    inTokens: promptTokens,
    outTokens: completionTokens,
    payload: {
      event_type: event.event_type,
      timestamp: event.timestamp,
      ...event.payload,
    },
  }
}

function normalizeStatus(status: string): SessionStatus {
  if (status === "completed" || status === "failed" || status === "running") return status
  return "running"
}

function firstString(values: unknown[], fallback: string): string {
  return values.find((value): value is string => typeof value === "string" && value.length > 0) ?? fallback
}

function inferSessionTitle(session: RawTraceSession): string {
  const failed = session.events.find((event) => event.event_type === "AgentFailedEvent")
  const finished = session.events.find((event) => event.event_type === "AgentFinishedEvent")
  const firstTool = session.events.find((event) => event.event_type === "ToolCalledEvent")
  const firstResponse = session.events.find((event) => event.event_type === "LLMRespondedEvent")

  if (failed) return String(failed.payload.error ?? "Provider channel unavailable")
  if (firstTool) return String(firstTool.payload.tool_name ?? "Tool call session")
  if (finished) return truncate(String(finished.payload.output ?? "Completed session"), 58)
  if (firstResponse) return truncate(formatAssistantContent(firstResponse.payload), 58)
  return "Agent session"
}

function eventSummaryText(event: RawTraceEvent): string {
  switch (event.event_type) {
    case "AgentStartedEvent":
      return "Session created and memory initialized."
    case "AgentFinishedEvent":
      return truncate(String(event.payload.output ?? "Success"), 82)
    case "AgentFailedEvent":
      return truncate(String(event.payload.error ?? "Session failed"), 82)
    case "LLMCalledEvent":
      return `${String(event.payload.model ?? "unknown model")} · ${String(event.payload.message_count ?? 0)} messages`
    case "LLMRespondedEvent":
      return truncate(formatAssistantContent(event.payload), 82)
    case "ToolCalledEvent":
      return `${String(event.payload.tool_name ?? "tool")} ${formatArguments(event.payload.arguments)}`
    case "ToolResultEvent":
      return truncate(String(event.payload.result ?? "Tool result received."), 82)
    default:
      return "Persisted event payload."
  }
}

function buildMessageView(session: TraceSession): TraceMessage[] {
  const finalEvent =
    session.raw.events.findLast((event) => event.event_type === "AgentFinishedEvent") ??
    session.raw.events.findLast((event) => event.event_type === "AgentFailedEvent")
  const rawMessages = finalEvent && Array.isArray(finalEvent.payload.messages)
    ? finalEvent.payload.messages
    : []

  if (rawMessages.length > 0) {
    const messageEvents = session.raw.events.filter((event) =>
      event.event_type === "LLMRespondedEvent" || event.event_type === "ToolResultEvent",
    )
    let eventIndex = 0
    return rawMessages.flatMap((message, index) => {
      if (!isRecord(message)) return []
      const role = normalizeRole(message.role)
      const relatedEvent = role === "assistant" || role === "tool"
        ? messageEvents[eventIndex++]
        : undefined
      const source = role === "assistant" && Array.isArray(message.tool_calls)
        ? `assistant · ${message.tool_calls.length} tool call${message.tool_calls.length === 1 ? "" : "s"}`
        : role === "tool" && typeof message.tool_call_id === "string"
          ? `tool result · ${message.tool_call_id}`
          : "session memory"
      return [{
        id: `${finalEvent?.event_id ?? session.id}-message-${index}`,
        role,
        content: role === "assistant" ? formatAssistantContent(message) : formatMessageContent(message.content),
        source,
        at: String(index + 1).padStart(2, "0"),
        eventId: relatedEvent?.event_id ?? finalEvent?.event_id ?? "",
      }]
    })
  }

  return session.raw.events.flatMap<TraceMessage>((event) => {
    if (event.event_type === "LLMRespondedEvent") {
      return [{
        id: `${event.event_id}-assistant`,
        role: "assistant" as const,
        content: formatAssistantContent(event.payload),
        source: String(event.payload.model ?? "LLM response"),
        at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
        eventId: event.event_id,
      }]
    }
    if (event.event_type === "ToolResultEvent") {
      return [{
        id: `${event.event_id}-tool`,
        role: "tool" as const,
        content: String(event.payload.result ?? ""),
        source: String(event.payload.tool_name ?? "tool result"),
        at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
        eventId: event.event_id,
      }]
    }
    return []
  })
}

function buildSessionUsageBars(session: TraceSession): UsageBar[] {
  const eventTimes = session.events
    .map((event) => event.payload.timestamp)
    .filter((value): value is string => typeof value === "string")
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite)
  const anchorTime = eventTimes.length > 0
    ? Math.max(...eventTimes)
    : new Date(session.raw.ended_at ?? session.raw.started_at).getTime()
  const anchor = new Date(anchorTime)
  anchor.setMinutes(0, 0, 0)

  const buckets = new Map<string, UsageBar>()

  for (let index = 11; index >= 0; index -= 1) {
    const hourStart = new Date(anchor)
    hourStart.setHours(anchor.getHours() - index)
    const key = hourStart.toISOString()
    buckets.set(key, {
      key,
      hour: hourStart.toLocaleTimeString([], {
        hour: "2-digit",
        hour12: false,
      }),
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    })
  }

  for (const event of session.events) {
    if (event.inTokens === 0 && event.outTokens === 0) continue

    const timestamp = typeof event.payload.timestamp === "string"
      ? new Date(event.payload.timestamp)
      : new Date(session.raw.started_at)
    timestamp.setMinutes(0, 0, 0)
    const bucket = buckets.get(timestamp.toISOString())
    if (!bucket) continue

    bucket.promptTokens += event.inTokens
    bucket.completionTokens += event.outTokens
    bucket.totalTokens += event.inTokens + event.outTokens
  }

  return Array.from(buckets.values())
}

function buildEventBreakdown(session: TraceSession): EventBreakdownItem[] {
  const total = Math.max(1, session.events.length)
  const counts = new Map<string, number>()

  for (const event of session.events) {
    counts.set(event.type, (counts.get(event.type) ?? 0) + 1)
  }

  return Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1])
    .map(([type, count], index) => ({
      type,
      count,
      percentage: (count / total) * 100,
      color: eventColors[index % eventColors.length],
    }))
}

function pieBackground(items: EventBreakdownItem[]): string {
  if (items.length === 0) return "conic-gradient(oklch(0.93 0 0) 0% 100%)"

  let cursor = 0
  const segments = items.map((item) => {
    const start = cursor
    cursor += item.percentage
    return `${item.color} ${start}% ${cursor}%`
  })

  return `conic-gradient(${segments.join(", ")})`
}

function highlightJson(value: unknown): string {
  return hljs.highlight(JSON.stringify(value, null, 2), { language: "json" }).value
}

function normalizeRole(value: unknown): MessageRole {
  return value === "system" || value === "user" || value === "assistant" || value === "tool"
    ? value
    : "user"
}

function formatMessageContent(value: unknown): string {
  if (typeof value === "string") return value
  if (Array.isArray(value)) {
    return value
      .map((item) => (isRecord(item) && "text" in item ? String(item.text) : JSON.stringify(item)))
      .join("\n")
  }
  if (value == null) return ""
  return JSON.stringify(value, null, 2)
}

function formatAssistantContent(message: Record<string, unknown>): string {
  const content = formatMessageContent(message.content).trim()
  if (content) return content

  const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : []
  if (toolCalls.length === 0) return "Assistant responded with an empty message."

  return toolCalls
    .map((toolCall, index) => {
      if (!isRecord(toolCall)) return `Tool call ${index + 1}`
      const name = toolCallName(toolCall)
      const args = toolCallArguments(toolCall)
      return `${name}${args ? `\n${args}` : ""}`
    })
    .join("\n\n")
}

function toolCallName(toolCall: Record<string, unknown>): string {
  if (typeof toolCall.name === "string") return toolCall.name
  if (isRecord(toolCall.function) && typeof toolCall.function.name === "string") {
    return toolCall.function.name
  }
  return "tool"
}

function toolCallArguments(toolCall: Record<string, unknown>): string {
  const rawArguments = isRecord(toolCall.function) ? toolCall.function.arguments : toolCall.arguments
  if (typeof rawArguments === "string") {
    try {
      return JSON.stringify(JSON.parse(rawArguments), null, 2)
    } catch {
      return rawArguments
    }
  }
  if (isRecord(rawArguments)) return JSON.stringify(rawArguments, null, 2)
  return ""
}

function formatArguments(value: unknown): string {
  if (!isRecord(value)) return ""
  const keys = Object.keys(value)
  if (keys.length === 0) return ""
  return `(${keys.map((key) => `${key}: ${String(value[key])}`).join(", ")})`
}

function formatSessionId(id: string): string {
  return `sess_${id.slice(0, 8)}`
}

function formatActor(id: string): string {
  return `agent_${id.slice(0, 6)}`
}

function formatDuration(started: Date, ended: Date | null): string {
  if (!ended) return "running"
  return formatMilliseconds(Math.max(0, ended.getTime() - started.getTime()))
}

function formatOffset(started: Date, timestamp: Date): string {
  const totalMs = Math.max(0, timestamp.getTime() - started.getTime())
  const hours = Math.floor(totalMs / 3_600_000)
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000)
  const seconds = Math.floor((totalMs % 60_000) / 1_000)
  const ms = totalMs % 1_000
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${String(ms).padStart(3, "0")}`
}

function formatMilliseconds(ms: number): string {
  if (ms < 1_000) return `${Math.max(1, Math.round(ms))} ms`
  return `${(ms / 1_000).toFixed(2)}s`
}

function formatRelativeTime(date: Date): string {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1_000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : 0
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value
}

function pad(value: number): string {
  return String(value).padStart(2, "0")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function App() {
  const [rawSessionData, setRawSessionData] = useState<RawTraceSession[]>(rawSessions)
  const [filterNow] = useState(() => Date.now())
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [modelFilter, setModelFilter] = useState("all")
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all")
  const [selectedId, setSelectedId] = useState("")
  const [activeEventId, setActiveEventId] = useState("")
  const [activeMessageId, setActiveMessageId] = useState("")
  const [dbMenuOpen, setDbMenuOpen] = useState(false)
  const [dbPath, setDbPath] = useState("local fixture")
  const [dbConnected, setDbConnected] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const dbFileInputRef = useRef<HTMLInputElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const [columns, setColumns] = useState({ sessions: 420, inspector: 430 })
  const sessionRows = useMemo(() => rawSessionData.map(toTraceSession), [rawSessionData])
  const availableModels = useMemo(() => Array.from(new Set(sessionRows.map((session) => session.model))), [sessionRows])

  useEffect(() => {
    const controller = new AbortController()

    async function loadTraces() {
      try {
        const response = await fetch("/api/traces", { signal: controller.signal })
        if (!response.ok) return
        const payload = await response.json() as TraceApiResponse
        setRawSessionData(payload.sessions ?? [])
        setDbPath(payload.db_path ?? "unknown")
        setDbConnected(Boolean(payload.connected))
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return
      }
    }

    void loadTraces()
    return () => controller.abort()
  }, [])

  const filteredSessions = useMemo(() => {
    return sessionRows.filter((session) => {
      if (statusFilter !== "all" && session.status !== statusFilter) return false
      if (modelFilter !== "all" && session.model !== modelFilter) return false
      if (timeFilter !== "all") {
        const minutes = timeFilter === "15m" ? 15 : 60
        if (filterNow - new Date(session.raw.started_at).getTime() > minutes * 60_000) return false
      }
      return true
    })
  }, [filterNow, modelFilter, sessionRows, statusFilter, timeFilter])

  const selectedSession =
    sessionRows.find((session) => session.id === selectedId) ?? sessionRows[0] ?? emptySession
  const activeEvent =
    selectedSession.events.find((event) => event.id === activeEventId) ??
    selectedSession.events[0]
  const usageBars = buildSessionUsageBars(selectedSession)
  const maxHourlyTokens = Math.max(1, ...usageBars.map((bucket) => bucket.totalTokens))
  const eventBreakdown = buildEventBreakdown(selectedSession)
  const highlightedPayload = highlightJson(activeEvent?.payload ?? {})

  const messages = buildMessageView(selectedSession)
  const selectedMessageId = activeMessageId || messages[0]?.id || ""

  function startColumnResize(edge: "sessions" | "inspector", event: PointerEvent<HTMLButtonElement>) {
    const section = sectionRef.current
    if (!section) return
    event.preventDefault()
    const rect = section.getBoundingClientRect()
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"

    const resize = (pointerEvent: globalThis.PointerEvent) => {
      setColumns((current) => {
        const availableWidth = rect.width - 12
        if (edge === "sessions") {
          const maxSessions = Math.min(
            MAX_SESSIONS_WIDTH,
            availableWidth - current.inspector - MIN_DETAILS_WIDTH,
          )
          return {
            ...current,
            sessions: clamp(pointerEvent.clientX - rect.left, MIN_SESSIONS_WIDTH, maxSessions),
          }
        }

        const maxInspector = Math.min(
          MAX_INSPECTOR_WIDTH,
          availableWidth - current.sessions - MIN_DETAILS_WIDTH,
        )
        return {
          ...current,
          inspector: clamp(rect.right - pointerEvent.clientX, MIN_INSPECTOR_WIDTH, maxInspector),
        }
      })
    }

    const stopResize = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener("pointermove", resize)
      window.removeEventListener("pointerup", stopResize)
    }

    window.addEventListener("pointermove", resize)
    window.addEventListener("pointerup", stopResize)
  }

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
            <div className={cn("flex shrink-0 items-center py-3", sidebarCollapsed ? "justify-center px-0" : "gap-2 px-2")}>
              {sidebarCollapsed ? (
                <button
                  className="brand-mark group flex size-8 shrink-0 items-center justify-center rounded-md transition"
                  type="button"
                  aria-label="Expand navigation"
                  title="Expand navigation"
                  onClick={() => setSidebarCollapsed(false)}
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
                    onClick={() => setSidebarCollapsed(true)}
                  >
                    <PanelLeftClose data-icon="inline-start" />
                  </button>
                </>
              )}
            </div>

            <ScrollArea className={cn("mt-3 min-h-0 flex-1", sidebarCollapsed ? "pr-0" : "pr-1")}>
              <div className="flex flex-col gap-5">
                {sidebarGroups.map((group) => (
                  <div key={group.title} className="flex flex-col gap-1">
                    {!sidebarCollapsed && (
                      <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {group.title}
                      </div>
                    )}
                    {group.items.map(([Icon, label]) => (
                      <button
                        key={label}
                        className={cn(
                          "flex h-9 items-center rounded-md text-sm transition",
                          sidebarCollapsed ? "justify-center px-0" : "gap-2 px-2",
                          label === "Sessions"
                            ? "nav-active font-medium text-foreground"
                            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                        )}
                        type="button"
                        title={sidebarCollapsed ? label : undefined}
                      >
                        <Icon data-icon="inline-start" />
                        {!sidebarCollapsed && label}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <header className="header-surface flex h-[72px] shrink-0 items-center justify-between border-b px-7">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">Observability</span>
              <ChevronDown className="size-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">Sessions</span>
            </div>
            <div className="relative">
              <button
                className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition hover:bg-muted/60"
                type="button"
                onClick={() => setDbMenuOpen((open) => !open)}
              >
                <span className={cn("inline-block size-2 rounded-full", dbConnected ? "bg-emerald-500" : "bg-zinc-400")} />
                Trace DB
                <span className={cn("text-xs", dbConnected ? "text-emerald-600" : "text-muted-foreground")}>
                  {dbConnected ? "Connected" : "Fixture"}
                </span>
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </button>

              {dbMenuOpen && (
                <div className="absolute right-0 top-11 z-30 w-[360px] rounded-lg border bg-background p-3 shadow-lg">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Database data-icon="inline-start" />
                    Trace database
                  </div>
                  <div className="mt-3 rounded-md border bg-muted/30 p-2">
                    <div className="text-xs text-muted-foreground">Current file</div>
                    <div className="mt-1 break-all font-mono text-xs">{dbPath}</div>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="text-xs text-muted-foreground">
                      Switch the dashboard source.
                    </span>
                    <button
                      className="h-8 rounded-md border px-3 text-xs font-medium hover:bg-muted/60"
                      type="button"
                      onClick={() => dbFileInputRef.current?.click()}
                    >
                      Choose DB
                    </button>
                  </div>
                  <input
                    ref={dbFileInputRef}
                    className="hidden"
                    type="file"
                    accept=".db,.sqlite,.sqlite3"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (!file) return
                      setDbPath(file.name)
                    }}
                  />
                </div>
              )}
            </div>
          </header>

          <section
            ref={sectionRef}
            className="grid min-h-0 flex-1 overflow-hidden"
            style={{
              gridTemplateColumns: `${columns.sessions}px 6px minmax(${MIN_DETAILS_WIDTH}px, 1fr) 6px ${columns.inspector}px`,
            }}
          >
            <div className="min-h-0">
              <Card className="panel-card flex h-full min-h-0 rounded-none border-0 shadow-none ring-0">
                <CardHeader className="shrink-0 border-b px-4 py-4">
                  <CardTitle className="text-xl">Sessions</CardTitle>
                  <CardAction className="relative flex items-center gap-2">
                    <button
                      className={cn(
                        "flex h-8 items-center gap-2 rounded-md border px-2.5 text-xs transition hover:bg-muted/70",
                        (statusFilter !== "all" || modelFilter !== "all" || timeFilter !== "all") &&
                          "border-foreground text-foreground",
                      )}
                      type="button"
                      onClick={() => setFiltersOpen((open) => !open)}
                    >
                      <ListFilter data-icon="inline-start" />
                      Filter
                      <Badge variant="secondary">{filteredSessions.length}</Badge>
                    </button>

                    {filtersOpen && (
                      <div className="absolute right-0 top-10 z-30 w-[300px] space-y-3 rounded-lg border bg-background p-3 shadow-lg">
                        <FilterSelect
                          label="Status"
                          value={statusFilter}
                          options={[
                            ["all", "All statuses"],
                            ["completed", "Completed"],
                            ["running", "Running"],
                            ["failed", "Failed"],
                          ]}
                          onChange={(value) => setStatusFilter(value as StatusFilter)}
                        />
                        <FilterSelect
                          label="Model"
                          value={modelFilter}
                          options={[
                            ["all", "All models"],
                            ...availableModels.map((model) => [model, model] as [string, string]),
                          ]}
                          onChange={setModelFilter}
                        />
                        <FilterSelect
                          label="Started"
                          value={timeFilter}
                          options={[
                            ["all", "Any time"],
                            ["15m", "Last 15 minutes"],
                            ["1h", "Last hour"],
                          ]}
                          onChange={(value) => setTimeFilter(value as TimeFilter)}
                        />
                        <button
                          className="h-8 w-full rounded-md border text-xs hover:bg-muted/70"
                          type="button"
                          onClick={() => {
                            setStatusFilter("all")
                            setModelFilter("all")
                            setTimeFilter("all")
                          }}
                        >
                          Reset filters
                        </button>
                      </div>
                    )}
                  </CardAction>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-hidden px-0 py-0">
                  <ScrollArea className="h-full">
                    <Table className="text-[13px]">
                      <TableHeader className="sticky top-0 z-10 bg-background">
                        <TableRow>
                          <TableHead className="pl-4">Session ID</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Latency</TableHead>
                          <TableHead className="pr-4 text-right">Started</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredSessions.map((session) => (
                          <TableRow
                            key={session.id}
                            className={cn(
                              "cursor-pointer",
                              selectedSession.id === session.id && "selected-row",
                            )}
                            onClick={() => {
                              setSelectedId(session.id)
                              setActiveEventId(session.events[0]?.id ?? "")
                              setActiveMessageId("")
                            }}
                          >
                            <TableCell className="pl-4 font-mono text-xs">{session.id}</TableCell>
                            <TableCell>
                              <Badge className={statusClass[session.status]}>{session.status}</Badge>
                            </TableCell>
                            <TableCell>{session.latency}</TableCell>
                            <TableCell className="pr-4 text-right">{session.startedAgo}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                </CardContent>
              </Card>
            </div>

            <ResizeHandle label="Resize sessions column" onPointerDown={(event) => startColumnResize("sessions", event)} />

            <div className="min-h-0">
              <Card className="panel-card flex h-full min-h-0 rounded-none border-0 shadow-none ring-0">
                <CardHeader className="shrink-0 border-b px-5 py-4">
                  <div className="flex items-center gap-3">
                    <CardTitle className="font-mono text-xl">{selectedSession.id}</CardTitle>
                    <Badge variant="outline" className={statusClass[selectedSession.status]}>
                      {selectedSession.status}
                    </Badge>
                  </div>
                  <div className="mt-4 grid grid-cols-6 gap-4 text-sm">
                    <MetaCell label="Started" value={selectedSession.startedAt} />
                    <MetaCell label="Duration" value={selectedSession.duration} />
                    <MetaCell label="Model" value={selectedSession.model} />
                    <MetaCell label="User" value={selectedSession.user} />
                    <MetaCell label="Version" value={selectedSession.version} />
                    <MetaCell label="Trace ID" value={selectedSession.traceId} />
                  </div>
                </CardHeader>
                <CardContent className="flex min-h-0 flex-1 px-5 py-4">
                  <Tabs defaultValue="timeline" className="flex min-h-0 flex-1 flex-col gap-4">
                    <TabsList>
                      <TabsTrigger value="timeline">Timeline</TabsTrigger>
                      <TabsTrigger value="events">
                        Events {selectedSession.events.length}
                      </TabsTrigger>
                      <TabsTrigger value="messages">
                        Messages {messages.length}
                      </TabsTrigger>
                    </TabsList>

                    <TabsContent value="timeline" className="min-h-0 flex-1">
                      <ScrollArea className="h-full pr-2">
                        <div className="relative flex flex-col">
                          {selectedSession.events.map((event, index) => (
                            <TimelineEvent
                              key={event.id}
                              event={event}
                              isFirst={index === 0}
                              isLast={index === selectedSession.events.length - 1}
                              selected={event.id === activeEventId}
                              onClick={() => {
                                setActiveEventId(event.id)
                                setActiveMessageId("")
                              }}
                            />
                          ))}
                        </div>
                      </ScrollArea>
                    </TabsContent>
                    <TabsContent value="events" className="min-h-0 flex-1">
                      <EventBreakdownPanel
                        items={eventBreakdown}
                        total={selectedSession.events.length}
                        onSelect={(eventType) => {
                          const matchingEvent = selectedSession.events.find((event) => event.type === eventType)
                          if (matchingEvent) {
                            setActiveEventId(matchingEvent.id)
                            setActiveMessageId("")
                          }
                        }}
                      />
                    </TabsContent>
                    <TabsContent value="messages" className="min-h-0 flex-1">
                      <ScrollArea className="h-full pr-2">
                        <div className="flex flex-col gap-3 pb-2">
                          {messages.map((message) => (
                            <MessageRow
                              key={message.id}
                              message={message}
                              selected={message.id === selectedMessageId}
                              onClick={() => {
                                setActiveMessageId(message.id)
                                if (message.eventId) setActiveEventId(message.eventId)
                              }}
                            />
                          ))}
                        </div>
                      </ScrollArea>
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </div>

            <ResizeHandle label="Resize inspector column" onPointerDown={(event) => startColumnResize("inspector", event)} />

            <div className="min-h-0 overflow-hidden bg-background p-4">
              <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4">
                <Card size="sm" className="rounded-lg border shadow-none ring-0">
                  <CardHeader>
                    <CardTitle>Token Usage</CardTitle>
                    <CardDescription>
                      <span className="text-2xl font-semibold text-foreground">
                        {selectedSession.totalTokens.toLocaleString()}
                      </span>{" "}
                      Total Tokens
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="mb-4 flex gap-4 text-sm">
                      <span className="text-blue-600">
                        ↓ {selectedSession.promptTokens.toLocaleString()} input
                      </span>
                      <span className="text-emerald-600">
                        ↑ {selectedSession.completionTokens.toLocaleString()} output
                      </span>
                    </div>
                    <div className="grid h-32 grid-cols-12 items-end gap-1.5 pt-8">
                      {usageBars.map((bucket) => {
                        const promptHeight = (bucket.promptTokens / maxHourlyTokens) * 100
                        const completionHeight = (bucket.completionTokens / maxHourlyTokens) * 100
                        return (
                          <div
                            key={bucket.key}
                            className="usage-bar relative h-full rounded-sm bg-muted/50"
                            tabIndex={0}
                            aria-label={`${bucket.hour}, ${bucket.totalTokens} total tokens`}
                          >
                            <div className="usage-tooltip pointer-events-none absolute left-1/2 bottom-full z-20 mb-2 w-max -translate-x-1/2 rounded-md border bg-background px-2.5 py-2 text-left text-[11px] shadow-lg">
                              <div className="mb-1 font-mono font-medium text-foreground">{bucket.hour}:00</div>
                              <div className="text-blue-600">Input {bucket.promptTokens.toLocaleString()}</div>
                              <div className="text-emerald-600">
                                Output {bucket.completionTokens.toLocaleString()}
                              </div>
                              <div className="mt-1 border-t pt-1 font-medium text-foreground">
                                Total {bucket.totalTokens.toLocaleString()}
                              </div>
                            </div>
                            <div
                              className="usage-bar-prompt absolute bottom-0 w-full rounded-b-sm bg-blue-500/80"
                              style={{ height: `${promptHeight}%` }}
                            />
                            <div
                              className="usage-bar-completion absolute w-full rounded-t-sm bg-emerald-500/75"
                              style={{
                                bottom: `${promptHeight}%`,
                                height: `${completionHeight}%`,
                              }}
                            />
                          </div>
                        )
                      })}
                    </div>
                    <div className="mt-2 grid grid-cols-12 gap-1.5 text-center text-[10px] text-muted-foreground">
                      {usageBars.map((bucket) => (
                        <span key={bucket.key}>{bucket.hour}</span>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                <Card size="sm" className="flex min-h-0 rounded-lg border shadow-none ring-0">
                  <CardHeader>
                    <CardTitle>Event Payload</CardTitle>
                    <CardAction>
                      <Badge variant="outline">{activeEvent?.type ?? "-"}</Badge>
                    </CardAction>
                  </CardHeader>
                  <CardContent className="flex min-h-0 flex-1 flex-col">
                    <pre className="payload-box min-h-0 flex-1 overflow-auto rounded-md border p-3 font-mono text-xs leading-6">
                      <code
                        className="hljs language-json"
                        dangerouslySetInnerHTML={{ __html: highlightedPayload }}
                      />
                    </pre>
                  </CardContent>
                </Card>
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-sm">{value}</div>
    </div>
  )
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (value: string) => void
}) {
  return (
    <label className="block space-y-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <select
        className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none transition hover:bg-muted/40 focus:border-blue-400 focus:ring-2 focus:ring-blue-500/15"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  )
}

function EventBreakdownPanel({
  items,
  total,
  onSelect,
}: {
  items: EventBreakdownItem[]
  total: number
  onSelect: (eventType: string) => void
}) {
  const topEvent = items[0]

  return (
    <div className="event-breakdown flex h-full min-h-0 flex-col gap-5 rounded-lg border p-5">
      <div className="grid shrink-0 grid-cols-[180px_minmax(0,1fr)] items-center gap-6">
        <div className="event-pie" style={{ background: pieBackground(items) }}>
          <div className="event-pie-center text-center">
            <div className="text-3xl font-semibold leading-none">{total}</div>
            <div className="mt-1 text-xs text-muted-foreground">events</div>
          </div>
        </div>

        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Event Mix</div>
          <div className="mt-2 text-2xl font-semibold">Current session</div>
          <div className="mt-2 text-sm text-muted-foreground">
            {topEvent ? `${topEvent.type} is the most frequent event type.` : "No events captured."}
          </div>
          {topEvent && (
            <div className="mt-4 grid max-w-md grid-cols-3 gap-2">
              <div className="event-mini-stat">
                <div className="text-xs text-muted-foreground">Types</div>
                <div className="mt-1 text-lg font-semibold">{items.length}</div>
              </div>
              <div className="event-mini-stat">
                <div className="text-xs text-muted-foreground">Top Count</div>
                <div className="mt-1 text-lg font-semibold">{topEvent.count}</div>
              </div>
              <div className="event-mini-stat">
                <div className="text-xs text-muted-foreground">Top Share</div>
                <div className="mt-1 text-lg font-semibold">{topEvent.percentage.toFixed(1)}%</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1 pr-2">
        <div className="grid gap-2">
          {items.map((item) => (
            <button
              key={item.type}
              type="button"
              className="event-breakdown-row grid grid-cols-[minmax(0,1fr)_56px_56px] items-center gap-4 rounded-md border px-3 py-2.5 text-left transition"
              onClick={() => onSelect(item.type)}
            >
              <span className="min-w-0">
                <span className="mb-1.5 flex min-w-0 items-center gap-2">
                  <span className="event-dot" style={{ background: item.color }} />
                  <span className="truncate font-medium">{item.type}</span>
                </span>
                <span className="event-share-track">
                  <span
                    className="event-share-fill"
                    style={{ width: `${item.percentage}%`, background: item.color }}
                  />
                </span>
              </span>
              <span className="text-right font-mono text-sm">{item.count}</span>
              <span className="w-14 text-right text-xs text-muted-foreground">
                {item.percentage.toFixed(1)}%
              </span>
            </button>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}

function ResizeHandle({
  label,
  onPointerDown,
}: {
  label: string
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="resize-handle group relative min-h-0 cursor-col-resize border-x"
      onPointerDown={onPointerDown}
    >
      <span className="absolute left-1/2 top-1/2 h-12 w-px -translate-x-1/2 -translate-y-1/2 rounded-full bg-border transition group-hover:bg-blue-500" />
    </button>
  )
}

function TimelineEvent({
  event,
  isFirst,
  isLast,
  selected,
  onClick,
}: {
  event: TraceEvent
  isFirst: boolean
  isLast: boolean
  selected: boolean
  onClick: () => void
}) {
  const colorClass = event.type.includes("LLM")
    ? "event-llm"
    : event.type.includes("Tool")
      ? "event-tool"
      : event.type.includes("Finished")
        ? "event-finished"
        : "event-started"

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "timeline-row grid grid-cols-[112px_32px_1fr_auto] items-start gap-3 border-b px-0 py-4 text-left",
        selected && "selected-row",
      )}
    >
      <span className="font-mono text-sm text-muted-foreground">{event.at}</span>
      <span
        className={cn(
          "timeline-node relative z-10 flex size-8 items-center justify-center",
          !isFirst && "timeline-node-before",
          !isLast && "timeline-node-after",
        )}
      >
        <span className={cn("event-icon relative z-10 flex size-8 items-center justify-center rounded-full", colorClass)}>
        {event.type.includes("Tool") ? (
          <Wrench data-icon="inline-start" />
        ) : event.type.includes("LLM") ? (
          <MessagesSquare data-icon="inline-start" />
        ) : event.type.includes("Finished") ? (
          <CheckCircle2 data-icon="inline-start" />
        ) : (
          <PlayCircle data-icon="inline-start" />
        )}
        </span>
      </span>
      <div className="min-w-0">
        <div className="truncate font-medium">{event.type}</div>
        <div className="text-muted-foreground">{event.summary}</div>
      </div>
      <div className="min-w-24 text-right">
        <Badge variant="outline">{event.latency}</Badge>
        {(event.inTokens > 0 || event.outTokens > 0) && (
          <div className="mt-2 text-xs text-muted-foreground">
            ↓ {event.inTokens.toLocaleString()} / ↑ {event.outTokens.toLocaleString()}
          </div>
        )}
      </div>
    </button>
  )
}

function MessageRow({
  message,
  selected,
  onClick,
}: {
  message: TraceMessage
  selected: boolean
  onClick: () => void
}) {
  const isUser = message.role === "user"
  const isTool = message.role === "tool"

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "message-row flex w-full text-left",
        isUser ? "justify-end" : "justify-start",
        selected && "message-row-active",
      )}
    >
      <div
        className={cn(
          isTool ? "message-tool-card" : "message-bubble",
          isUser && "message-bubble-user",
          message.role === "assistant" && "message-bubble-agent",
          selected && "message-selected",
        )}
      >
        {isTool ? (
          <>
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="summary-tool flex size-7 shrink-0 items-center justify-center rounded-md border">
                  <Wrench data-icon="inline-start" />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">Tool result</div>
                  <div className="truncate text-xs text-muted-foreground">{message.source}</div>
                </div>
              </div>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">{message.at}</span>
            </div>
            <pre className="message-content mt-1.5 line-clamp-2 whitespace-pre-wrap font-sans text-xs leading-5">
              {message.content}
            </pre>
          </>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
              <span className={cn("font-medium", isUser ? "text-blue-700" : "text-emerald-700")}>
                {isUser ? "User" : "Agent"}
              </span>
              <span className="font-mono text-muted-foreground">{message.at}</span>
            </div>
            <div className="message-content message-markdown text-sm leading-6">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          </>
        )}
      </div>
    </button>
  )
}

export default App
