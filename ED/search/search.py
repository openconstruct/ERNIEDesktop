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
import signal
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    import psutil
except ImportError:  # pragma: no cover - psutil should exist but degrade gracefully
    psutil = None

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

# LLM Server management
CHAT_DIR = os.getenv("CHAT_DIR", "")
LLM_MODEL_DIR = os.getenv("LLM_MODEL_DIR", "")
LLM_HOST = os.getenv("LLM_HOST", "127.0.0.1")
LLM_PORT = os.getenv("LLM_PORT", "8080")
LLAMA_ARGS = os.getenv("LLAMA_ARGS", "--threads 7 --ctx-size 2048 --batch-size 4 --mlock")
LLAMA_PID_FILE = os.getenv("LLAMA_PID_FILE", "/tmp/ernie_llama.pid")
LLAMA_LOG_FILE = os.getenv("LLAMA_LOG_FILE", "")

# Find .env file location
ENV_FILE_PATH = None
if CHAT_DIR:
    # Try parent directory of CHAT_DIR
    potential_env = Path(CHAT_DIR).parent / ".env"
    if potential_env.exists():
        ENV_FILE_PATH = str(potential_env)

def _update_env_file(model_filename: str):
    """Update LLM_MODEL_PATH in .env file to persist model selection"""
    if not ENV_FILE_PATH:
        print("Warning: Could not locate .env file to save model selection")
        return False

    try:
        # Read current .env file
        with open(ENV_FILE_PATH, 'r') as f:
            lines = f.readlines()

        # Update LLM_MODEL_PATH line
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('LLM_MODEL_PATH='):
                lines[i] = f'LLM_MODEL_PATH={model_filename}\n'
                updated = True
                break

        # If line doesn't exist, add it after LLM_MODEL_DIR
        if not updated:
            for i, line in enumerate(lines):
                if line.startswith('LLM_MODEL_DIR='):
                    lines.insert(i + 1, f'LLM_MODEL_PATH={model_filename}\n')
                    updated = True
                    break

        # Write back to file
        if updated:
            with open(ENV_FILE_PATH, 'w') as f:
                f.writelines(lines)
            print(f"Saved model selection to .env: {model_filename}")
            return True
        else:
            print("Warning: Could not find LLM_MODEL_PATH or LLM_MODEL_DIR in .env file")
            return False

    except Exception as e:
        print(f"Error updating .env file: {e}")
        return False

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
    vram_used_bytes: Optional[int] = None
    vram_total_bytes: Optional[int] = None
    vram_percent: Optional[float] = None
    vram_source: Optional[str] = None
    gpu_driver: Optional[str] = None
    vulkan_available: Optional[bool] = None

class ModelInfo(BaseModel):
    name: str
    path: str
    size_bytes: int
    size_human: str
    is_current: bool

class ModelsResponse(BaseModel):
    models: List[ModelInfo]
    current_model: Optional[str]
    model_dir: str

class SwitchModelRequest(BaseModel):
    model_path: str

class SwitchModelResponse(BaseModel):
    success: bool
    message: str
    new_model: Optional[str] = None

def _format_size(bytes_size):
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def _get_current_model():
    """Get the currently loaded model from PID file"""
    if not os.path.exists(LLAMA_PID_FILE):
        return None
    try:
        with open(LLAMA_PID_FILE, 'r') as f:
            data = f.read().strip().split('\n')
            if len(data) >= 2:
                return data[1]  # Second line contains model path
    except Exception:
        pass
    return None

def _list_gguf_models():
    """List all .gguf models in the model directory"""
    # Use LLM_MODEL_DIR if set, otherwise fall back to CHAT_DIR for backward compatibility
    model_dir = LLM_MODEL_DIR if LLM_MODEL_DIR else CHAT_DIR

    if not model_dir or not os.path.isdir(model_dir):
        return []

    models = []
    current_model = _get_current_model()

    try:
        for file in os.listdir(model_dir):
            if file.endswith('.gguf'):
                full_path = os.path.join(model_dir, file)
                try:
                    size = os.path.getsize(full_path)
                    models.append(ModelInfo(
                        name=file,
                        path=full_path,
                        size_bytes=size,
                        size_human=_format_size(size),
                        is_current=(full_path == current_model or file == current_model)
                    ))
                except OSError:
                    continue
    except OSError:
        pass

    return sorted(models, key=lambda m: m.name)

