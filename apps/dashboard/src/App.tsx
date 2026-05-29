import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react"
import hljs from "highlight.js/lib/core"
import json from "highlight.js/lib/languages/json"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Database,
  Folder,
  FolderOpen,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import traceFixture from "@/data/traces.json"
import { cn } from "@/lib/utils"

hljs.registerLanguage("json", json)

type SessionStatus = "completed" | "failed" | "running"
type StatusFilter = "all" | SessionStatus
type TimeFilter = "all" | "15m" | "1h"
type TokenUsageMode = "current" | "all"
type DetailMode = "run" | "session"
type RunTab = "overview" | "timeline"
type TraceScope = "runtime" | "agent"

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

type RawWorldSummary = {
  world_id?: string
  label?: string
  kind?: string
  status?: string
  summary?: string
  metadata?: Record<string, unknown>
}

type RawEntityTrace = {
  entity_id: string
  label: string
  kind?: string
  status?: string
  event_count?: number
  token_usage?: RawTokenUsage
  sessions?: RawTraceSession[]
  metadata?: Record<string, unknown>
}

type RawTraceRun = {
  run_id: string
  scope: TraceScope
  title: string
  status: string
  started_at: string
  ended_at: string | null
  event_count: number
  token_usage: RawTokenUsage
  world?: RawWorldSummary | null
  entities?: RawEntityTrace[]
  sessions?: RawTraceSession[]
  events?: RawTraceEvent[]
  metadata?: Record<string, unknown>
}

type TraceApiResponse = {
  db_path?: string
  connected?: boolean
  runs?: RawTraceRun[]
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
  displayId: string
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

type EntityTrace = {
  id: string
  label: string
  kind: string
  status: SessionStatus
  eventCount: number
  promptTokens: number
  completionTokens: number
  totalTokens: number
  sessions: TraceSession[]
  raw: RawEntityTrace
}

type TraceRun = {
  id: string
  title: string
  scope: TraceScope
  status: SessionStatus
  startedAt: string
  startedAgo: string
  duration: string
  eventCount: number
  promptTokens: number
  completionTokens: number
  totalTokens: number
  world: RawWorldSummary | null
  entities: EntityTrace[]
  sessions: TraceSession[]
  events: TraceEvent[]
  raw: RawTraceRun
}

type RuntimeTimelineItem =
  | {
      id: string
      kind: "event"
      timestamp: string
      event: TraceEvent
    }
  | {
      id: string
      kind: "session"
      timestamp: string
      session: TraceSession
      entity: EntityTrace | undefined
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

type TokenMixItem = {
  type: string
  count: number
  percentage: number
  color: string
}

const rawRuns = normalizeRawRuns(traceFixture as unknown as TraceApiResponse)
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

function normalizeRawRuns(payload: TraceApiResponse): RawTraceRun[] {
  if (payload.runs) return payload.runs
  return (payload.sessions ?? []).map((session) => sessionToRawRun(session))
}

function sessionToRawRun(session: RawTraceSession): RawTraceRun {
  return {
    run_id: `run_${session.session_id}`,
    scope: "agent",
    title: inferSessionTitle(session),
    status: session.status,
    started_at: session.started_at,
    ended_at: session.ended_at,
    event_count: session.event_count,
    token_usage: session.token_usage,
    world: null,
    entities: [
      {
        entity_id: session.agent_id || session.session_id,
        label: session.agent_id || "Agent",
        kind: "agent",
        status: session.status,
        event_count: session.event_count,
        token_usage: session.token_usage,
        sessions: [session],
      },
    ],
    sessions: [session],
    events: [],
    metadata: session.metadata,
  }
}

function toTraceRun(run: RawTraceRun): TraceRun {
  const started = new Date(run.started_at)
  const ended = run.ended_at ? new Date(run.ended_at) : null
  const entities = (run.entities ?? []).map(toEntityTrace)
  const sessions = run.sessions?.length
    ? run.sessions.map(toTraceSession)
    : entities.flatMap((entity) => entity.sessions)
  const tokenUsage = run.token_usage ?? buildTokenTotals(sessions)
  const events = (run.events ?? []).map((event, index) =>
    toTraceEvent(event, run.started_at, run.events?.[index - 1]?.timestamp),
  )

  return {
    id: run.run_id,
    title: run.title || run.run_id,
    scope: run.scope,
    status: normalizeStatus(run.status),
    startedAt: started.toLocaleString([], {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }),
    startedAgo: formatRelativeTime(started),
    duration: formatDuration(started, ended),
    eventCount: run.event_count ?? sessions.reduce((total, session) => total + session.events.length, 0),
    promptTokens: tokenUsage.prompt_tokens ?? 0,
    completionTokens: tokenUsage.completion_tokens ?? 0,
    totalTokens: tokenUsage.total_tokens ?? 0,
    world: run.world ?? null,
    entities,
    sessions,
    events,
    raw: run,
  }
}

function toEntityTrace(entity: RawEntityTrace): EntityTrace {
  const sessions = (entity.sessions ?? []).map(toTraceSession)
  const tokenUsage = entity.token_usage ?? buildTokenTotals(sessions)
  const status = entity.status ?? sessions.find((session) => session.status === "running")?.status ?? sessions[0]?.status ?? "running"

  return {
    id: entity.entity_id,
    label: entity.label || entity.entity_id,
    kind: entity.kind ?? "agent",
    status: normalizeStatus(status),
    eventCount: entity.event_count ?? sessions.reduce((total, session) => total + session.events.length, 0),
    promptTokens: tokenUsage.prompt_tokens ?? 0,
    completionTokens: tokenUsage.completion_tokens ?? 0,
    totalTokens: tokenUsage.total_tokens ?? 0,
    sessions,
    raw: entity,
  }
}

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
    id: session.session_id,
    displayId: formatSessionId(session.session_id),
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
  const streamChunk = session.events.find((event) => event.event_type === "LLMStreamChunkEvent")

  if (failed) return String(failed.payload.error ?? "Provider channel unavailable")
  if (firstTool) return String(firstTool.payload.tool_name ?? "Tool call session")
  if (finished) return truncate(String(finished.payload.output ?? "Completed session"), 58)
  if (firstResponse) return truncate(formatAssistantContent(firstResponse.payload), 58)
  if (streamChunk) return truncate(String(streamChunk.payload.content ?? "Streaming response"), 58)
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
    case "LLMStreamChunkEvent":
      return truncate(String(event.payload.content ?? "Streaming response chunk."), 82)
    case "ToolCalledEvent":
      return `${String(event.payload.tool_name ?? "tool")} ${formatArguments(event.payload.arguments)}`
    case "ToolResultEvent":
      return truncate(String(event.payload.result ?? "Tool result received."), 82)
    default:
      return "Persisted event payload."
  }
}

