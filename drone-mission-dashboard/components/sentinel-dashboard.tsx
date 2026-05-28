"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import {
  Upload,
  AlertTriangle,
  Radio,
  Shield,
  Clock,
  ArrowUp,
  Gauge,
  Battery,
  Zap,
  Play,
  Square,
  Loader2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  analyzeMissionLog,
  fetchLiveTelemetry,
  startLiveMonitor,
  stopLiveMonitor,
  checkHealth,
  API_BASE,
} from "@/lib/api"
import type {
  Anomaly,
  FlightPathPoint,
  LiveTelemetry,
  MissionStats,
} from "@/lib/types"

const EMPTY_TELEMETRY: LiveTelemetry = {
  altitude: 0,
  speed: 0,
  battery: 0,
  voltage: 0,
}

export default function SentinelDashboard() {
  const [file, setFile] = useState<File | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [missionLoaded, setMissionLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [telemetry, setTelemetry] = useState<LiveTelemetry>(EMPTY_TELEMETRY)
  const [stats, setStats] = useState<MissionStats>({
    duration: "00:00:00",
    maxAltitude: 0,
    anomaliesDetected: 0,
  })
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [intelReport, setIntelReport] = useState("")
  const [flightPath, setFlightPath] = useState<FlightPathPoint[]>([])

  const [liveConnected, setLiveConnected] = useState(false)
  const [liveMonitorRunning, setLiveMonitorRunning] = useState(false)
  const [isStartingMonitor, setIsStartingMonitor] = useState(false)
  const [backendOnline, setBackendOnline] = useState(false)
  const [liveMonitorRequested, setLiveMonitorRequested] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [clock, setClock] = useState("--:--:--")

  const liveAnomaliesRef = useRef<Anomaly[]>([])

  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleTimeString("en-US", { hour12: false }),
      )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    checkHealth()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false))
  }, [])

  const pollLiveTelemetry = useCallback(async () => {
    try {
      const data = await fetchLiveTelemetry()
      setLiveConnected(data.connected)
      setLiveMonitorRunning(data.monitor_running)
      setConnectionError(data.connection_error)
      setTelemetry(data.telemetry)
      liveAnomaliesRef.current = data.anomalies

      if (data.connected) {
        setMissionLoaded(true)

        // Update live stats (Duration and Max Altitude)
        const formatDuration = (sec: number) => {
          const hrs = Math.floor(sec / 3600)
          const mins = Math.floor((sec % 3600) / 60)
          const secs = sec % 60
          return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
        }

        setStats((prev) => ({
          duration: formatDuration(data.mission_elapsed_seconds),
          maxAltitude: Math.max(prev.maxAltitude, data.telemetry.altitude),
          anomaliesDetected: data.anomalies.length,
        }))

        // Update live flight path coordinates for the Tactical Map
        if (data.telemetry.lat != null && data.telemetry.lon != null) {
          const newPoint = {
            timestamp: Date.now() / 1000,
            lat: data.telemetry.lat,
            lon: data.telemetry.lon,
            relative_alt: data.telemetry.altitude,
          }

          setFlightPath((prevPath) => {
            const last = prevPath[prevPath.length - 1]
            if (
              last &&
              last.lat === newPoint.lat &&
              last.lon === newPoint.lon &&
              last.relative_alt === newPoint.relative_alt
            ) {
              return prevPath
            }
            return [...prevPath, newPoint]
          })
        }
      }

      setAnomalies((prev) => {
        const missionOnly = prev.filter((a) => !a.id.startsWith("LIVE-"))
        const merged = [...liveAnomaliesRef.current, ...missionOnly]
        const seen = new Set<string>()
        return merged.filter((a) => {
          if (seen.has(a.id)) return false
          seen.add(a.id)
          return true
        })
      })
    } catch {
      setLiveConnected(false)
    }
  }, [])

  useEffect(() => {
    if (!liveMonitorRequested && !missionLoaded) return

    pollLiveTelemetry()
    const interval = setInterval(pollLiveTelemetry, 1500)
    return () => clearInterval(interval)
  }, [liveMonitorRequested, missionLoaded, pollLiveTelemetry])

  const handleAnalyze = useCallback(async () => {
    if (!file) return

    setIsProcessing(true)
    setError(null)

    try {
      const result = await analyzeMissionLog(file)
      setStats({
        duration: result.mission_stats.duration,
        maxAltitude: result.mission_stats.max_altitude,
        anomaliesDetected: result.mission_stats.anomalies_detected,
      })
      setAnomalies(result.anomalies)
      setIntelReport(result.intelligence_report)
      setFlightPath(result.flight_path)
      setMissionLoaded(true)

      const lastPoint = result.flight_path[result.flight_path.length - 1]
      if (lastPoint) {
        setTelemetry({
          altitude: lastPoint.relative_alt,
          speed: 0,
          battery: telemetry.battery,
          voltage: telemetry.voltage,
          lat: lastPoint.lat,
          lon: lastPoint.lon,
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setIsProcessing(false)
    }
  }, [file, telemetry.battery, telemetry.voltage])

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = e.target.files?.[0]
    if (uploadedFile && uploadedFile.name.endsWith(".tlog")) {
      setFile(uploadedFile)
      setError(null)
    } else if (uploadedFile) {
      setError("Only .tlog mission log files are supported")
    }
  }, [])

  const handleStartMonitor = async () => {
    setIsStartingMonitor(true)
    setError(null)
    setConnectionError(null)
    setLiveMonitorRequested(true)

    // Clear any previous session state to start fresh
    setStats({
      duration: "00:00:00",
      maxAltitude: 0,
      anomaliesDetected: 0,
    })
    setAnomalies([])
    setFlightPath([])
    setIntelReport("")

    try {
      await startLiveMonitor()
      setLiveMonitorRunning(true)
      await pollLiveTelemetry()
    } catch (err) {
      setLiveMonitorRequested(false)
      setError(
        err instanceof Error
          ? err.message
          : "Could not reach API. Is uvicorn running on port 8000?",
      )
    } finally {
      setIsStartingMonitor(false)
    }
  }

  const handleStopMonitor = async () => {
    try {
      await stopLiveMonitor()
      setLiveMonitorRequested(false)
      setLiveMonitorRunning(false)
      setLiveConnected(false)
      setConnectionError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop monitor")
    }
  }

  const getSeverityStyles = (severity: Anomaly["severity"]) => {
    switch (severity) {
      case "CRITICAL":
        return "bg-red-500/20 text-red-400 border-red-500/50"
      case "HIGH":
        return "bg-orange-500/20 text-orange-400 border-orange-500/50"
      case "MEDIUM":
        return "bg-yellow-500/20 text-yellow-400 border-yellow-500/50"
      default:
        return "bg-green-500/20 text-green-400 border-green-500/50"
    }
  }

  const mapPath = flightPath.length > 1 ? flightPath : null
  const latestPosition = flightPath[flightPath.length - 1]
  const gridLabel =
    latestPosition != null
      ? `${latestPosition.lat.toFixed(4)}° N, ${latestPosition.lon.toFixed(4)}° E`
      : liveConnected && telemetry.lat != null && telemetry.lon != null
        ? `${telemetry.lat.toFixed(4)}° N, ${telemetry.lon.toFixed(4)}° E`
        : "AWAITING TELEMETRY"

  const statusLabel = !backendOnline
    ? "BACKEND OFFLINE"
    : liveConnected
      ? "LIVE LINK"
      : liveMonitorRunning
        ? "CONNECTING"
        : missionLoaded
          ? "MISSION LOADED"
          : "STANDBY"

  const statusVariant =
    liveConnected || missionLoaded
      ? "bg-primary/20 text-primary border-primary/50"
      : "bg-muted text-muted-foreground border-border"

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <header className="flex items-center justify-between mb-6 pb-4 border-b border-border">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Shield className="h-8 w-8 text-primary" />
            <h1 className="text-2xl font-bold tracking-wider text-foreground">
              SENTINEL
            </h1>
          </div>
          <span className="text-xs text-muted-foreground font-mono">v0.1.0</span>
        </div>
        <div className="flex items-center gap-4">
          <Badge
            variant="outline"
            className={`font-mono text-xs px-3 py-1 ${statusVariant}`}
          >
            <span
              className={`w-2 h-2 rounded-full mr-2 inline-block ${liveConnected ? "bg-primary pulse-glow" : "bg-muted-foreground"
                }`}
            />
            {statusLabel}
          </Badge>
          <span className="text-xs text-muted-foreground font-mono" suppressHydrationWarning>
            {clock} UTC
          </span>
        </div>
      </header>

      {!backendOnline && (
        <div className="mb-4 rounded-md border border-orange-500/50 bg-orange-500/10 px-4 py-3 text-sm font-mono text-orange-300">
          Backend unreachable at {API_BASE}. Start the API:{" "}
          <code className="text-orange-200">
            uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
          </code>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm font-mono text-red-400">
          {error}
        </div>
      )}

      <Card className="mb-6 bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
            <Upload className="h-4 w-4" />
            MISSION LOG UPLOAD
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <label className="flex-1">
              <input
                type="file"
                accept=".tlog"
                onChange={handleFileUpload}
                className="hidden"
              />
              <div className="border-2 border-dashed border-border rounded-md p-6 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors">
                <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                <p className="text-sm text-muted-foreground font-mono">
                  {file
                    ? file.name
                    : "Drop .tlog file here or click to browse"}
                </p>
              </div>
            </label>
            {file && (
              <Button
                disabled={isProcessing || !backendOnline}
                onClick={handleAnalyze}
                className="bg-primary text-primary-foreground hover:bg-primary/90 font-mono"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    PROCESSING...
                  </>
                ) : (
                  "ANALYZE"
                )}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="mb-6 bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" />
            LIVE MAVLINK MONITOR
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-mono text-muted-foreground flex-1 min-w-[200px]">
              In the SITL terminal run{" "}
              <code className="text-primary">output add 127.0.0.1:14551</code> once per
              session. SENTINEL listens on port 14551 (MAVProxy keeps 14550 for the
              console). Start SITL, arm, and takeoff before START LIVE.
            </p>
            {!liveMonitorRequested ? (
              <Button
                onClick={handleStartMonitor}
                disabled={isStartingMonitor || !backendOnline}
                className="font-mono"
              >
                {isStartingMonitor ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                START LIVE
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={handleStopMonitor}
                className="font-mono"
              >
                <Square className="h-4 w-4 mr-2" />
                STOP LIVE
              </Button>
            )}
          </div>
          {liveMonitorRequested && !liveConnected && (
            <p className="text-xs font-mono text-yellow-400/90">
              {liveMonitorRunning
                ? "Connecting to SITL (waiting for heartbeat, up to ~10s)…"
                : "Monitor stopped."}
            </p>
          )}
          {connectionError && (
            <p className="text-xs font-mono text-red-400">
              MAVLink: {connectionError}. Is SITL running? Start sim_vehicle.py,
              arm, and takeoff, then click START LIVE again.
            </p>
          )}
          {liveConnected && (
            <p className="text-xs font-mono text-primary">
              Live link active — telemetry updating below.
            </p>
          )}
        </CardContent>
      </Card>

      {missionLoaded && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <Card className="bg-card border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-md bg-primary/10">
                    <Clock className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground font-mono">
                      DURATION
                    </p>
                    <p className="text-xl font-mono text-foreground">
                      {stats.duration}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-md bg-primary/10">
                    <ArrowUp className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground font-mono">
                      MAX ALTITUDE
                    </p>
                    <p className="text-xl font-mono text-foreground">
                      {stats.maxAltitude}
                      <span className="text-sm text-muted-foreground ml-1">
                        m
                      </span>
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-md bg-orange-500/10">
                    <AlertTriangle className="h-5 w-5 text-orange-400" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground font-mono">
                      ANOMALIES DETECTED
                    </p>
                    <p className="text-xl font-mono text-foreground">
                      {anomalies.length || stats.anomaliesDetected}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" />
                  ANOMALY EVENTS
                </CardTitle>
              </CardHeader>
              <CardContent className="max-h-[320px] overflow-y-auto">
                {anomalies.length === 0 ? (
                  <p className="text-xs font-mono text-muted-foreground">
                    No anomalies detected. Mission nominal.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {anomalies.map((anomaly) => (
                      <div
                        key={anomaly.id}
                        className="p-3 rounded-md bg-secondary/50 border border-border"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono text-muted-foreground">
                              {anomaly.id}
                            </span>
                            <Badge
                              variant="outline"
                              className={`text-[10px] font-mono ${getSeverityStyles(anomaly.severity)}`}
                            >
                              {anomaly.severity}
                            </Badge>
                          </div>
                          <span className="text-xs font-mono text-muted-foreground">
                            {anomaly.timestamp}
                          </span>
                        </div>
                        <p className="text-xs font-mono text-primary mb-1">
                          {anomaly.type}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {anomaly.description}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
                  <Radio className="h-4 w-4" />
                  TACTICAL MAP
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="relative h-[280px] rounded-md bg-[#0a0f0a] tactical-grid overflow-hidden">
                  <div className="absolute inset-0 pointer-events-none">
                    <div className="w-full h-8 bg-gradient-to-b from-primary/20 to-transparent scan-line" />
                  </div>

                  <div className="absolute top-2 left-2 text-[10px] font-mono text-primary/60">
                    GRID: {gridLabel}
                  </div>
                  <div className="absolute bottom-2 right-2 text-[10px] font-mono text-primary/60">
                    POINTS: {flightPath.length}
                  </div>

                  {mapPath && (
                    <svg className="absolute inset-0 w-full h-full pointer-events-none p-4">
                      <polyline
                        fill="none"
                        stroke="rgba(34, 197, 94, 0.5)"
                        strokeWidth="2"
                        strokeDasharray="6 4"
                        points={mapPath
                          .map((point, index) => {
                            const x =
                              20 +
                              (index / Math.max(mapPath.length - 1, 1)) * 280
                            const y =
                              240 -
                              (point.relative_alt /
                                Math.max(
                                  ...mapPath.map((p) => p.relative_alt),
                                  1,
                                )) *
                              180
                            return `${x},${y}`
                          })
                          .join(" ")}
                      />
                    </svg>
                  )}

                  <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
                    <div className="relative">
                      <div
                        className={`w-4 h-4 rounded-full ${liveConnected ? "bg-primary pulse-glow" : "bg-primary/40"
                          }`}
                      />
                      <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] font-mono text-primary whitespace-nowrap">
                        {liveConnected ? "LIVE ASSET" : "LOG REPLAY"}
                      </div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {intelReport && (
            <Card className="mb-6 bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  AI INTELLIGENCE REPORT
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="bg-secondary/30 rounded-md p-4 max-h-[300px] overflow-y-auto">
                  <pre className="text-xs font-mono text-foreground/90 whitespace-pre-wrap">
                    {intelReport}
                  </pre>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <Card className="bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-mono text-muted-foreground flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" />
            <span
              className={`w-2 h-2 rounded-full ${liveConnected ? "bg-primary pulse-glow" : "bg-muted-foreground"
                }`}
            />
            LIVE TELEMETRY
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <TelemetryTile
              icon={<ArrowUp className="h-4 w-4 text-primary" />}
              label="ALTITUDE"
              value={telemetry.altitude.toFixed(1)}
              unit="m"
            />
            <TelemetryTile
              icon={<Gauge className="h-4 w-4 text-primary" />}
              label="SPEED"
              value={telemetry.speed.toFixed(1)}
              unit="m/s"
            />
            <div className="bg-secondary/30 rounded-md p-4 border border-border">
              <div className="flex items-center gap-2 mb-2">
                <Battery className="h-4 w-4 text-primary" />
                <span className="text-[10px] font-mono text-muted-foreground">
                  BATTERY
                </span>
              </div>
              <p className="text-2xl font-mono text-foreground">
                {telemetry.battery.toFixed(0)}
                <span className="text-sm text-muted-foreground ml-1">%</span>
              </p>
              <div className="mt-2 h-1.5 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-500"
                  style={{ width: `${Math.max(0, Math.min(100, telemetry.battery))}%` }}
                />
              </div>
            </div>
            <TelemetryTile
              icon={<Zap className="h-4 w-4 text-primary" />}
              label="VOLTAGE"
              value={telemetry.voltage.toFixed(1)}
              unit="V"
            />
          </div>
        </CardContent>
      </Card>

      <footer className="mt-6 pt-4 border-t border-border flex items-center justify-between">
        <span className="text-[10px] font-mono text-muted-foreground">
          SENTINEL DRONE INTELLIGENCE SYSTEM
        </span>
        <span className="text-[10px] font-mono text-muted-foreground">
          API: {backendOnline ? "CONNECTED" : "UNREACHABLE"} ({API_BASE})
        </span>
      </footer>
    </div>
  )
}

function TelemetryTile({
  icon,
  label,
  value,
  unit,
}: {
  icon: React.ReactNode
  label: string
  value: string
  unit: string
}) {
  return (
    <div className="bg-secondary/30 rounded-md p-4 border border-border">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-[10px] font-mono text-muted-foreground">
          {label}
        </span>
      </div>
      <p className="text-2xl font-mono text-foreground">
        {value}
        <span className="text-sm text-muted-foreground ml-1">{unit}</span>
      </p>
    </div>
  )
}