def _stop_llama_server():
    """Stop the current llama-server process"""
    if not os.path.exists(LLAMA_PID_FILE):
        return True

    try:
        with open(LLAMA_PID_FILE, 'r') as f:
            pid = int(f.readline().strip())

        # Try graceful shutdown first
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            # Process already dead
            pass

        # Wait a bit for graceful shutdown
        for i in range(10):
            try:
                os.kill(pid, 0)  # Check if process exists
                time.sleep(0.5)
            except OSError:
                # Process is dead
                break

        # Force kill if still running
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except OSError:
            pass

        os.remove(LLAMA_PID_FILE)
        return True
    except Exception as e:
        print(f"Error stopping llama-server: {e}")
        return False

def _start_llama_server(model_path):
    """Start llama-server with the specified model"""
    if not CHAT_DIR:
        raise Exception("CHAT_DIR not configured")

    llama_binary = os.path.join(CHAT_DIR, "llama-server")
    if not os.path.exists(llama_binary):
        raise Exception(f"llama-server binary not found at {llama_binary}")

    # Build command
    cmd = [
        llama_binary,
        "-m", model_path,
        "--host", LLM_HOST,
        "--port", str(LLM_PORT)
    ]

    # Add additional args
    if LLAMA_ARGS:
        # Strip quotes if present and split
        args_str = LLAMA_ARGS.strip('"').strip("'")
        cmd.extend(args_str.split())

    # Start process
    log_file = LLAMA_LOG_FILE if LLAMA_LOG_FILE else "/tmp/llama.log"
    with open(log_file, 'a') as log:
        log.write(f"\n=== Starting llama-server at {datetime.now().isoformat()} ===\n")
        log.write(f"Model: {model_path}\n")
        log.write(f"Command: {' '.join(cmd)}\n\n")
        log.flush()

        process = subprocess.Popen(
            cmd,
            cwd=CHAT_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )

    # Verify process started
    time.sleep(0.5)
    try:
        os.kill(process.pid, 0)  # Check if process exists
    except OSError:
        raise Exception("llama-server process failed to start")

    # Write PID and model to file
    with open(LLAMA_PID_FILE, 'w') as f:
        f.write(f"{process.pid}\n{model_path}")

    print(f"Started llama-server with PID {process.pid}")
    return process.pid