function buildTimelineEvents(events: TraceEvent[]): TraceEvent[] {
  const timelineEvents: TraceEvent[] = []
  let streamGroup: TraceEvent[] = []

  function flushStreamGroup() {
    if (streamGroup.length === 0) return
    if (streamGroup.length === 1) {
      timelineEvents.push(streamGroup[0])
      streamGroup = []
      return
    }

    const first = streamGroup[0]
    const last = streamGroup[streamGroup.length - 1]
    const content = streamGroup.map((event) => String(event.payload.content ?? "")).join("")
    timelineEvents.push({
      ...first,
      id: `${first.id}-stream-group-${last.id}`,
      summary: truncate(content || "Streaming response chunks.", 82),
      latency: `${streamGroup.length} chunks`,
      payload: {
        event_type: "LLMStreamChunkEvent",
        timestamp: first.payload.timestamp,
        chunk_count: streamGroup.length,
        event_ids: streamGroup.map((event) => event.id),
        model: first.payload.model,
        content,
      },
    })
    streamGroup = []
  }

  for (const event of events) {
    if (event.type === "LLMStreamChunkEvent") {
      streamGroup.push(event)
      continue
    }
    flushStreamGroup()
    timelineEvents.push(event)
  }

  flushStreamGroup()
  return timelineEvents
}

function buildRuntimeTimelineItems(run: TraceRun): RuntimeTimelineItem[] {
  const sessionEntity = new Map<string, EntityTrace>()
  for (const entity of run.entities) {
    for (const session of entity.sessions) {
      sessionEntity.set(session.id, entity)
    }
  }

  return [
    ...run.events.map((event) => ({
      id: `event-${event.id}`,
      kind: "event" as const,
      timestamp: String(event.payload.timestamp ?? run.raw.started_at),
      event,
    })),
    ...run.sessions.map((session) => ({
      id: `session-${session.id}`,
      kind: "session" as const,
      timestamp: session.raw.started_at,
      session,
      entity: sessionEntity.get(session.id),
    })),
  ].sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
}

