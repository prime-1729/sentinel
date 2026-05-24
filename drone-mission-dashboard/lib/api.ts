import type { AnalyzeResponse, LiveTelemetryResponse } from "./types"

const API_BASE =
  process.env.NEXT_PUBLIC_SENTINEL_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed (${response.status})`)
  }

  return response.json() as Promise<T>
}

export async function analyzeMissionLog(file: File): Promise<AnalyzeResponse> {
  const formData = new FormData()
  formData.append("file", file)

  return request<AnalyzeResponse>("/analyze", {
    method: "POST",
    body: formData,
  })
}

export async function fetchLiveTelemetry(): Promise<LiveTelemetryResponse> {
  return request<LiveTelemetryResponse>("/telemetry/live")
}

export async function startLiveMonitor(
  connection = "udpin:127.0.0.1:14551",
): Promise<{ status: string; connection: string }> {
  return request(`/monitor/start?connection=${encodeURIComponent(connection)}`, {
    method: "POST",
  })
}

export async function stopLiveMonitor(): Promise<{ status: string }> {
  return request("/monitor/stop", { method: "POST" })
}

export async function checkHealth(): Promise<{
  status: string
  live_monitor_running: boolean
  live_connected: boolean
}> {
  return request("/health")
}

export { API_BASE }
