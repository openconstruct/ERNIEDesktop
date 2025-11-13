#!/usr/bin/env python3
"""
FastAPI Search Server with Tavily integration
For IRIS/ERNIE Desktop App
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from tavily import TavilyClient
import uvicorn
import os
import sys
from datetime import datetime

try:
    import psutil
except ImportError:  # pragma: no cover - psutil should exist but degrade gracefully
    psutil = None

app = FastAPI(title="IRIS Search API", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Tavily client (get API key from environment)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
if not TAVILY_API_KEY:
    print("⚠️  WARNING: TAVILY_API_KEY not set in environment variables")
    print("   Get your free API key at: https://tavily.com")
    print("   Set it with: export TAVILY_API_KEY=your_key_here")

API_MODEL = os.getenv("API_MODEL", "tavily-web")
API_HOST = os.getenv("API_HOST", "127.0.0.1")
POWER_IDLE_WATTS = float(os.getenv("POWER_IDLE_WATTS", "15"))
POWER_MAX_WATTS = float(os.getenv("POWER_MAX_WATTS", "65"))

def _get_port_value():
    raw = os.getenv("API_PORT", "8000")
    try:
        return int(raw)
    except ValueError:
        print(f"⚠️  WARNING: Invalid API_PORT '{raw}', falling back to 8000.")
        return 8000

API_PORT = _get_port_value()

tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    query: str
    count: int = 5  # Changed from max_results to count

class SearchResult(BaseModel):
    name: str  # Changed from title to name
    url: str
    snippet: str

class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    model: str
    error: Optional[str] = None  # Added error field for compatibility

class PowerTelemetry(BaseModel):
    watts: Optional[float]
    plugged: Optional[bool]
    percent: Optional[float]
    status: str
    detail: Optional[str] = None
    timestamp: str
    ram_used_bytes: Optional[int] = None
    ram_total_bytes: Optional[int] = None
    ram_percent: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    temp_source: Optional[str] = None
    cpu_usage_percent: Optional[float] = None
    power_idle_watts: Optional[float] = None
    power_max_watts: Optional[float] = None
    power_utilization: Optional[float] = None

@app.get("/")
async def root():
    return {
        "service": "IRIS Search API",
        "version": "1.0.0",
        "model": API_MODEL,
        "endpoints": {
            "search": "/search/web (POST)",
            "health": "/health (GET)"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/search/web", response_model=SearchResponse)
async def search_web(request: SearchRequest):
    """
    Search using Tavily and return formatted results
    """
    if not request.query or len(request.query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    if not tavily_client:
        raise HTTPException(
            status_code=503,
            detail="Search service not configured. Set TAVILY_API_KEY environment variable."
        )
    
    try:
        # Perform Tavily search
        response = tavily_client.search(
            query=request.query,
            max_results=request.count  # Use count from request
        )
        
        # Extract results
        raw_results = response.get("results", [])
        
        # Format results to match expected structure
        results = []
        for item in raw_results:
            results.append(SearchResult(
                name=item.get("title", "No title"),  # Map title to name
                url=item.get("url", ""),
                snippet=item.get("content", "No description available")
            ))
        
        return SearchResponse(
            query=request.query,
            results=results,
            model=API_MODEL,
            error=None
        )
        
    except Exception as e:
        # Return error in response instead of raising exception
        return SearchResponse(
            query=request.query,
            results=[],
            model=API_MODEL,
            error=f"Search failed: {str(e)}"
        )

def _read_power_supply_watts():
    if not sys.platform.startswith("linux"):
        return None
    try:
        from psutil import _pslinux  # type: ignore
    except Exception:
        return None

    power_path = getattr(_pslinux, "POWER_SUPPLY_PATH", "/sys/class/power_supply")
    try:
        entries = [
            entry for entry in os.listdir(power_path)
            if entry.startswith("BAT") or "battery" in entry.lower()
        ]
    except FileNotFoundError:
        return None

    if not entries:
        return None

    root = os.path.join(power_path, sorted(entries)[0])

    def _read_number(*relative_paths):
        for rel in relative_paths:
            path = os.path.join(root, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().strip()
            except FileNotFoundError:
                continue
            except OSError:
                continue
            try:
                return float(raw), rel
            except ValueError:
                continue
        return None, None

    power_value, source = _read_number("power_now", "current_now")
    if power_value is None:
        return None

    watts = None
    if source == "power_now":
        # power_now is reported in microwatts
        watts = power_value / 1_000_000.0
    elif source == "current_now":
        voltage_value, _ = _read_number("voltage_now")
        if voltage_value is not None:
            watts = (power_value * voltage_value) / 1_000_000_000_000.0  # microA * microV

    if watts is None:
        return None
    return round(watts, 2)

def _read_hwmon_power_watts():
    base_path = "/sys/class/hwmon"
    if not os.path.isdir(base_path):
        return None
    try:
        hwmons = sorted(os.listdir(base_path))
    except OSError:
        return None

    for entry in hwmons:
        root = os.path.join(base_path, entry)
        try:
            files = os.listdir(root)
        except OSError:
            continue
        power_files = sorted(f for f in files if f.startswith("power") and f.endswith("_input"))
        for pf in power_files:
            path = os.path.join(root, pf)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().strip()
                    value = float(raw)
            except (OSError, ValueError):
                continue
            if value <= 0:
                continue
            # hwmon power is usually reported in microwatts
            watts = value / 1_000_000.0
            return round(watts, 2)
    return None

def _read_linux_power_watts():
    if not sys.platform.startswith("linux"):
        return None
    watts = _read_power_supply_watts()
    if watts is not None:
        return watts
    return _read_hwmon_power_watts()

def _estimate_power_draw():
    if psutil is None:
        return None
    try:
        load = psutil.cpu_percent(interval=0.05) / 100.0
        clamped = max(0.0, min(1.0, load))
        span = max(0.0, POWER_MAX_WATTS - POWER_IDLE_WATTS)
        watts = POWER_IDLE_WATTS + span * clamped
        return round(max(0.0, watts), 2)
    except Exception:
        return None

def get_power_metrics():
    payload = {
        "watts": None,
        "plugged": None,
        "percent": None,
        "status": "unavailable",
        "detail": None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ram_used_bytes": None,
        "ram_total_bytes": None,
        "ram_percent": None,
        "cpu_temp_c": None,
        "temp_source": None,
        "cpu_usage_percent": None,
        "power_idle_watts": POWER_IDLE_WATTS,
        "power_max_watts": POWER_MAX_WATTS,
        "power_utilization": None,
    }

    battery = None
    if psutil is None:
        payload["detail"] = "psutil is not installed"
    else:
        battery_reader = getattr(psutil, "sensors_battery", None)
        if battery_reader is None:
            payload["detail"] = "Battery sensors not supported on this platform"
        else:
            try:
                battery = battery_reader()
            except Exception as exc:  # pragma: no cover
                payload["detail"] = f"Battery sensor error: {exc}"
                payload["status"] = "error"
            else:
                if battery is None:
                    payload["detail"] = "Battery information unavailable"
                else:
                    payload["plugged"] = getattr(battery, "power_plugged", None)
                    payload["percent"] = getattr(battery, "percent", None)

    watts = None
    if sys.platform.startswith("linux"):
        watts = _read_linux_power_watts()

    # Some platforms might expose power directly on the battery tuple
    if watts is None and battery is not None:
        for attr in ("power_watts", "power_now", "current_watts"):
            raw = getattr(battery, attr, None)
            if raw is None:
                continue
            try:
                watts = float(raw)
                break
            except (TypeError, ValueError):
                continue

    if watts is None:
        estimated = _estimate_power_draw()
        if estimated is not None:
            watts = estimated
            payload["status"] = "estimated"
            payload["detail"] = "Estimated from CPU utilization"

    if watts is not None:
        payload["watts"] = round(watts, 2)
        if payload["status"] not in ("ok", "estimated"):
            payload["status"] = "ok"
        if payload["status"] == "ok":
            payload["detail"] = None
        span = max(0.0, POWER_MAX_WATTS - POWER_IDLE_WATTS)
        if span > 0:
            utilization = (watts - POWER_IDLE_WATTS) / span
            payload["power_utilization"] = max(0.0, min(1.0, utilization))
    else:
        if not payload["detail"]:
            payload["detail"] = "Power telemetry unavailable on this host."

    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            payload["ram_used_bytes"] = int(vm.used)
            payload["ram_total_bytes"] = int(vm.total)
            payload["ram_percent"] = round(float(vm.percent), 2)
        except Exception:
            payload["ram_percent"] = None
        try:
            usage = psutil.cpu_percent(interval=0.05)
            payload["cpu_usage_percent"] = round(float(usage), 1)
        except Exception:
            payload["cpu_usage_percent"] = None

    temp_value, temp_source = _read_cpu_temperature()
    if temp_value is not None:
        payload["cpu_temp_c"] = round(float(temp_value), 1)
        payload["temp_source"] = temp_source

    return payload

def _read_cpu_temperature():
    if psutil is None:
        return None, None
    temp_reader = getattr(psutil, "sensors_temperatures", None)
    if temp_reader is None:
        return None, None
    try:
        temps = temp_reader()
    except Exception:
        return None, None
    if not temps:
        return None, None

    preferred = [
        "coretemp",
        "k10temp",
        "cpu-thermal",
        "soc-thermal",
        "thermal-fan-est",
        "acpitz",
    ]

    def pick_entry(entries):
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is not None:
                return current
        return None

    for key in preferred:
        if key in temps:
            value = pick_entry(temps[key])
            if value is not None:
                return value, key

    for key, entries in temps.items():
        value = pick_entry(entries)
        if value is not None:
            return value, key
    return None, None

@app.get("/telemetry/power", response_model=PowerTelemetry)
async def telemetry_power():
    return PowerTelemetry(**get_power_metrics())

if __name__ == "__main__":
    print("=" * 60)
    print("IRIS Search API Server")
    print("=" * 60)
    print(f"Starting server on http://{API_HOST}:{API_PORT}")
    print("Endpoints:")
    print("  POST /search/web - Perform web search")
    print("  GET  /health - Health check")
    print("=" * 60)
    
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info"
    )