function isTimelineEventSelected(event: TraceEvent, activeEventId: string): boolean {
  if (event.id === activeEventId) return true
  const eventIds = event.payload.event_ids
  return Array.isArray(eventIds) && eventIds.includes(activeEventId)
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

  const messages: TraceMessage[] = []
  let userAdded = false
  let streamingMessage: TraceMessage | null = null

  function flushStreamingMessage() {
    if (streamingMessage) {
      messages.push(streamingMessage)
      streamingMessage = null
    }
  }

  for (const event of session.raw.events) {
    if (event.event_type === "LLMCalledEvent" && !userAdded && Array.isArray(event.payload.messages)) {
      const userMessage = event.payload.messages.findLast((message) =>
        isRecord(message) && normalizeRole(message.role) === "user",
      )
      if (isRecord(userMessage)) {
        messages.push({
          id: `${event.event_id}-user`,
          role: "user",
          content: formatMessageContent(userMessage.content),
          source: "prompt",
          at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
          eventId: event.event_id,
        })
        userAdded = true
      }
    }

    if (event.event_type === "LLMStreamChunkEvent") {
      const content = String(event.payload.content ?? "")
      if (content.length === 0) continue
      if (!streamingMessage) {
        streamingMessage = {
          id: `${event.session_id}-streaming-assistant`,
          role: "assistant",
          content: "",
          source: String(event.payload.model ?? "streaming response"),
          at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
          eventId: event.event_id,
        }
      }
      streamingMessage = {
        ...streamingMessage,
        content: `${streamingMessage.content}${content}`,
        eventId: event.event_id,
      }
      continue
    }

    if (event.event_type === "LLMRespondedEvent") {
      const content = formatAssistantContent(event.payload)
      if (content.length > 0) {
        if (streamingMessage) {
          streamingMessage = {
            ...streamingMessage,
            id: `${event.event_id}-assistant`,
            content,
            source: String(event.payload.model ?? streamingMessage.source),
            eventId: event.event_id,
          }
          flushStreamingMessage()
        } else {
          messages.push({
            id: `${event.event_id}-assistant`,
            role: "assistant",
            content,
            source: String(event.payload.model ?? "LLM response"),
            at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
            eventId: event.event_id,
          })
        }
      }
      continue
    }

    if (event.event_type === "ToolResultEvent") {
      flushStreamingMessage()
      messages.push({
        id: `${event.event_id}-tool`,
        role: "tool",
        content: String(event.payload.result ?? ""),
        source: String(event.payload.tool_name ?? "tool result"),
        at: formatOffset(new Date(session.raw.started_at), new Date(event.timestamp)),
        eventId: event.event_id,
      })
    }
  }

  flushStreamingMessage()
  return messages
}

function buildAllSessionUsageBars(sessions: TraceSession[]): UsageBar[] {
  const eventTimes = sessions
    .flatMap((session) => session.events.map((event) => event.payload.timestamp))
    .filter((value): value is string => typeof value === "string")
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite)
  const anchorTime = eventTimes.length > 0
    ? Math.max(...eventTimes)
    : Date.now()
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

  for (const session of sessions) {
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
  }

  return Array.from(buckets.values())
}