@app.get("/")
async def root():
    return {
        "service": "IRIS Search API",
        "version": "1.0.0",
        "model": API_MODEL,
        "endpoints": {
            "search": "/search/web (POST)",
            "health": "/health (GET)",
            "telemetry": "/telemetry/power (GET)",
            "models": "/models (GET)",
            "switch_model": "/models/switch (POST)"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/models", response_model=ModelsResponse)
async def list_models():
    """List all available GGUF models in the model directory"""
    models = _list_gguf_models()
    current_model = _get_current_model()
    model_dir = LLM_MODEL_DIR if LLM_MODEL_DIR else CHAT_DIR

    return ModelsResponse(
        models=models,
        current_model=current_model,
        model_dir=model_dir or ""
    )

@app.post("/models/switch", response_model=SwitchModelResponse)
async def switch_model(request: SwitchModelRequest):
    """Switch to a different GGUF model"""
    if not CHAT_DIR:
        raise HTTPException(status_code=503, detail="Model switching not configured (CHAT_DIR not set)")

    model_path = request.model_path

    # Validate model exists
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")

    if not model_path.endswith('.gguf'):
        raise HTTPException(status_code=400, detail="Model must be a .gguf file")

    try:
        # Stop current server
        print(f"Stopping current llama-server...")
        _stop_llama_server()

        # Start with new model
        print(f"Starting llama-server with model: {model_path}")
        pid = _start_llama_server(model_path)

        model_name = os.path.basename(model_path)

        # Save model selection to .env file for persistence
        _update_env_file(model_name)

        return SwitchModelResponse(
            success=True,
            message=f"Successfully switched to {model_name} (PID: {pid})",
            new_model=model_path
        )
    except Exception as e:
        return SwitchModelResponse(
            success=False,
            message=f"Failed to switch model: {str(e)}",
            new_model=None
        )

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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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

    # VRAM metrics
    vram_used, vram_total, vram_source = _read_vram()
    if vram_used is not None:
        payload["vram_used_bytes"] = int(vram_used)
        payload["vram_total_bytes"] = int(vram_total) if vram_total is not None else None
        # Calculate percentage only if total is available and non-zero
        if vram_total and vram_total > 0:
            payload["vram_percent"] = round((vram_used / vram_total) * 100, 2)
        else:
            payload["vram_percent"] = None  # Shared memory case
        payload["vram_source"] = vram_source

    # GPU driver and Vulkan detection
    payload["gpu_driver"] = _detect_gpu_driver()
    payload["vulkan_available"] = _check_vulkan_available()

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

def _read_nvidia_vram():
    """
    Read VRAM from NVIDIA GPU using nvidia-smi command.
    Returns GPU with most VRAM if multiple GPUs present.
    """
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            best_gpu = None
            max_vram = 0

            # Find GPU with most VRAM
            for idx, line in enumerate(lines):
                parts = line.split(',')
                if len(parts) == 2:
                    try:
                        used_mb = float(parts[0].strip())
                        total_mb = float(parts[1].strip())

                        if total_mb > max_vram:
                            max_vram = total_mb
                            best_gpu = (used_mb, total_mb, idx)
                    except ValueError:
                        continue

            if best_gpu:
                used_mb, total_mb, gpu_idx = best_gpu
                source = f"nvidia-smi:gpu{gpu_idx}" if len(lines) > 1 else "nvidia-smi"
                return int(used_mb * 1024 * 1024), int(total_mb * 1024 * 1024), source
    except FileNotFoundError:
        # nvidia-smi not installed
        pass
    except (subprocess.TimeoutExpired, ValueError, OSError):
        # Command failed or timed out
        pass
    return None, None, None

def _read_amd_vram():
    """
    Read VRAM from AMD GPU using rocm-smi command or sysfs fallback.
    Returns GPU with most VRAM if multiple GPUs present.
    """
    # 1. Try rocm-smi first (requires ROCm installation)
    try:
        result = subprocess.run(
            ['rocm-smi', '--showmeminfo', 'vram', '--json'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                import json
                data = json.loads(result.stdout)
                # ROCm JSON format varies, try to parse it
                # This is a best-effort parser for common formats
                if isinstance(data, dict):
                    best_gpu = None
                    max_vram = 0

                    for gpu_id, gpu_data in data.items():
                        if isinstance(gpu_data, dict):
                            vram_info = gpu_data.get('VRAM Total Memory (B)', {})
                            if isinstance(vram_info, dict):
                                total = int(vram_info.get('value', 0))
                                used = int(gpu_data.get('VRAM Total Used Memory (B)', {}).get('value', 0))
                                if total > max_vram:
                                    max_vram = total
                                    best_gpu = (used, total, gpu_id)

                    if best_gpu:
                        used, total, gpu_id = best_gpu
                        source = f"rocm-smi:gpu{gpu_id}" if len(data) > 1 else "rocm-smi"
                        return used, total, source
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    except FileNotFoundError:
        # rocm-smi not installed
        pass
    except (subprocess.TimeoutExpired, OSError):
        # Command failed or timed out
        pass

    # 2. Try CSV format as fallback
    try:
        result = subprocess.run(
            ['rocm-smi', '--showmeminfo', 'vram', '--csv'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            best_gpu = None
            max_vram = 0

            for idx, line in enumerate(lines[1:], 0):  # Skip header
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    try:
                        # Format: GPU, Used, Total
                        used_mb = float(parts[1])
                        total_mb = float(parts[2])

                        if total_mb > max_vram:
                            max_vram = total_mb
                            best_gpu = (used_mb, total_mb, idx)
                    except ValueError:
                        continue

            if best_gpu:
                used_mb, total_mb, gpu_idx = best_gpu
                source = f"rocm-smi:gpu{gpu_idx}" if len(lines) > 2 else "rocm-smi"
                return int(used_mb * 1024 * 1024), int(total_mb * 1024 * 1024), source
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass

    # 3. Fallback to sysfs for AMD GPUs (works without ROCm)
    try:
        drm_path = '/sys/class/drm'
        if os.path.exists(drm_path):
            best_card = None
            max_vram = 0

            # Find all card* directories and track the one with most VRAM
            for entry in sorted(os.listdir(drm_path)):
                if not entry.startswith('card') or '-' in entry:
                    continue

                vram_used_path = os.path.join(drm_path, entry, 'device', 'mem_info_vram_used')
                vram_total_path = os.path.join(drm_path, entry, 'device', 'mem_info_vram_total')

                if os.path.exists(vram_used_path) and os.path.exists(vram_total_path):
                    try:
                        with open(vram_used_path, 'r') as f:
                            used = int(f.read().strip())
                        with open(vram_total_path, 'r') as f:
                            total = int(f.read().strip())

                        # Track card with most VRAM
                        if total > max_vram:
                            max_vram = total
                            best_card = (used, total, entry)
                    except (ValueError, OSError):
                        continue

            # Return the card with most VRAM
            if best_card:
                return best_card[0], best_card[1], f"amdgpu-sysfs:{best_card[2]}"
    except (FileNotFoundError, OSError):
        pass

    return None, None, None

def _read_intel_vram():
    """
    Read VRAM from Intel GPU using debugfs.
    Intel integrated GPUs share system RAM, so this is best-effort.
    """
    # Try to read from debugfs if available (requires root or appropriate permissions)
    try:
        debugfs_path = '/sys/kernel/debug/dri'
        if os.path.exists(debugfs_path):
            # Try all DRI devices
            for entry in sorted(os.listdir(debugfs_path)):
                gem_path = os.path.join(debugfs_path, entry, 'i915_gem_objects')
                if os.path.exists(gem_path):
                    try:
                        with open(gem_path, 'r') as f:
                            content = f.read()
                            # Parse output for memory usage
                            for line in content.split('\n'):
                                if 'total' in line.lower() and 'bytes' in line.lower():
                                    # This is a simplified parser, actual format varies by kernel version
                                    parts = line.split()
                                    for i, part in enumerate(parts):
                                        if 'bytes' in part.lower() and i > 0:
                                            try:
                                                used = int(parts[i-1])
                                                # Intel doesn't expose total easily, return 0 for total
                                                # to indicate shared memory
                                                return used, 0, f"intel-debugfs:{entry}"
                                            except ValueError:
                                                continue
                    except (PermissionError, OSError):
                        # Debugfs often requires root
                        continue
    except (FileNotFoundError, OSError):
        pass

    return None, None, None

def _read_vram():
    """
    Read VRAM usage by checking for available tools in order of preference.
    Tries: nvidia-smi -> rocm-smi -> AMD sysfs -> Intel debugfs
    """
    # 1. Try nvidia-smi (NVIDIA GPUs)
    used, total, source = _read_nvidia_vram()
    if used is not None:
        return used, total, source

    # 2. Try rocm-smi (AMD discrete GPUs with ROCm)
    used, total, source = _read_amd_vram()
    if used is not None:
        return used, total, source

    # 3. Try Intel methods (integrated GPUs)
    used, total, source = _read_intel_vram()
    if used is not None:
        return used, total, source

    return None, None, None

def _detect_gpu_driver():
    """Detect which GPU driver is being used"""
    try:
        drm_path = '/sys/class/drm'
        if os.path.exists(drm_path):
            for entry in sorted(os.listdir(drm_path)):
                if not entry.startswith('card') or '-' in entry:
                    continue

                uevent_path = os.path.join(drm_path, entry, 'device', 'uevent')
                if os.path.exists(uevent_path):
                    with open(uevent_path, 'r') as f:
                        for line in f:
                            if line.startswith('DRIVER='):
                                driver = line.strip().split('=')[1]
                                return driver
    except (FileNotFoundError, OSError):
        pass
    return None

def _check_vulkan_available():
    """Check if Vulkan is available on the system"""
    # Check for Vulkan loader library
    vulkan_libs = [
        '/usr/lib64/libvulkan.so.1',
        '/usr/lib/x86_64-linux-gnu/libvulkan.so.1',
        '/usr/lib/libvulkan.so.1',
        '/usr/local/lib/libvulkan.so.1'
    ]

    for lib in vulkan_libs:
        if os.path.exists(lib):
            return True

    # Check if vulkaninfo exists
    try:
        result = subprocess.run(['which', 'vulkaninfo'], capture_output=True, timeout=1)
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False

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
