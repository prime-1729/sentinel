export type AnomalySeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"

export interface Anomaly {
  id: string
  timestamp: string
  type: string
  severity: AnomalySeverity
  description: string
  recommendation?: string
}

export interface MissionStats {
  duration: string
  maxAltitude: number
  anomaliesDetected: number
}

export interface LiveTelemetry {
  altitude: number
  speed: number
  battery: number
  voltage: number
  lat?: number | null
  lon?: number | null
}

export interface FlightPathPoint {
  timestamp: number
  lat: number
  lon: number
  relative_alt: number
}

export interface AnalyzeResponse {
  status: string
  mission_stats: {
    duration: string
    duration_seconds: number
    max_altitude: number
    max_altitude_metres: number
    anomalies_detected: number
  }
  anomalies: Anomaly[]
  intelligence_report: string
  flight_path: FlightPathPoint[]
}

export interface LiveTelemetryResponse {
  connected: boolean
  connection_error: string | null
  monitor_running: boolean
  telemetry: LiveTelemetry
  anomalies: Anomaly[]
  mission_elapsed_seconds: number
}