function buildTokenTotals(sessions: TraceSession[]): RawTokenUsage {
  return sessions.reduce<RawTokenUsage>(
    (totals, session) => ({
      prompt_tokens: (totals.prompt_tokens ?? 0) + session.promptTokens,
      completion_tokens: (totals.completion_tokens ?? 0) + session.completionTokens,
      total_tokens: (totals.total_tokens ?? 0) + session.totalTokens,
    }),
    { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  )
}

function buildTokenMix(usage: RawTokenUsage): TokenMixItem[] {
  const promptTokens = usage.prompt_tokens ?? 0
  const completionTokens = usage.completion_tokens ?? 0
  const total = Math.max(1, promptTokens + completionTokens)
  return [
    {
      type: "Input",
      count: promptTokens,
      percentage: (promptTokens / total) * 100,
      color: "oklch(0.62 0.18 247)",
    },
    {
      type: "Output",
      count: completionTokens,
      percentage: (completionTokens / total) * 100,
      color: "oklch(0.66 0.16 150)",
    },
  ]
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
  if (id.length <= 14) return `sess_${id}`
  return `sess_${id.slice(0, 6)}_${id.slice(-6)}`
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
  const [rawRunData, setRawRunData] = useState<RawTraceRun[]>(rawRuns)
  const [filterNow] = useState(() => Date.now())
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [modelFilter, setModelFilter] = useState("all")
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all")
  const [tokenUsageMode, setTokenUsageMode] = useState<TokenUsageMode>("current")
  const [selectedRunId, setSelectedRunId] = useState("")
  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(() => new Set())
  const [expandedEntityIds, setExpandedEntityIds] = useState<Set<string>>(() => new Set())
  const [detailMode, setDetailMode] = useState<DetailMode>("run")
  const [runTab, setRunTab] = useState<RunTab>("overview")
  const [selectedId, setSelectedId] = useState("")
  const [activeRunEventId, setActiveRunEventId] = useState("")
  const [activeEventId, setActiveEventId] = useState("")
  const [activeMessageId, setActiveMessageId] = useState("")
  const [dbMenuOpen, setDbMenuOpen] = useState(false)
  const [dbPath, setDbPath] = useState("local fixture")
  const [dbConnected, setDbConnected] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const dbMenuRef = useRef<HTMLDivElement>(null)
  const filtersMenuRef = useRef<HTMLDivElement>(null)
  const sectionRef = useRef<HTMLElement>(null)
  const [columns, setColumns] = useState({ sessions: 420, inspector: 430 })
  const runRows = useMemo(() => rawRunData.map(toTraceRun), [rawRunData])
  const sessionRows = useMemo(() => runRows.flatMap((run) => run.sessions), [runRows])
  const availableModels = useMemo(() => Array.from(new Set(sessionRows.map((session) => session.model))), [sessionRows])

  function applyTracePayload(payload: TraceApiResponse) {
    const nextDbPath = payload.db_path ?? "unknown"
    setRawRunData(normalizeRawRuns(payload))
    setDbPath(nextDbPath)
    setDbConnected(Boolean(payload.connected))
  }

  useEffect(() => {
    const controller = new AbortController()
    let eventSource: EventSource | null = null
    let loadedFromStream = false

    async function loadTraces() {
      try {
        const response = await fetch("/api/traces", { signal: controller.signal })
        if (!response.ok) return
        const payload = await response.json() as TraceApiResponse
        applyTracePayload(payload)
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return
      }
    }

    if ("EventSource" in window) {
      eventSource = new EventSource("/api/traces/stream")
      eventSource.addEventListener("snapshot", (event) => {
        loadedFromStream = true
        applyTracePayload(JSON.parse(event.data) as TraceApiResponse)
      })
      eventSource.onerror = () => {
        if (!loadedFromStream) void loadTraces()
      }
    } else {
      void loadTraces()
    }

    return () => {
      controller.abort()
      eventSource?.close()
    }
  }, [])

  useEffect(() => {
    function closeMenusOnPointerDown(event: globalThis.PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) return

      if (dbMenuOpen && !dbMenuRef.current?.contains(target)) {
        setDbMenuOpen(false)
      }
      if (filtersOpen && !filtersMenuRef.current?.contains(target)) {
        setFiltersOpen(false)
      }
    }

    function closeMenusOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return
      setDbMenuOpen(false)
      setFiltersOpen(false)
    }

    document.addEventListener("pointerdown", closeMenusOnPointerDown)
    document.addEventListener("keydown", closeMenusOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeMenusOnPointerDown)
      document.removeEventListener("keydown", closeMenusOnEscape)
    }
  }, [dbMenuOpen, filtersOpen])

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

  const filteredSessionIds = useMemo(
    () => new Set(filteredSessions.map((session) => session.id)),
    [filteredSessions],
  )
  const filteredRuns = useMemo(() => {
    return runRows
      .map((run) => {
        const entities = run.entities
          .map((entity) => ({
            ...entity,
            sessions: entity.sessions.filter((session) => filteredSessionIds.has(session.id)),
          }))
          .filter((entity) => entity.sessions.length > 0)
        const sessions = run.sessions.filter((session) => filteredSessionIds.has(session.id))
        return { ...run, entities, sessions }
      })
      .filter((run) => run.sessions.length > 0)
  }, [filteredSessionIds, runRows])

  const selectedRun =
    runRows.find((run) => run.id === selectedRunId) ??
    runRows.find((run) => run.sessions.some((session) => session.id === selectedId)) ??
    runRows[0]
  const selectedSession =
    selectedRun?.sessions.find((session) => session.id === selectedId) ??
    selectedRun?.sessions[0] ??
    sessionRows[0] ??
    emptySession
  const timelineEvents = useMemo(() => buildTimelineEvents(selectedSession.events), [selectedSession])
  const activeEvent =
    selectedSession.events.find((event) => event.id === activeEventId) ??
    timelineEvents.find((event) => event.id === activeEventId) ??
    selectedSession.events[0]
  const activeRunEvent =
    selectedRun?.events.find((event) => event.id === activeRunEventId) ??
    selectedRun?.events[0]
  const usageBars = buildAllSessionUsageBars(sessionRows)
  const maxHourlyTokens = Math.max(1, ...usageBars.map((bucket) => bucket.totalTokens))
  const allTokenUsage = buildTokenTotals(sessionRows)
  const currentTokenUsage: RawTokenUsage = {
    prompt_tokens: detailMode === "run" && selectedRun ? selectedRun.promptTokens : selectedSession.promptTokens,
    completion_tokens: detailMode === "run" && selectedRun ? selectedRun.completionTokens : selectedSession.completionTokens,
    total_tokens: detailMode === "run" && selectedRun ? selectedRun.totalTokens : selectedSession.totalTokens,
  }
  const displayedTokenUsage = tokenUsageMode === "all" ? allTokenUsage : currentTokenUsage
  const tokenMix = buildTokenMix(currentTokenUsage)
  const eventBreakdown = buildEventBreakdown(selectedSession)
  const inspectorPayload = detailMode === "run" && selectedRun
    ? activeRunEvent
      ? activeRunEvent.payload
      : {
          run_id: selectedRun.id,
          scope: selectedRun.scope,
          status: selectedRun.status,
          world: selectedRun.world,
          entities: selectedRun.raw.entities ?? [],
          metadata: selectedRun.raw.metadata ?? {},
        }
    : activeEvent?.payload ?? {}
  const inspectorLabel = detailMode === "run" && selectedRun
    ? activeRunEvent?.type ?? `${selectedRun.scope} run`
    : activeEvent?.type ?? "-"
  const highlightedPayload = highlightJson(inspectorPayload)

  const messages = buildMessageView(selectedSession)
  const selectedMessageId = activeMessageId || messages[0]?.id || ""

  function openRun(run: TraceRun) {
    setSelectedRunId(run.id)
    setSelectedId(run.sessions[0]?.id ?? "")
    setDetailMode("run")
    setActiveRunEventId(run.events[0]?.id ?? "")
    setActiveEventId("")
    setActiveMessageId("")
    setExpandedRunIds((current) => {
      const next = new Set(current)
      if (next.has(run.id)) {
        next.delete(run.id)
      } else {
        next.add(run.id)
      }
      return next
    })
  }

  function toggleEntity(run: TraceRun, entity: EntityTrace) {
    const key = treeEntityKey(run.id, entity.id)
    setExpandedEntityIds((current) => {
      const next = new Set(current)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  function openSession(run: TraceRun, session: TraceSession) {
    setSelectedRunId(run.id)
    setSelectedId(session.id)
    setDetailMode("session")
    setActiveRunEventId("")
    setActiveEventId(session.events[0]?.id ?? "")
    setActiveMessageId("")
    setExpandedRunIds((current) => new Set(current).add(run.id))
    const entity = run.entities.find((candidate) =>
      candidate.sessions.some((candidateSession) => candidateSession.id === session.id),
    )
    if (entity) {
      setExpandedEntityIds((current) => new Set(current).add(treeEntityKey(run.id, entity.id)))
    }
  }

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
            <div ref={dbMenuRef} className="relative">
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
                  <div className="mt-3 text-xs text-muted-foreground">
                    Start the dashboard with <span className="font-mono">easyagent dashboard --db path/to/traces.db</span> to inspect another database.
                  </div>
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
                  <CardTitle className="text-xl">Runs</CardTitle>
                  <CardAction ref={filtersMenuRef} className="relative flex items-center gap-2">
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
                    <TraceTree
                      runs={filteredRuns}
                      expandedRunIds={expandedRunIds}
                      expandedEntityIds={expandedEntityIds}
                      selectedRunId={selectedRun?.id ?? ""}
                      selectedSessionId={detailMode === "session" ? selectedSession.id : ""}
                      onOpenRun={openRun}
                      onToggleEntity={toggleEntity}
                      onOpenSession={openSession}
                    />
                  </ScrollArea>
                </CardContent>
              </Card>
            </div>

            <ResizeHandle label="Resize sessions column" onPointerDown={(event) => startColumnResize("sessions", event)} />

            <div className="min-h-0">
              <Card className="panel-card flex h-full min-h-0 rounded-none border-0 shadow-none ring-0">
                {detailMode === "session" ? (
                  <>
                <CardHeader className="shrink-0 border-b px-5 py-4">
                  <div className="flex items-center gap-3">
                    <button
                      className="flex size-8 items-center justify-center rounded-md border text-muted-foreground transition hover:bg-muted/70 hover:text-foreground"
                      type="button"
                      aria-label="Back to run overview"
                      onClick={() => setDetailMode("run")}
                    >
                      <ArrowLeft data-icon="inline-start" />
                    </button>
                    <CardTitle className="font-mono text-xl">{selectedSession.displayId}</CardTitle>
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
                        <div className="session-timeline relative flex flex-col">
                          {timelineEvents.map((event) => (
                            <TimelineEvent
                              key={event.id}
                              event={event}
                              selected={isTimelineEventSelected(event, activeEventId)}
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
                  </>
                ) : (
                  <RunOverview
                    run={selectedRun}
                    activeTab={runTab}
                    activeRunEventId={activeRunEvent?.id ?? ""}
                    selectedSessionId={selectedSession.id}
                    onTabChange={setRunTab}
                    onSelectRunEvent={(event) => setActiveRunEventId(event.id)}
                    onOpenSession={(session) => {
                      if (selectedRun) openSession(selectedRun, session)
                    }}
                  />
                )}
              </Card>
            </div>

            <ResizeHandle label="Resize inspector column" onPointerDown={(event) => startColumnResize("inspector", event)} />

            <div className="min-h-0 overflow-hidden bg-background p-4">
              <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4">
                <Card size="sm" className="rounded-lg border shadow-none ring-0">
                  <CardHeader>
                    <CardTitle>Token Usage</CardTitle>
                    <CardAction>
                      <div className="inline-flex h-8 rounded-md bg-muted p-0.5 text-xs">
                        {(["current", "all"] as const).map((mode) => (
                          <button
                            key={mode}
                            className={cn(
                              "rounded-[5px] px-2.5 font-medium capitalize transition",
                              tokenUsageMode === mode
                                ? "bg-background text-foreground shadow-sm"
                                : "text-muted-foreground hover:text-foreground",
                            )}
                            type="button"
                            onClick={() => setTokenUsageMode(mode)}
                          >
                            {mode}
                          </button>
                        ))}
                      </div>
                    </CardAction>
                    <CardDescription>
                      <span className="text-2xl font-semibold text-foreground">
                        {(displayedTokenUsage.total_tokens ?? 0).toLocaleString()}
                      </span>{" "}
                      Total Tokens
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="mb-4 flex gap-4 text-sm">
                      <span className="text-blue-600">
                        ↓ {(displayedTokenUsage.prompt_tokens ?? 0).toLocaleString()} input
                      </span>
                      <span className="text-emerald-600">
                        ↑ {(displayedTokenUsage.completion_tokens ?? 0).toLocaleString()} output
                      </span>
                    </div>
                    {tokenUsageMode === "current" ? (
                      <div className="token-pie-layout">
                        <div className="usage-pie animated-pie" style={{ background: pieBackground(tokenMix) }}>
                          <div className="usage-pie-center text-center">
                            <div className="text-2xl font-semibold leading-none">
                              {(displayedTokenUsage.total_tokens ?? 0).toLocaleString()}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">tokens</div>
                          </div>
                        </div>
                        <div className="grid min-w-0 gap-2">
                          {tokenMix.map((item) => (
                            <div key={item.type} className="token-mix-row">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="event-dot" style={{ background: item.color }} />
                                <span className="font-medium">{item.type}</span>
                              </div>
                              <span className="font-mono text-sm">{item.count.toLocaleString()}</span>
                              <span className="text-right text-xs text-muted-foreground">
                                {item.percentage.toFixed(1)}%
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="grid h-32 grid-cols-12 items-end gap-1.5 pt-8">
                          {usageBars.map((bucket, index) => {
                            const promptHeight = (bucket.promptTokens / maxHourlyTokens) * 100
                            const completionHeight = (bucket.completionTokens / maxHourlyTokens) * 100
                            return (
                              <div
                                key={bucket.key}
                                className={cn(
                                  "usage-bar relative h-full rounded-sm bg-muted/50",
                                  index === 0 && "usage-bar-start",
                                  index === usageBars.length - 1 && "usage-bar-end",
                                )}
                                tabIndex={0}
                                aria-label={`${bucket.hour}, ${bucket.totalTokens} total tokens`}
                              >
                                <div className="usage-tooltip pointer-events-none absolute bottom-full z-20 mb-2 w-max rounded-md border bg-background px-2.5 py-2 text-left text-[11px] shadow-lg">
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
                      </>
                    )}
                  </CardContent>
                </Card>

                <Card size="sm" className="flex min-h-0 rounded-lg border shadow-none ring-0">
                  <CardHeader>
                    <CardTitle>Event Payload</CardTitle>
                    <CardAction>
                      <Badge variant="outline">{inspectorLabel}</Badge>
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

function treeEntityKey(runId: string, entityId: string): string {
  return `${runId}:${entityId}`
}

function TraceTree({
  runs,
  expandedRunIds,
  expandedEntityIds,
  selectedRunId,
  selectedSessionId,
  onOpenRun,
  onToggleEntity,
  onOpenSession,
}: {
  runs: TraceRun[]
  expandedRunIds: Set<string>
  expandedEntityIds: Set<string>
  selectedRunId: string
  selectedSessionId: string
  onOpenRun: (run: TraceRun) => void
  onToggleEntity: (run: TraceRun, entity: EntityTrace) => void
  onOpenSession: (run: TraceRun, session: TraceSession) => void
}) {
  if (runs.length === 0) {
    return (
      <div className="px-4 py-8 text-sm text-muted-foreground">
        No runs match the current filters.
      </div>
    )
  }

  return (
    <div className="trace-tree py-2">
      {runs.map((run) => {
        const selected = run.id === selectedRunId && !selectedSessionId
        const expanded = expandedRunIds.has(run.id)
        return (
          <div key={run.id} className="trace-tree-run">
            <button
              className={cn("trace-tree-row trace-tree-row-run", selected && "trace-tree-row-active")}
              type="button"
              onClick={() => onOpenRun(run)}
            >
              <ChevronRight
                className={cn("trace-tree-chevron", expanded && "trace-tree-chevron-open")}
                data-icon="inline-start"
              />
              {run.id === selectedRunId ? (
                <FolderOpen className="trace-tree-icon trace-tree-icon-run" data-icon="inline-start" />
              ) : (
                <Folder className="trace-tree-icon trace-tree-icon-run" data-icon="inline-start" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{run.title}</span>
                <span className="block truncate font-mono text-[11px] text-muted-foreground">
                  {run.scope} · {run.startedAgo}
                </span>
              </span>
              <span className="trace-tree-count">{run.sessions.length}</span>
              <span className={cn("trace-tree-status", `trace-tree-status-${run.status}`)} />
            </button>

            {expanded && (
              <div className="trace-tree-children">
                {run.entities.map((entity) => {
                  const entityExpanded = expandedEntityIds.has(treeEntityKey(run.id, entity.id))
                  return (
                  <div key={`${run.id}-${entity.id}`} className="trace-tree-entity">
                    <button
                      className="trace-tree-row trace-tree-row-entity"
                      type="button"
                      onClick={() => onToggleEntity(run, entity)}
                    >
                      <ChevronRight
                        className={cn("trace-tree-chevron trace-tree-chevron-entity", entityExpanded && "trace-tree-chevron-open")}
                        data-icon="inline-start"
                      />
                      <span className={cn("trace-tree-entity-dot", `trace-tree-status-${entity.status}`)} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{entity.label}</span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {entity.kind} · {entity.eventCount} events
                        </span>
                      </span>
                      <span className="trace-tree-count">{entity.sessions.length}</span>
                    </button>

                    {entityExpanded && (
                    <div className="trace-tree-sessions">
                      {entity.sessions.map((session) => (
                        <button
                          key={`${run.id}-${entity.id}-${session.id}`}
                          className={cn(
                            "trace-tree-row trace-tree-row-session",
                            session.id === selectedSessionId && "trace-tree-row-active",
                          )}
                          type="button"
                          onClick={() => onOpenSession(run, session)}
                        >
                          <PlayCircle className="trace-tree-icon trace-tree-icon-session" data-icon="inline-start" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm">{session.title}</span>
                            <span className="block truncate font-mono text-[11px] text-muted-foreground">
                              {session.displayId}
                            </span>
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{session.latency}</span>
                        </button>
                      ))}
                    </div>
                    )}
                  </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function RunOverview({
  run,
  activeTab,
  activeRunEventId,
  selectedSessionId,
  onTabChange,
  onSelectRunEvent,
  onOpenSession,
}: {
  run: TraceRun | undefined
  activeTab: RunTab
  activeRunEventId: string
  selectedSessionId: string
  onTabChange: (tab: RunTab) => void
  onSelectRunEvent: (event: TraceEvent) => void
  onOpenSession: (session: TraceSession) => void
}) {
  if (!run) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No trace run selected.
      </div>
    )
  }

  return (
    <>
      <CardHeader className="shrink-0 border-b px-5 py-4">
        <div className="flex items-center gap-3">
          <CardTitle className="truncate text-xl">{run.title}</CardTitle>
          <Badge variant="outline" className={statusClass[run.status]}>
            {run.status}
          </Badge>
          <Badge variant="secondary" className="capitalize">
            {run.scope} run
          </Badge>
        </div>
        <div className="mt-4 grid grid-cols-5 gap-4 text-sm">
          <MetaCell label="Started" value={run.startedAt} />
          <MetaCell label="Duration" value={run.duration} />
          <MetaCell label="Entities" value={String(run.entities.length)} />
          <MetaCell label="Sessions" value={String(run.sessions.length)} />
          <MetaCell label="Events" value={String(run.eventCount)} />
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 px-5 py-4">
        <Tabs
          value={activeTab}
          onValueChange={(value) => onTabChange(value as RunTab)}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="timeline">Timeline {run.events.length + run.sessions.length}</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="min-h-0 flex-1">
            <div className="flex h-full min-h-0 flex-col gap-4">
              <div className="runtime-overview-grid">
                <div className="runtime-card">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">World</div>
                  <div className="mt-2 text-lg font-semibold">
                    {run.world?.label ?? run.world?.world_id ?? "Agent-only run"}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {run.world?.summary ?? "No world context has been attached to this run yet."}
                  </div>
                </div>
                <div className="runtime-card">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Usage</div>
                  <div className="mt-2 text-lg font-semibold">{run.totalTokens.toLocaleString()} tokens</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {run.promptTokens.toLocaleString()} input · {run.completionTokens.toLocaleString()} output
                  </div>
                </div>
              </div>

              <ScrollArea className="min-h-0 flex-1 pr-2">
                <div className="grid gap-3 pb-2">
                  {run.entities.map((entity) => (
                    <div key={entity.id} className="runtime-entity-card">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate font-medium">{entity.label}</div>
                          <div className="mt-1 text-sm text-muted-foreground">
                            {entity.kind} · {entity.eventCount} events · {entity.totalTokens.toLocaleString()} tokens
                          </div>
                        </div>
                        <Badge className={statusClass[entity.status]}>{entity.status}</Badge>
                      </div>
                      <div className="mt-3 grid gap-2">
                        {entity.sessions.map((session) => (
                          <button
                            key={session.id}
                            className={cn(
                              "runtime-session-row",
                              session.id === selectedSessionId && "runtime-session-row-active",
                            )}
                            type="button"
                            onClick={() => onOpenSession(session)}
                          >
                            <span className="min-w-0 flex-1 text-left">
                              <span className="block truncate font-medium">{session.title}</span>
                              <span className="block truncate font-mono text-xs text-muted-foreground">
                                {session.displayId} · {session.model}
                              </span>
                            </span>
                            <span className="text-sm text-muted-foreground">{session.startedAgo}</span>
                            <span className="font-mono text-sm">{session.totalTokens.toLocaleString()}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </TabsContent>

          <TabsContent value="timeline" className="min-h-0 flex-1">
            <RuntimeTimeline
              run={run}
              activeEventId={activeRunEventId}
              onSelectEvent={onSelectRunEvent}
              onOpenSession={onOpenSession}
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </>
  )
}

function RuntimeTimeline({
  run,
  activeEventId,
  onSelectEvent,
  onOpenSession,
}: {
  run: TraceRun
  activeEventId: string
  onSelectEvent: (event: TraceEvent) => void
  onOpenSession: (session: TraceSession) => void
}) {
  const items = buildRuntimeTimelineItems(run)

  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border text-sm text-muted-foreground">
        No runtime timeline events captured.
      </div>
    )
  }

  return (
    <ScrollArea className="h-full pr-2">
      <div className="runtime-timeline">
        {items.map((item) => {
          if (item.kind === "session") {
            return (
              <button
                key={item.id}
                type="button"
                className="runtime-timeline-row runtime-timeline-session"
                onClick={() => onOpenSession(item.session)}
              >
                <RuntimeTimelineRail color="session" />
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate font-medium">{item.session.title}</span>
                  <span className="block truncate text-sm text-muted-foreground">
                    {item.entity?.label ?? item.session.user} · {item.session.displayId} · {item.session.totalTokens.toLocaleString()} tokens
                  </span>
                </span>
                <Badge variant="outline">{item.session.duration}</Badge>
              </button>
            )
          }

          return (
            <button
              key={item.id}
              type="button"
              className={cn(
                "runtime-timeline-row",
                item.event.id === activeEventId && "runtime-timeline-row-active",
              )}
              onClick={() => onSelectEvent(item.event)}
            >
              <RuntimeTimelineRail color={runtimeEventColor(item.event.type)} />
              <span className="min-w-0 flex-1 text-left">
                <span className="block truncate font-medium">{item.event.type}</span>
                <span className="block truncate text-sm text-muted-foreground">{item.event.summary}</span>
              </span>
              <span className="font-mono text-xs text-muted-foreground">{item.event.at}</span>
            </button>
          )
        })}
      </div>
    </ScrollArea>
  )
}

function RuntimeTimelineRail({
  color,
}: {
  color: "runtime" | "entity" | "message" | "session"
}) {
  return (
    <span className="runtime-timeline-rail">
      <span className={cn("runtime-timeline-dot", `runtime-timeline-dot-${color}`)} />
    </span>
  )
}

function runtimeEventColor(type: string): "runtime" | "entity" | "message" | "session" {
  if (type.includes("Entity")) return "entity"
  if (type.includes("Message")) return "message"
  return "runtime"
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
        <div className="event-pie animated-pie" style={{ background: pieBackground(items) }}>
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
  selected,
  onClick,
}: {
  event: TraceEvent
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
        "timeline-row grid grid-cols-[112px_32px_1fr_auto] items-center gap-3 border-b px-0 py-4 text-left",
        selected && "selected-row",
      )}
    >
      <span className="font-mono text-sm text-muted-foreground">{event.at}</span>
      <span className="timeline-node relative z-10 flex size-8 items-center justify-center">
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
