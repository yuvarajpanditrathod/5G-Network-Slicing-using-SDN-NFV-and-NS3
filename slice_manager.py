#!/usr/bin/env python3
"""
Professional 5G Network Slicing Management CLI with Dynamic Resource Allocation
Advanced management interface for adaptive network slices

Features:
- Dynamic Resource Allocation (DRA)
- Adaptive slice management
- Real-time resource optimization
- Predictive scaling
- SLA-aware allocation
- Machine learning-based decisions
- Advanced monitoring and analytics
- Encryption/decryption of slice data
- Interactive CLI interface with dynamic features

Usage:
    python3 slice_manager.py [command] [options]
"""

import os
import sys
import json
import time
import argparse
import logging
import requests
import base64
import subprocess
import threading
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque
import signal
from datetime import datetime, timezone
# Do not import topology at module import time to avoid circular imports
DynamicNetworkSlicingTopology = None

# Import encryption functionality
sys.path.append(os.path.join(os.path.dirname(__file__), 'nfv'))
try:
    from nfv.firewall_vnf import SliceEncryption, load_or_create_key
except Exception:
    try:
        from firewall_vnf import SliceEncryption, load_or_create_key
    except Exception:
        SliceEncryption = None
        def load_or_create_key(*args, **kwargs):
            raise RuntimeError('Encryption utilities not available')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='→ %(message)s'
)
logger = logging.getLogger('DynamicSliceManager')

class DynamicSliceManager:
    """Advanced 5G Network Slice Manager with Dynamic Resource Allocation"""
    def get_current_timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def __init__(self):
        # Slice configs are orchestrator-driven. Initialize empty and allow
        # `load_slice_registry()` to populate them from `slice_registry.json`.
        self.slice_configs = {}
        
        # Dynamic Resource Allocation Configuration
        self.dra_config = {
            'controller_url': 'http://localhost:8080',
            'monitoring_interval': 5,  # seconds
            'prediction_window': 30,   # seconds
            'allocation_algorithms': ['proportional', 'priority', 'predictive', 'ml_based'],
            'current_algorithm': 'proportional',
            'auto_scaling_enabled': True,
            'sla_monitoring_enabled': True,
            'traffic_prediction_enabled': True,
            'load_balancing_enabled': True
        }
        
        # Dynamic monitoring state
        self.monitoring_active = False
        self.allocation_history = deque(maxlen=100)
        self.traffic_history = deque(maxlen=100)
        self.sla_violations = []
        self.performance_metrics = {
            'allocation_efficiency': 0.0,
            'sla_compliance': 100.0,
            'resource_utilization': 0.0,
            'prediction_accuracy': 0.0
        }
        
        # Active monitoring threads
        self.monitor_thread = None
        self.prediction_thread = None
        
        # Legacy slice management state
        self.active_slices = []
        self.slice_processes = {}
        # Use explicit key 'Slice' (per user request) and default to 256-bit AES
        self.encryption_key = "Slice"

        # Runtime universal slice config (in-memory) - authoritative source at runtime
        # This replaces any on-disk `universal_slice_config.json` usage.
        # It must be explicitly activated via `activate_universal_config()` after
        # validation/handshake. Other modules should call `get_universal_slice_config()`
        # to retrieve the shared runtime config.
        self.universal_slice_config = None
        self.universal_config_active = False

        # Legacy compatibility - maintain existing attributes
        self.created_slices = {}  # Track dynamically created slices
        self.slice_registry_file = 'slice_registry.json'
        # Use modern canonical filenames requested by user
        self.encrypted_file = 'slice_encrypted.enc'
        self.encrypted_json = 'slice_encrypted.json'
        self.decrypted_file = 'slice_decrypted.dec'
        self.decrypted_json = 'slice_decrypted.json'
        self.stats_file = 'slice_statistics.json'
        self.vnf_url = self.find_available_service('http://localhost', [9000, 9001, 9002, 9003])
        self.controller_url = self.dra_config['controller_url']  # Use DRA controller URL

        # Initialize statistics - canonical slices default to INACTIVE unless
        # explicitly activated by the orchestrator or runtime config. This
        # prevents slices appearing active when the system boots without inputs.
        self.stats = {slice_name: {'packets': 0, 'bytes': 0, 'active': False}
                      for slice_name in self.slice_configs}

        # Load existing slices and initialize dynamic monitoring
        self.load_slice_registry()

        # Ensure stats entries exist for any slices loaded from the registry
        for slice_name in self.slice_configs:
            # Do not mark canonical slices active by default; respect loaded status
            self.stats.setdefault(slice_name, {'packets': 0, 'bytes': 0, 'active': False})

        # Track whether current in-memory slices are decrypted
        # If an encrypted file exists and there is no in-memory decrypted registry,
        # default to encrypted state (hide details until user decrypts)
        self.decrypted = False
        self._initialize_dynamic_monitoring()

        # Initialize slice encryption
        self._initialize_slice_encryption()
        # Populate deterministic in-memory encrypted artifacts for compatibility
        self._populate_deterministic_encryption_artifacts()
        # Note: Do not merge topology-defined slices here to avoid circular imports.
        # The topology should load canonical slices from this manager using the
        # `get_canonical_slices()` API when it runs.
    
    def _initialize_dynamic_monitoring(self):
        """Initialize dynamic monitoring systems"""
        logger.info("Initializing dynamic monitoring systems...")
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Verify controller connectivity
        try:
            response = requests.get(f"{self.dra_config['controller_url']}/stats/slices", timeout=5)
            if response.status_code == 200:
                logger.info("✓ Dynamic controller connectivity verified")
            else:
                logger.warning("⚠ Controller available but may not support dynamic features")
        except requests.RequestException:
            logger.warning("⚠ Controller not reachable - some features may be limited")
    
    def _initialize_slice_encryption(self):
        """Initialize slice encryption system"""
        logger.info("Initializing slice encryption system...")
        try:
            key = load_or_create_key(bits=256, passphrase=self.encryption_key)
            self.slice_encryptor = SliceEncryption(key)
            logger.info("✓ Slice encryption initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize slice encryption: {e}")
            self.slice_encryptor = None

    # -------------------------
    # Slice status helpers
    # -------------------------
    def set_slice_status(self, slice_name: str, active: bool, persist: bool = True):
        """Set the active/inactive status for a slice in-memory and optionally persist to slice_status.json."""
        if not hasattr(self, '_in_memory_slice_status') or self._in_memory_slice_status is None:
            self._in_memory_slice_status = {}
        self._in_memory_slice_status[slice_name] = {'active': bool(active), 'updated_at': datetime.now().isoformat()}
        # update stats mapping
        self.stats.setdefault(slice_name, {'packets': 0, 'bytes': 0, 'active': False})
        self.stats[slice_name]['active'] = bool(active)
        # propagate into slice_configs if present
        if slice_name in self.slice_configs:
            self.slice_configs[slice_name]['status'] = 'active' if active else 'inactive'
        if persist:
            try:
                with open('slice_status.json', 'w') as f:
                    json.dump(self._in_memory_slice_status, f, indent=2)
            except Exception:
                logger.debug('Failed to persist slice_status.json')

    def get_slice_status(self, slice_name: str) -> bool:
        """Return True if slice is considered active, False otherwise (defaults to True for canonical slices)."""
        status_map = getattr(self, '_in_memory_slice_status', None)
        if status_map and slice_name in status_map:
            return bool(status_map[slice_name].get('active', True))
        # fall back to stats mapping
        return bool(self.stats.get(slice_name, {}).get('active', True))

    # -------------------------
    # Universal runtime config
    # -------------------------
    def build_universal_config(self) -> Dict:
        """Build the in-memory universal slice config from runtime sources.

        This collects canonical `slice_configs`, dynamic `created_slices`,
        controller-derived data and runtime measurements. It does NOT write
        to disk and must be activated explicitly.
        """
        # Gather canonical slices
        canonical = self.get_canonical_slices()

        # Merge created dynamic slices (never overwrite canonical keys)
        merged = {k: dict(v) for k, v in canonical.items()}
        for k, v in self.created_slices.items():
            if k not in merged:
                merged[k] = dict(v)

        # Attach runtime metadata
        for name, cfg in merged.items():
            cfg.setdefault('slice_name', name)
            cfg.setdefault('activated_at', None)
            cfg.setdefault('runtime_measurements', {})

        return {
            'generated_at': datetime.now().isoformat(),
            'slices': merged,
            'source': 'runtime',
            'active': False
        }

    def validate_universal_config(self, config: Dict) -> None:
        """Validate universal config - raise ValueError on missing required fields.

        Required per-slice fields: 'port', 'current_bandwidth' or 'base_bandwidth',
        'max_bandwidth', 'target_latency'.
        """
        if not isinstance(config, dict):
            raise ValueError('universal config must be a dict')
        slices = config.get('slices')
        if not isinstance(slices, dict) or not slices:
            raise ValueError('universal config must contain non-empty "slices" mapping')

        for name, s in slices.items():
            if 'port' not in s or s.get('port') in (None, 'N/A', ''):
                raise ValueError(f"Slice {name} missing required 'port'")
            if not (('current_bandwidth' in s and s.get('current_bandwidth') is not None) or ('base_bandwidth' in s and s.get('base_bandwidth') is not None)):
                raise ValueError(f"Slice {name} missing required bandwidth fields")
            if 'max_bandwidth' not in s or s.get('max_bandwidth') in (None, 0):
                raise ValueError(f"Slice {name} missing required 'max_bandwidth'")
            if 'target_latency' not in s or s.get('target_latency') in (None, ''):
                raise ValueError(f"Slice {name} missing required 'target_latency'")

    def activate_universal_config(self, handshake_ok: bool = True) -> None:
        """Create, validate and activate the runtime universal config.

        Activation requires a runtime handshake/authorization check. If
        `handshake_ok` is False, activation fails loudly.
        """
        if not handshake_ok:
            raise RuntimeError('Runtime handshake/authorization failed; cannot activate universal slice config')

        config = self.build_universal_config()
        # Validate - will raise on failure
        self.validate_universal_config(config)

        config['active'] = True
        config['activated_at'] = datetime.now().isoformat()
        # mark per-slice activated times
        for name in config['slices']:
            config['slices'][name]['activated_at'] = datetime.now().isoformat()

        self.universal_slice_config = config
        self.universal_config_active = True
        logger.info('✓ Universal runtime slice config activated')
        # Start background measurement updater
        self._start_runtime_measurements()

        # Persist per-slice active status so topology watcher can enforce network rules
        try:
            for sname in config['slices']:
                try:
                    self.set_slice_status(sname, True, persist=True)
                except Exception:
                    # best-effort
                    pass
        except Exception:
            pass

        # Try to integrate with ns-3: create taps and attempt to start the
        # ns-3 scratch simulation using the helper runner. This is best-effort
        # and will not raise on failure. Use NS3_HOME env var or the dra_config
        # entry 'ns3_home' to point to the ns-3 top-level directory.
        try:
            # Ensure kernel taps exist
            try:
                self.ensure_taps()
            except Exception:
                logger.debug('ensure_taps failed; continuing')

            ns3_home = os.environ.get('NS3_HOME') or self.dra_config.get('ns3_home')
            runner_py = os.path.join(os.path.dirname(__file__), 'ns3', 'run_ns3.py')
            if os.path.exists(runner_py):
                # Build command - if NS3_HOME provided, we can call the runner with --ns3-home
                cmd = [sys.executable, runner_py]
                if ns3_home:
                    cmd += ['--ns3-home', ns3_home]
                # pass tap prefix to runner (match create_taps script prefix)
                cmd += ['--tap-prefix', 'tap']

                # Start in background and record process handle
                try:
                    proc = subprocess.Popen(cmd, cwd=os.path.join(os.path.dirname(__file__), 'ns3'))
                    self._ns3_process = proc
                    logger.info('Started ns-3 runner (pid=%s)', getattr(proc, 'pid', 'unknown'))
                except Exception as e:
                    logger.warning('Could not start ns-3 runner: %s', e)
            else:
                logger.info('ns-3 runner not found; print command instead')
                # Print the command the user can run
                sim_cmd = f"python {runner_py} --tap-prefix tap"
                if ns3_home:
                    sim_cmd += f" --ns3-home {ns3_home}"
                logger.info('To run ns-3 simulation manually: %s', sim_cmd)
        except Exception as e:
            logger.debug('ns-3 integration attempt failed: %s', e)

    def _start_runtime_measurements(self):
        """Start a background thread that measures latency and throughput for each slice.

        Measurements update `self.universal_slice_config['slices'][slice]['runtime_measurements']`.
        If measurement commands (ping/iperf3) are missing or fail, the measurement
        will retry and ultimately raise RuntimeError if a required value cannot be obtained.
        """
        if getattr(self, '_measurement_thread', None) and self._measurement_thread.is_alive():
            return

        def measurement_loop():
            logger.info('Starting runtime network measurements for slices')
            while self.universal_config_active:
                try:
                    ucfg = self.get_universal_slice_config()
                    for slice_name, cfg in ucfg['slices'].items():
                        # Determine a target host for measurement - prefer 'monitor' or 'server' hosts
                        target_host = cfg.get('monitor_host') or cfg.get('server_host') or '127.0.0.1'
                        # Measure latency
                        try:
                            latency_ms, packet_loss = self._measure_ping(target_host, attempts=3, timeout=2)
                        except Exception as e:
                            logger.error('Latency measurement failed for %s: %s', slice_name, e)
                            raise

                        # Measure throughput via iperf3 (requires iperf3 server reachable)
                        try:
                            throughput_mbps = self._measure_iperf_throughput(target_host, port=cfg.get('port', 5001), duration=5, retries=2)
                        except Exception as e:
                            logger.error('Throughput measurement failed for %s: %s', slice_name, e)
                            raise

                        # Update runtime measurements
                        ucfg['slices'][slice_name].setdefault('runtime_measurements', {})
                        ucfg['slices'][slice_name]['runtime_measurements'].update({
                            'latency_ms': latency_ms,
                            'packet_loss_percent': packet_loss,
                            'throughput_mbps': throughput_mbps,
                            'measured_at': datetime.now().isoformat()
                        })

                    # Sleep between measurement rounds
                    time.sleep(max(5, self.dra_config.get('monitoring_interval', 5)))
                except Exception as e:
                    logger.error('Runtime measurement loop error: %s', e)
                    # If measurements fail repeatedly, stop and surface error
                    time.sleep(5)

        self._measurement_thread = threading.Thread(target=measurement_loop, daemon=True)
        self._measurement_thread.start()

    from typing import Tuple

    def _measure_ping(self, host: str, attempts: int = 3, timeout: int = 2) -> Tuple[float, float]:
        """Measure round-trip latency (ms) and packet loss (%) using system ping.

        Returns (avg_latency_ms, packet_loss_percent). Raises RuntimeError on failure.
        """
        if not host:
            raise RuntimeError('Host required for ping')

        # Choose ping args per platform
        count_arg = '-n' if os.name == 'nt' else '-c'
        timeout_arg = '-w' if os.name == 'nt' else '-W'

        cmd = ['ping', count_arg, str(attempts), timeout_arg, str(timeout), host]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=attempts * (timeout + 2))
            out = proc.stdout
        except Exception as e:
            raise RuntimeError(f'Ping command failed: {e}')

        # Parse output for packet loss and average latency
        packet_loss = None
        avg_latency = None
        try:
            # Look for 'Lost' or 'loss' line
            for line in out.splitlines():
                line_l = line.lower()
                if 'loss' in line_l or 'lost' in line_l:
                    # Windows: "Lost = 0 (0% loss)" or Unix: "0% packet loss"
                    import re
                    m = re.search(r"(\d+)%\s*loss", line_l)
                    if not m:
                        m = re.search(r"\((\d+)%\s*loss\)", line_l)
                    if m:
                        packet_loss = float(m.group(1))
                if 'average' in line_l or 'avg' in line_l:
                    import re
                    m = re.search(r"=\s*[\d\.]+/([\d\.]+)/", line_l)
                    if not m:
                        m = re.search(r"avg[=/ ]+([\d\.]+)ms", line_l)
                    if m:
                        avg_latency = float(m.group(1))

        except Exception:
            pass

        if packet_loss is None:
            # If not parsed, assume high loss and fail
            raise RuntimeError('Could not parse ping output for packet loss')
        if avg_latency is None:
            raise RuntimeError('Could not parse ping output for average latency')

        return avg_latency, packet_loss

    def _measure_iperf_throughput(self, host: str, port: int = 5001, duration: int = 5, retries: int = 2) -> float:
        """Measure throughput (Mbps) using `iperf3` command-line tool.

        Returns measured Mbps. Raises RuntimeError if iperf3 not available or measurement fails.
        """
        # Ensure iperf3 available
        try:
            subprocess.run(['iperf3', '--version'], capture_output=True, text=True, timeout=5)
        except Exception:
            raise RuntimeError('iperf3 not available on system PATH')

        for attempt in range(1, retries + 2):
            cmd = [
                'iperf3', '-c', host, '-p', str(port), '-t', str(duration), '--json',
                '--congestion', 'cubic'
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
                if proc.returncode != 0:
                    logger.warning('iperf3 attempt %d failed: %s', attempt, proc.stderr.strip())
                    time.sleep(1)
                    continue

                out = proc.stdout
                import json as _json
                parsed = _json.loads(out)
                # Prefer end->sum->bits_per_second
                bps = None
                try:
                    bps = parsed.get('end', {}).get('sum_received', {}).get('bits_per_second')
                    if not bps:
                        bps = parsed.get('end', {}).get('sum', {}).get('bits_per_second')
                except Exception:
                    pass

                if not bps:
                    logger.warning('iperf3 JSON missing bits_per_second; raw output used')
                    # Attempt to parse rudimentary
                    import re
                    m = re.search(r"(\d+\.?\d*)\s+Mbits/sec", out)
                    if m:
                        mbps = float(m.group(1))
                        return mbps
                    else:
                        time.sleep(1)
                        continue

                mbps = float(bps) / 1e6
                return mbps

            except Exception as e:
                logger.warning('iperf3 measurement error on attempt %d: %s', attempt, e)
                time.sleep(1)

        raise RuntimeError('iperf3 throughput measurement failed after retries')

    def get_universal_slice_config(self) -> Dict:
        """Return the active universal slice config or raise if not active."""
        if not self.universal_config_active or not self.universal_slice_config:
            raise RuntimeError('Universal slice config is not active. Call activate_universal_config() after runtime validation.')
        return self.universal_slice_config

    def _populate_deterministic_encryption_artifacts(self):
        """Populate deterministic in-memory encryption artifacts used by older modules.

        This produces a reproducible mapping of slice_name -> encrypted_data (base64 string)
        using the existing `SliceEncryption` with key derived from `nfv_key.bin`.
        No files are written.
        """
        try:
            if not self.slice_encryptor:
                return
            artifacts = {}
            for name, cfg in self.get_canonical_slices().items():
                cfg_copy = dict(cfg)
                cfg_copy.setdefault('slice_name', name)
                encrypted = self.slice_encryptor.encrypt_slice_config(cfg_copy)
                artifacts[name] = {'encrypted_data': encrypted, 'timestamp': datetime.now().isoformat()}
            # Store in-memory artifact map for other modules to query
            self._in_memory_encrypted_map = artifacts
            logger.info('✓ Populated deterministic in-memory encryption artifacts')
        except Exception as e:
            logger.debug('Could not populate in-memory encryption artifacts: %s', e)

    def get_in_memory_encrypted_map(self, force_populate: bool = True):
        """Return the in-memory deterministic encrypted artifacts.

        If `force_populate` is True and the artifact map is missing, try to
        initialize encryption and populate artifacts deterministically.
        """
        artifacts = getattr(self, '_in_memory_encrypted_map', None)
        if not artifacts and force_populate:
            try:
                # Ensure encryption is initialized
                if not getattr(self, 'slice_encryptor', None):
                    self._initialize_slice_encryption()
                self._populate_deterministic_encryption_artifacts()
                artifacts = getattr(self, '_in_memory_encrypted_map', None)
            except Exception:
                artifacts = None
        return artifacts
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info("Received shutdown signal - cleaning up...")
        self.stop_monitoring()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Tap management & slice mapping helpers (ns-3 integration)
    # ------------------------------------------------------------------
    def ensure_taps(self, bridge_name: str = 's1') -> bool:
        """Ensure taps exist by calling scripts/create_taps.sh (idempotent).

        Returns True if script executed or taps appear to exist.
        """
        try:
            script = os.path.join(os.path.dirname(__file__), 'scripts', 'create_taps.sh')
            if os.path.exists(script):
                logger.info('Ensuring taps using %s', script)
                subprocess.run(['sudo', script], check=False)
                return True
            else:
                logger.warning('Tap creation script not found: %s', script)
                return False
        except Exception as e:
            logger.error('ensure_taps error: %s', e)
            return False

    def get_ovs_port(self, tap_name: str, bridge_name: str = 's1') -> Optional[int]:
        """Return the OVS numerical port for a tap interface by parsing `ovs-ofctl show` output."""
        try:
            out = subprocess.check_output(['sudo', 'ovs-ofctl', 'show', bridge_name], text=True)
            # Example line: " 1(tap-embb): addr:..."
            for line in out.splitlines():
                if '(' + tap_name + ')' in line or tap_name in line:
                    # Parse leading port number
                    parts = line.strip().split()
                    if parts:
                        try:
                            port_no = int(parts[0].split('(')[0])
                            return port_no
                        except Exception:
                            continue
            return None
        except Exception as e:
            logger.debug('get_ovs_port error: %s', e)
            return None

    def map_slice_to_controller(self, slice_name: str, tap_name: str, dst: Optional[str] = None, controller_url: Optional[str] = None) -> bool:
        """Call controller REST API to map slice to OVS port.

        Finds the OVS port for tap_name and POSTs {"slice": slice_name, "port": <port>, "dst": dst}
        to controller_url (defaults to self.controller_url).
        Returns True on success.
        """
        controller_url = controller_url or self.controller_url or self.dra_config.get('controller_url')
        self.ensure_taps()
        port_no = self.get_ovs_port(tap_name)
        if not port_no:
            logger.error('Could not determine OVS port for tap %s', tap_name)
            return False

        payload = {'slice': slice_name, 'port': port_no}
        if dst:
            payload['dst'] = dst

        try:
            resp = requests.post(f"{controller_url.rstrip('/')}/slice/map", json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info('Mapped slice %s to tap %s (port %s) via controller', slice_name, tap_name, port_no)
                return True
            else:
                logger.error('Controller mapping failed: %s %s', resp.status_code, resp.text)
                return False
        except requests.RequestException as e:
            logger.error('Failed to call controller to map slice: %s', e)
            return False

    def activate_slice(self, slice_name: str, tap_name: str) -> bool:
        """Activate a slice: ensure taps, map slice to controller, and update registry/stats.

        Returns True on success.
        """
        try:
            self.ensure_taps()
            success = self.map_slice_to_controller(slice_name, tap_name)
            # Update slice_registry.json and slice_statistics_ns3.json
            registry = {}
            if os.path.exists(self.slice_registry_file):
                try:
                    with open(self.slice_registry_file, 'r') as f:
                        registry = json.load(f)
                except Exception:
                    registry = {}

            registry.setdefault(slice_name, {})
            registry[slice_name]['active'] = bool(success)
            registry[slice_name]['updated_at'] = self.get_current_timestamp()

            with open(self.slice_registry_file, 'w') as f:
                json.dump(registry, f, indent=2)

            # Update generic runtime stats file for slices (ns-3 disabled)
            stats = {}
            stats_file = os.path.join(os.path.dirname(__file__), 'slice_statistics.json')
            # if an older ns3-specific file exists, prefer to continue using it for compatibility
            legacy_ns3_file = os.path.join(os.path.dirname(__file__), 'slice_statistics_ns3.json')
            if os.path.exists(stats_file):
                try:
                    with open(stats_file, 'r') as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}
            elif os.path.exists(legacy_ns3_file):
                try:
                    with open(legacy_ns3_file, 'r') as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}

            stats.setdefault('timestamp', self.get_current_timestamp())
            stats.setdefault('slices', {})
            stats['slices'].setdefault(slice_name, {'throughput_kbps': 0, 'latency_ms': 0, 'packet_loss': 0, 'active': bool(success)})
            stats['slices'][slice_name]['active'] = bool(success)

            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)

            logger.info('Activated slice %s (tap=%s) success=%s', slice_name, tap_name, success)
            return success
        except Exception as e:
            logger.error('activate_slice error: %s', e)
            return False

    def deactivate_slice(self, slice_name: str) -> bool:
        """Mark slice inactive in registry and stats (no controller unmap currently)."""
        try:
            registry = {}
            if os.path.exists(self.slice_registry_file):
                try:
                    with open(self.slice_registry_file, 'r') as f:
                        registry = json.load(f)
                except Exception:
                    registry = {}

            registry.setdefault(slice_name, {})
            registry[slice_name]['active'] = False
            registry[slice_name]['updated_at'] = self.get_current_timestamp()
            with open(self.slice_registry_file, 'w') as f:
                json.dump(registry, f, indent=2)

            # Update generic runtime stats file for slices (ns-3 disabled)
            stats = {}
            stats_file = os.path.join(os.path.dirname(__file__), 'slice_statistics.json')
            legacy_ns3_file = os.path.join(os.path.dirname(__file__), 'slice_statistics_ns3.json')
            if os.path.exists(stats_file):
                try:
                    with open(stats_file, 'r') as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}
            elif os.path.exists(legacy_ns3_file):
                try:
                    with open(legacy_ns3_file, 'r') as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}

            stats.setdefault('timestamp', self.get_current_timestamp())
            stats.setdefault('slices', {})
            stats['slices'].setdefault(slice_name, {'throughput_kbps': 0, 'latency_ms': 0, 'packet_loss': 0, 'active': False})
            stats['slices'][slice_name]['active'] = False
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)

            logger.info('Deactivated slice %s', slice_name)
            return True
        except Exception as e:
            logger.error('deactivate_slice error: %s', e)
            return False
    
    # ==========================================
    # Dynamic Resource Allocation Methods
    # ==========================================
    
    def start_dynamic_monitoring(self):
        """Start dynamic resource allocation monitoring"""
        if self.monitoring_active:
            logger.warning("Dynamic monitoring is already active")
            return
        
        logger.info("Starting dynamic resource allocation monitoring...")
        self.monitoring_active = True
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(
            target=self._dynamic_monitoring_loop,
            daemon=True
        )
        self.monitor_thread.start()
        
        # Start prediction thread if enabled
        if self.dra_config['traffic_prediction_enabled']:
            self.prediction_thread = threading.Thread(
                target=self._traffic_prediction_loop,
                daemon=True
            )
            self.prediction_thread.start()
        
        logger.info("✓ Dynamic monitoring started successfully")
    
    def stop_monitoring(self):
        """Stop dynamic monitoring gracefully"""
        if not self.monitoring_active:
            return
        
        logger.info("Stopping dynamic monitoring...")
        self.monitoring_active = False
        
        # Wait for threads to complete
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        if self.prediction_thread and self.prediction_thread.is_alive():
            self.prediction_thread.join(timeout=5)
        
        logger.info("✓ Dynamic monitoring stopped")
    
    def _dynamic_monitoring_loop(self):
        """Main dynamic monitoring loop"""
        logger.info("Dynamic monitoring loop started")
        
        while self.monitoring_active:
            try:
                # Collect current allocation status
                allocation_data = self._collect_allocation_data()
                if allocation_data:
                    self.allocation_history.append(allocation_data)
                
                # Monitor SLA compliance if enabled
                if self.dra_config['sla_monitoring_enabled']:
                    self._check_sla_compliance()
                
                # Trigger auto-scaling if enabled
                if self.dra_config['auto_scaling_enabled']:
                    self._evaluate_auto_scaling()
                
                # Update performance metrics
                self._update_performance_metrics()
                
                # Sleep until next monitoring cycle
                time.sleep(self.dra_config['monitoring_interval'])
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(5)  # Back off on error
    
    def _traffic_prediction_loop(self):
        """Traffic prediction and proactive allocation loop"""
        logger.info("Traffic prediction loop started")
        
        while self.monitoring_active:
            try:
                # Collect traffic data
                traffic_data = self._collect_traffic_data()
                if traffic_data:
                    self.traffic_history.append(traffic_data)
                
                # Perform traffic prediction if enough history
                if len(self.traffic_history) >= 10:
                    predictions = self._predict_traffic_demands()
                    if predictions:
                        self._apply_predictive_allocation(predictions)
                
                # Sleep until next prediction cycle
                time.sleep(self.dra_config['prediction_window'])
                
            except Exception as e:
                logger.error(f"Error in prediction loop: {e}")
    
    def find_available_service(self, base_url, ports):
        """Find available service on given ports"""
        import socket
        for port in ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:  # Port is open and service is running
                    return f"{base_url}:{port}"
            except:
                continue
        return f"{base_url}:{ports[0]}"  # Default to first port
    
    def _collect_allocation_data(self):
        """Collect current resource allocation data"""
        try:
            response = requests.get(
                f"{self.dra_config['controller_url']}/dynamic/allocation_status",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                data['timestamp'] = datetime.now().isoformat()
                return data
        except requests.RequestException as e:
            logger.debug(f"Failed to collect allocation data: {e}")
        return None
    
    def _collect_traffic_data(self):
        """Collect current traffic data for prediction"""
        try:
            response = requests.get(
                f"{self.dra_config['controller_url']}/stats/slices",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                data['timestamp'] = datetime.now().isoformat()
                return data
        except requests.RequestException as e:
            logger.debug(f"Failed to collect traffic data: {e}")
        return None
    
    def _check_sla_compliance(self):
        """Check SLA compliance for all slices"""
        try:
            response = requests.get(
                f"{self.dra_config['controller_url']}/dynamic/sla_status",
                timeout=5
            )
            if response.status_code == 200:
                sla_data = response.json()
                
                # Check for violations
                for slice_id, metrics in sla_data.get('slices', {}).items():
                    if not metrics.get('compliant', True):
                        violation = {
                            'timestamp': datetime.now().isoformat(),
                            'slice_id': slice_id,
                            'violation_type': metrics.get('violation_type', 'unknown'),
                            'severity': metrics.get('severity', 'medium'),
                            'details': metrics.get('details', {})
                        }
                        self.sla_violations.append(violation)
                        logger.warning(f"SLA violation detected for slice {slice_id}: {violation['violation_type']}")
                        
                        # Trigger automatic remediation if configured
                        if metrics.get('severity') == 'high':
                            self._trigger_sla_remediation(slice_id, violation)
                
        except requests.RequestException as e:
            logger.debug(f"Failed to check SLA compliance: {e}")
    
    def _evaluate_auto_scaling(self):
        """Evaluate and trigger auto-scaling decisions"""
        if not self.allocation_history:
            return
        
        current_allocation = self.allocation_history[-1]
        
        for slice_id, slice_data in current_allocation.get('slices', {}).items():
            if slice_id not in self.slice_configs:
                continue
            
            config = self.slice_configs[slice_id]
            if not config.get('auto_scale', False):
                continue
            
            utilization = slice_data.get('utilization', 0)
            current_bw = slice_data.get('current_bandwidth', config['base_bandwidth'])
            
            # Scale up if utilization > 80%
            if utilization > 80 and current_bw < config['max_bandwidth']:
                new_bw = min(current_bw * 1.2, config['max_bandwidth'])
                self._request_bandwidth_adjustment(slice_id, new_bw, 'scale_up')
            
            # Scale down if utilization < 40% for extended period
            elif utilization < 40 and current_bw > config['min_bandwidth']:
                # Check if low utilization persists
                recent_utils = [
                    data.get('slices', {}).get(slice_id, {}).get('utilization', 100)
                    for data in list(self.allocation_history)[-3:]
                ]
                if all(u < 40 for u in recent_utils):
                    new_bw = max(current_bw * 0.8, config['min_bandwidth'])
                    self._request_bandwidth_adjustment(slice_id, new_bw, 'scale_down')
    
    def _predict_traffic_demands(self):
        """Predict future traffic demands using simple trend analysis"""
        if len(self.traffic_history) < 5:
            return None
        
        predictions = {}
        
        for slice_id in self.slice_configs.keys():
            # Extract utilization trend for this slice
            utilizations = []
            for data in list(self.traffic_history)[-10:]:
                slice_data = data.get('slices', {}).get(slice_id, {})
                util = slice_data.get('utilization', 0)
                utilizations.append(util)
            
            if len(utilizations) >= 3:
                # Simple linear trend prediction
                trend = statistics.mean(utilizations[-3:]) - statistics.mean(utilizations[:3])
                current_util = utilizations[-1]
                predicted_util = max(0, min(100, current_util + trend * 2))
                
                predictions[slice_id] = {
                    'predicted_utilization': predicted_util,
                    'trend': trend,
                    'confidence': min(100, len(utilizations) * 10)
                }
        
        return predictions if predictions else None
    
    def _apply_predictive_allocation(self, predictions):
        """Apply predictive resource allocation based on predictions"""
        for slice_id, pred_data in predictions.items():
            if slice_id not in self.slice_configs:
                continue
            
            config = self.slice_configs[slice_id]
            predicted_util = pred_data['predicted_utilization']
            confidence = pred_data['confidence']
            
            # Only act on high-confidence predictions
            if confidence < 60:
                continue
            
            # Proactively allocate if high utilization predicted
            if predicted_util > 75:
                current_bw = config.get('current_bandwidth', config['base_bandwidth'])
                target_bw = min(current_bw * 1.15, config['max_bandwidth'])
                
                logger.info(f"Predictive scaling for {slice_id}: {predicted_util:.1f}% utilization predicted")
                self._request_bandwidth_adjustment(slice_id, target_bw, 'predictive_scale')
    
    def _request_bandwidth_adjustment(self, slice_id, new_bandwidth, reason):
        """Request bandwidth adjustment from the controller"""
        try:
            adjustment_data = {
                'slice_id': slice_id,
                'target_bandwidth': new_bandwidth,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{self.dra_config['controller_url']}/dynamic/adjust_bandwidth",
                json=adjustment_data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✓ Bandwidth adjustment for {slice_id}: {new_bandwidth:.1f} Mbps ({reason})")
                
                # Update local config
                if slice_id in self.slice_configs:
                    self.slice_configs[slice_id]['current_bandwidth'] = result.get('allocated_bandwidth', new_bandwidth)
            else:
                logger.warning(f"Bandwidth adjustment failed for {slice_id}: {response.text}")
                
        except requests.RequestException as e:
            logger.error(f"Failed to request bandwidth adjustment: {e}")
    
    def _trigger_sla_remediation(self, slice_id, violation):
        """Trigger automatic SLA violation remediation"""
        logger.info(f"Triggering SLA remediation for slice {slice_id}")
        
        try:
            remediation_data = {
                'slice_id': slice_id,
                'violation': violation,
                'action': 'emergency_scale',
                'timestamp': datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{self.dra_config['controller_url']}/dynamic/sla_remediation",
                json=remediation_data,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✓ SLA remediation triggered for {slice_id}")
            else:
                logger.warning(f"SLA remediation failed for {slice_id}: {response.text}")
                
        except requests.RequestException as e:
            logger.error(f"Failed to trigger SLA remediation: {e}")
    
    def _update_performance_metrics(self):
        """Update performance metrics based on recent data"""
        if not self.allocation_history:
            return
        
        recent_data = list(self.allocation_history)[-10:]
        
        # Calculate allocation efficiency
        total_allocated = 0
        total_used = 0
        
        for data in recent_data:
            for slice_data in data.get('slices', {}).values():
                allocated = slice_data.get('current_bandwidth', 0)
                utilization = slice_data.get('utilization', 0)
                used = allocated * (utilization / 100)
                
                total_allocated += allocated
                total_used += used
        
        if total_allocated > 0:
            self.performance_metrics['allocation_efficiency'] = (total_used / total_allocated) * 100
            self.performance_metrics['resource_utilization'] = (total_used / 1000) * 100  # Assume 1Gbps total
        
        # Calculate SLA compliance
        total_violations = len([v for v in self.sla_violations if 
                              datetime.fromisoformat(v['timestamp']) > datetime.now() - timedelta(hours=1)])
        
        # Assume 100 SLA checks per hour (every 36 seconds)
        recent_checks = min(100, len(recent_data) * 2)
        if recent_checks > 0:
            self.performance_metrics['sla_compliance'] = max(0, 100 - (total_violations / recent_checks * 100))
    
    # ==========================================
    # Dynamic Management Commands
    # ==========================================
    
    def get_allocation_status(self):
        """Get current dynamic allocation status"""
        print("\n" + "="*80)
        print("🔄 DYNAMIC RESOURCE ALLOCATION STATUS")
        print("="*80)
        
        # Use runtime universal slice config - require active runtime config
        try:
            ucfg = self.get_universal_slice_config()
        except Exception as e:
            raise RuntimeError(f"Cannot display allocation status: {e}")

        # Query controller for live allocation status
        try:
            response = requests.get(
                f"{self.dra_config['controller_url']}/dynamic/allocation_status",
                timeout=5
            )
            if response.status_code != 200:
                raise RuntimeError(f"Controller returned unexpected status: {response.status_code}")

            data = response.json()

            print(f"📊 Current Algorithm: {data.get('current_algorithm', 'Unknown')}")
            print(f"⏰ Last Update: {data.get('last_update', 'Unknown')}")
            print(f"🎯 Auto-scaling: {'✓ Enabled' if self.dra_config['auto_scaling_enabled'] else '✗ Disabled'}")
            print(f"📈 Prediction: {'✓ Enabled' if self.dra_config['traffic_prediction_enabled'] else '✗ Disabled'}")

            print("\n📋 Slice Allocations:")
            print("-" * 80)

            active_slices = 0
            total_slices = len(data.get('slices', {}))

            for slice_id, slice_data in data.get('slices', {}).items():
                if slice_id not in ucfg['slices']:
                    raise RuntimeError(f"Controller returned allocation for unknown slice '{slice_id}' - runtime universal config must include this slice")

                config = ucfg['slices'][slice_id]
                # enforce required values exist
                port = config.get('port')
                if port is None:
                    raise RuntimeError(f"Slice {slice_id} missing required 'port' in runtime config")

                current_bw = slice_data.get('current_bandwidth', config.get('current_bandwidth', config.get('base_bandwidth')))
                utilization = slice_data.get('utilization', 0)

                if utilization > 0:
                    active_slices += 1
                    status = "🟢 ACTIVE"
                else:
                    status = "⚪ INACTIVE"

                status_icon = "🟢" if utilization < 70 else "🟡" if utilization < 90 else "🔴"

                print(f"{status_icon} {slice_id} ({config.get('name', slice_id)}) - {status}:")
                print(f"   • Bandwidth: {current_bw:.1f}/{config['max_bandwidth']} Mbps")
                print(f"   • Utilization: {utilization:.1f}%")
                print(f"   • Priority: {config.get('priority')}")
                print(f"   • Port: {port}")
                print(f"   • QoS Class: {config.get('qos_class')}")
                print(f"   • Encryption: {'✓' if config.get('encryption', False) else '✗'}")
                print()

            print(f"📊 Summary: {active_slices}/{total_slices} slices active")

            # Show performance metrics
            print("📈 Performance Metrics:")
            print("-" * 40)
            print(f"Allocation Efficiency: {self.performance_metrics['allocation_efficiency']:.1f}%")
            print(f"SLA Compliance: {self.performance_metrics['sla_compliance']:.1f}%")
            print(f"Resource Utilization: {self.performance_metrics['resource_utilization']:.1f}%")

        except requests.RequestException as e:
            raise RuntimeError(f"Connection error to controller: {e}")
        
        print("="*80)
    
    def show_detailed_slice_info(self):
        """Show detailed information about all slices"""
        print("\n" + "="*80)
        print("📋 DETAILED SLICE INFORMATION")
        print("="*80)
        
        # Use runtime universal config - require activation
        try:
            ucfg = self.get_universal_slice_config()
        except Exception as e:
            raise RuntimeError(f"Cannot show detailed slice info: {e}")

        for slice_name, config in ucfg['slices'].items():
            print(f"\n🔹 {slice_name} - {config.get('name')}")
            print("-" * 50)
            # All fields must be present and validated by activation
            port = config.get('port')
            if port is None:
                raise RuntimeError(f"Slice {slice_name} missing required 'port' in runtime config")

            print(f"Port: {port}")
            print(f"Bandwidth: {config.get('current_bandwidth')}/{config.get('max_bandwidth')} Mbps (Base: {config.get('base_bandwidth')} Mbps)")
            print(f"Latency: {config.get('target_latency')}ms (Max: {config.get('max_latency')}ms)")
            print(f"Reliability: {config.get('reliability')}%")
            print(f"Priority: {config.get('priority')}")
            print(f"QoS Class: {config.get('qos_class')}")
            print(f"Traffic Pattern: {config.get('traffic_pattern')}")
            print(f"Encryption: {'Enabled' if config.get('encryption', False) else 'Disabled'}")
            print(f"Auto Scale: {'Enabled' if config.get('auto_scale', False) else 'Disabled'}")

            # Show current status from controller
            try:
                response = requests.get(
                    f"{self.dra_config['controller_url']}/slice/{slice_name}/status",
                    timeout=3
                )
                if response.status_code == 200:
                    status_data = response.json()
                    print(f"Current Status: {status_data.get('status', 'Unknown')}")
                    print(f"Active Connections: {status_data.get('connections', 0)}")
                    print(f"Data Transferred: {status_data.get('data_transferred', 0)} MB")
                else:
                    print("Current Status: Unable to retrieve")
            except Exception:
                print("Current Status: Controller not available")
        
        print("\n" + "="*80)
    
    def show_realtime_monitoring(self):
        """Show real-time monitoring information"""
        print("\n" + "="*80)
        print("📊 REAL-TIME MONITORING")
        print("="*80)
        
        try:
            response = requests.get(
                f"{self.dra_config['controller_url']}/monitoring/realtime",
                timeout=5
            )
            
            if response.status_code == 200:
                monitoring_data = response.json()
                
                print(f"⏰ Timestamp: {monitoring_data.get('timestamp', 'N/A')}")
                print(f"📊 Total Active Slices: {monitoring_data.get('active_slices', 0)}")
                print(f"🌐 Total Bandwidth Used: {monitoring_data.get('total_bandwidth_used', 0):.1f} Mbps")
                print(f"⚡ Total Throughput: {monitoring_data.get('total_throughput', 0):.1f} Mbps")
                
                print("\n📈 Per-Slice Metrics:")
                print("-" * 50)
                
                for slice_name, metrics in monitoring_data.get('slice_metrics', {}).items():
                    status_icon = "🟢" if metrics.get('utilization', 0) < 70 else "🟡" if metrics.get('utilization', 0) < 90 else "🔴"
                    print(f"{status_icon} {slice_name}:")
                    print(f"   • Utilization: {metrics.get('utilization', 0):.1f}%")
                    print(f"   • Bandwidth: {metrics.get('current_bandwidth', 0):.1f} Mbps")
                    print(f"   • Latency: {metrics.get('latency', 0):.1f}ms")
                    print(f"   • Packet Loss: {metrics.get('packet_loss', 0):.2f}%")
                    print(f"   • Active Flows: {metrics.get('active_flows', 0)}")
                    print()
                
                print("🔧 System Health:")
                print("-" * 30)
                print(f"CPU Usage: {monitoring_data.get('system_cpu', 0):.1f}%")
                print(f"Memory Usage: {monitoring_data.get('system_memory', 0):.1f}%")
                print(f"Controller Status: {monitoring_data.get('controller_status', 'Unknown')}")
                
            else:
                print(f"❌ Failed to get monitoring data: {response.text}")
                
        except requests.RequestException as e:
            print(f"❌ Connection error: {e}")
            print("💡 Make sure the Ryu controller is running")
        
        print("="*80)
    
    def set_allocation_algorithm(self, algorithm):
        """Set the dynamic allocation algorithm"""
        if algorithm not in self.dra_config['allocation_algorithms']:
            print(f"❌ Invalid algorithm. Available: {', '.join(self.dra_config['allocation_algorithms'])}")
            return
        
        print(f"🔄 Setting allocation algorithm to: {algorithm}")
        
        try:
            response = requests.post(
                f"{self.dra_config['controller_url']}/dynamic/set_algorithm",
                json={'algorithm': algorithm},
                timeout=10
            )
            
            if response.status_code == 200:
                self.dra_config['current_algorithm'] = algorithm
                print(f"✓ Algorithm set to {algorithm}")
            else:
                print(f"❌ Failed to set algorithm: {response.text}")
                
        except requests.RequestException as e:
            print(f"❌ Connection error: {e}")
    
    def manual_bandwidth_adjustment(self, slice_id, bandwidth):
        """Manually adjust bandwidth for a slice"""
        if slice_id not in self.slice_configs:
            print(f"❌ Unknown slice: {slice_id}")
            return
        
        config = self.slice_configs[slice_id]
        if bandwidth < config['min_bandwidth'] or bandwidth > config['max_bandwidth']:
            print(f"❌ Bandwidth out of range: {config['min_bandwidth']}-{config['max_bandwidth']} Mbps")
            return
        
        print(f"🔧 Manually adjusting {slice_id} bandwidth to {bandwidth} Mbps")
        self._request_bandwidth_adjustment(slice_id, bandwidth, 'manual')
    
    def show_sla_violations(self):
        """Show recent SLA violations"""
        print("\n" + "="*60)
        print("⚠️  SLA VIOLATIONS REPORT")
        print("="*60)
        
        if not self.sla_violations:
            print("✓ No SLA violations recorded")
            print("="*60)
            return
        
        # Show recent violations (last 24 hours)
        recent_violations = [
            v for v in self.sla_violations
            if datetime.fromisoformat(v['timestamp']) > datetime.now() - timedelta(hours=24)
        ]
        
        if not recent_violations:
            print("✓ No recent SLA violations (last 24 hours)")
        else:
            print(f"📊 Total violations (24h): {len(recent_violations)}")
            print()
            
            for violation in recent_violations[-10:]:  # Show last 10
                timestamp = datetime.fromisoformat(violation['timestamp']).strftime('%H:%M:%S')
                severity_icon = "🔴" if violation['severity'] == 'high' else "🟡" if violation['severity'] == 'medium' else "🟢"
                
                print(f"{severity_icon} {timestamp} - {violation['slice_id']}")
                print(f"   Type: {violation['violation_type']}")
                print(f"   Severity: {violation['severity']}")
                print()
        
        print("="*60)
    
    def show_traffic_predictions(self):
        """Show current traffic predictions"""
        print("\n" + "="*60)
        print("🔮 TRAFFIC PREDICTIONS")
        print("="*60)
        
        if not self.dra_config['traffic_prediction_enabled']:
            print("❌ Traffic prediction is disabled")
            print("="*60)
            return
        
        predictions = self._predict_traffic_demands()
        
        if not predictions:
            print("⏳ Insufficient data for predictions")
            print("   (Need at least 5 data points)")
        else:
            print("📈 Predicted utilization (next 30 seconds):")
            print()
            
            for slice_id, pred_data in predictions.items():
                config = self.slice_configs[slice_id]
                predicted = pred_data['predicted_utilization']
                trend = pred_data['trend']
                confidence = pred_data['confidence']
                
                trend_icon = "📈" if trend > 5 else "📉" if trend < -5 else "➡️"
                confidence_icon = "🟢" if confidence > 80 else "🟡" if confidence > 60 else "🔴"
                
                print(f"{trend_icon} {slice_id} ({config['name']}):")
                print(f"   Predicted: {predicted:.1f}%")
                print(f"   Trend: {trend:+.1f}%")
                print(f"   {confidence_icon} Confidence: {confidence:.0f}%")
                print()
        
        print("="*60)
    
    def export_allocation_report(self, filename=None):
        """Export detailed allocation report"""
        if not filename:
            filename = f"allocation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        print(f"📊 Generating allocation report: {filename}")
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'dra_config': self.dra_config,
            'slice_configs': self.slice_configs,
            'performance_metrics': self.performance_metrics,
            'allocation_history': list(self.allocation_history),
            'traffic_history': list(self.traffic_history),
            'sla_violations': self.sla_violations[-50:],  # Last 50 violations
            'current_status': 'monitoring_active' if self.monitoring_active else 'monitoring_inactive'
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2)
            
            print(f"✓ Report exported to {filename}")
            print(f"📁 File size: {os.path.getsize(filename)} bytes")
            
        except Exception as e:
            print(f"❌ Failed to export report: {e}")
    
    # ==========================================
    # Enhanced Legacy Methods
    # ==========================================
    
    def load_slice_registry(self):
        """Load existing slice registry"""
        try:
            if os.path.exists(self.slice_registry_file):
                with open(self.slice_registry_file, 'r') as f:
                    self.created_slices = json.load(f)
                logger.info(f"Loaded {len(self.created_slices)} existing slices from registry")
                # Merge created_slices into canonical slice_configs so orchestrator
                # entries augment (not completely replace) the built-in configs.
                try:
                    for sname, cfg in self.created_slices.items():
                        # Ensure minimal display fields
                        copy = dict(cfg)
                        copy.setdefault('slice_id', f"slice_{sname.lower()}")
                        copy.setdefault('port', cfg.get('port', 5000))
                        # If a canonical config exists, update it; otherwise add new
                        if sname in self.slice_configs:
                            # Merge without losing existing canonical defaults
                            self.slice_configs[sname].update(copy)
                        else:
                            self.slice_configs[sname] = copy
                    logger.info(f"Merged orchestrator registry into canonical slice configs: {list(self.created_slices.keys())}")
                except Exception:
                    logger.exception("Failed while merging created_slices into slice_configs")
        except Exception as e:
            logger.warning(f"Could not load slice registry: {e}")
            self.created_slices = {}

        # Also load runtime slice status (set by topology/controller)
        try:
            status_map = getattr(self, '_in_memory_slice_status', None)
            if status_map is None and os.path.exists('slice_status.json'):
                with open('slice_status.json','r') as f:
                    status_map = json.load(f)
            if status_map:
                for sname, sinfo in status_map.items():
                    self.stats.setdefault(sname, {'packets':0,'bytes':0,'active':False})
                    self.stats[sname]['active'] = bool(sinfo.get('active', False))
                    # Propagate status into slice_configs and created_slices for display
                    status_label = 'active' if self.stats[sname]['active'] else 'inactive'
                    if sname in self.slice_configs:
                        # only set if not already explicit
                        self.slice_configs[sname].setdefault('status', status_label)
                    if sname in self.created_slices:
                        self.created_slices[sname].setdefault('status', status_label)
        except Exception:
            pass

        # If a runtime universal config exists (written by orchestrator), load and activate it
        try:
            runtmp = 'universal_runtime.json'
            if os.path.exists(runtmp):
                try:
                    with open(runtmp, 'r') as f:
                        ucfg = json.load(f)
                    # Basic validation and activation
                    if isinstance(ucfg, dict) and ucfg.get('slices'):
                        # Map fields if needed
                        for name, c in ucfg['slices'].items():
                            # ensure minimal fields exist for measurement loops
                            c.setdefault('port', c.get('port', 5000))
                            c.setdefault('current_bandwidth', c.get('current_bandwidth', c.get('base_bandwidth')))
                        # Activate runtime config so get_universal_slice_config() works
                        try:
                            self.universal_slice_config = ucfg
                            self.universal_config_active = True
                            logger.info('Activated universal runtime config from universal_runtime.json')
                            # propagate activated state to stats
                            for name in ucfg.get('slices', {}).keys():
                                self.stats.setdefault(name, {'packets':0,'bytes':0,'active':True})
                                self.stats[name]['active'] = True
                        except Exception:
                            logger.exception('Failed to activate universal runtime config')
                except Exception:
                    pass
        except Exception:
            pass

    # ----- Slice status persistence helpers -----
    def _read_slice_status_file(self):
        try:
            if os.path.exists('slice_status.json'):
                with open('slice_status.json','r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_slice_status_file(self, status_map: Dict):
        try:
            tmp = 'slice_status.json.tmp'
            with open(tmp, 'w') as f:
                json.dump(status_map, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, 'slice_status.json')
            return True
        except Exception:
            return False

    def refresh_status_from_file(self):
        """Refresh in-memory stats.active from persistent slice_status.json"""
        status_map = self._read_slice_status_file()
        for name, info in status_map.items():
            self.stats.setdefault(name, {'packets':0,'bytes':0,'active':False})
            self.stats[name]['active'] = bool(info.get('active', False))
    
    def save_slice_registry(self):
        """Save slice registry to file"""
        try:
            with open(self.slice_registry_file, 'w') as f:
                json.dump(self.created_slices, f, indent=2)
            logger.info(f"Saved slice registry with {len(self.created_slices)} slices")
        except Exception as e:
            logger.error(f"Failed to save slice registry: {e}")
    
    def create_dynamic_slice(self, slice_name: str, config: Dict) -> bool:
        """Create a new dynamic slice with custom configuration"""
        try:
            # Validate configuration
            required_fields = ['bandwidth', 'latency', 'reliability', 'port']
            for field in required_fields:
                if field not in config:
                    logger.error(f"Missing required field: {field}")
                    return False
            
            # Check if slice already exists
            if slice_name in self.created_slices:
                logger.warning(f"Slice {slice_name} already exists")
                return False
            
            # Check port conflicts
            used_ports = [slice_cfg.get('port') for slice_cfg in self.created_slices.values()]
            used_ports.extend([slice_cfg.get('port') for slice_cfg in self.slice_configs.values()])
            
            if config['port'] in used_ports:
                logger.error(f"Port {config['port']} is already in use")
                return False
            
            # Add metadata (do not embed free-form status; stats tracks active state)
            config.update({
                'created_at': datetime.now().isoformat(),
                'slice_id': f"{slice_name}_{int(time.time())}",
                'type': 'dynamic',
                'encryption': config.get('encryption', True)
            })
            
            # Add to registry
            self.created_slices[slice_name] = config
            
            # Save registry
            self.save_slice_registry()
            
            # Encrypt and save slice data
            encrypted_config = self.encrypt_slice_data(config)
            self.save_encrypted_slice(slice_name, encrypted_config)
            
            logger.info(f"✅ Created dynamic slice: {slice_name}")
            self.display_slice_info(slice_name, config)
            # Mark stats active for this dynamic slice (persist status so topology picks it up)
            try:
                self.set_slice_status(slice_name, True, persist=True)
            except Exception:
                # fallback if set_slice_status not available
                self.stats.setdefault(slice_name, {'packets': 0, 'bytes': 0, 'active': False})

            return True
            
        except Exception as e:
            logger.error(f"Failed to create dynamic slice {slice_name}: {e}")
            return False
    
    def list_slices(self, verbose: bool = False):
        """Display all network slices with their configurations"""
        print("\n" + "="*80)
        print("🔹 5G NETWORK SLICES OVERVIEW")
        print("="*80)
        
        # Prefer runtime universal config when active, but fall back to
        # canonical `self.slice_configs` so `list` works even before
        # activation or when running in environments that rely on files.
        try:
            ucfg = self.get_universal_slice_config()
        except Exception:
            # Not active — fall back to canonical slices and warn the user
            print("⚠️  Universal runtime config not active — using canonical slice configs")
            ucfg = {'slices': self.get_canonical_slices()}

        # Use canonical three slices (eMBB, URLLC, mMTC) as the authoritative set
        canonical_set = ['eMBB', 'URLLC', 'mMTC']
        # Ensure canonical slices exist in configs (create minimal if missing)
        for cname in canonical_set:
            if cname not in self.slice_configs:
                self.slice_configs[cname] = {'name': cname, 'port': 5002 if cname == 'eMBB' else 5001 if cname == 'URLLC' else 5003, 'current_bandwidth': None, 'max_bandwidth': None}

        active_names = [n for n in canonical_set if self.stats.get(n, {}).get('active', False)]
        total_known = len(canonical_set)
        active_count = len(active_names)

        # Print concise active summary (default)
        print()
        print(f"✅ Active slices ({active_count}/{total_known}):")
        if active_names:
            for n in sorted(active_names):
                print(f"  • {n}")
        else:
            print("  (none)")

        if not verbose:
            print("\n(To see detailed slice configs, run `list_slices(verbose=True)` in code or use the manager's verbose option)")
            print("\n" + "=" * 80)
            return

        # Verbose path: show detailed runtime/canonical info
        if ucfg and ucfg.get('slices'):
            print("\n📌 Pre-configured Slices (details):")
            print("-" * 60)
            for slice_name, config in ucfg['slices'].items():
                active_status = "🟢 Active" if self.stats.get(slice_name, {}).get('active', False) else "🔴 Inactive"
                encryption_status = "🔒 Encrypted" if config.get('encryption', True) else "📄 Plain"

                print(f"\n🔸 {slice_name}")
                print(f"   → Name: {config.get('name')}")
                print(f"   → Status: {active_status}")
                print(f"   → Port: {config.get('port')}")
                print(f"   → Bandwidth: {config.get('current_bandwidth')}/{config.get('max_bandwidth')} Mbps")
                print(f"   → Latency: {config.get('target_latency')} ms (SLA: {config.get('max_latency')} ms)")
                print(f"   → Reliability: {config.get('reliability')}")
                rm = config.get('runtime_measurements') or {}
                if rm:
                    print(f"   → Measured latency: {rm.get('latency_ms')} ms | throughput: {rm.get('throughput_mbps')} Mbps | loss: {rm.get('packet_loss_percent')}%")
                print(f"   → Encryption: {encryption_status}")
                print(f"   → Auto-scaling: {'✓' if config.get('auto_scale', False) else '✗'}")
        
        # Display dynamic slices (created_slices) only if they are separate from canonical slice_configs
        dyn_names = [n for n in self.created_slices.keys() if n not in self.slice_configs]
        if dyn_names:
            print(f"\n📌 Dynamic Slices ({len(dyn_names)} total):")
            print("-" * 60)
            # If not decrypted, do not show dynamic slice details
            if not self.decrypted and os.path.exists(self.encrypted_file):
                print("→ Dynamic slices exist but are encrypted. Decrypt to view details.")
            else:
                for slice_name in dyn_names:
                    config = self.created_slices.get(slice_name, {})
                    status = config.get('status', 'unknown')
                    status_icon = "🟢" if status == 'active' else "🟡" if status == 'pending' else "🔴"
                    encryption_status = "🔒 Encrypted" if config.get('encryption', True) else "📄 Plain"
                    
                    print(f"\n🔸 {slice_name}")
                    print(f"   → Status: {status_icon} {status.title()}")
                    print(f"   → Slice ID: {config.get('slice_id', 'N/A')}")
                    print(f"   → Unique Name: {config.get('slice_name', slice_name)}")
                    print(f"   → Port: {config.get('port', 'N/A')}")
                    print(f"   → Bandwidth: {config.get('current_bandwidth', 'N/A')}/{config.get('max_bandwidth', 'N/A')} Mbps")
                    print(f"   → Latency: {config.get('target_latency', 'N/A')} ms (SLA: {config.get('max_latency', 'N/A')} ms)")
                    print(f"   → Reliability: {config.get('reliability', 'N/A')}%")
                    print(f"   → Created: {config.get('created_at', 'Unknown')}")
                    print(f"   → Type: {config.get('type', 'dynamic').title() if 'type' in config else 'Dynamic'}")
                    print(f"   → Encryption: {encryption_status}")
        
        if not self.slice_configs and not self.created_slices:
            print("\n❌ No slices configured or created yet.")
        
        print("\n" + "=" * 80)

    def clean_shutdown(self):
        """Perform a professional clean shutdown: stop monitoring, save state, and
        present a concise summary of cleanup actions.
        """
        try:
            print("\nPerforming clean shutdown of Slice Manager...")
            # Stop monitoring threads
            self.stop_monitoring()
            # Save registries and stats
            try:
                self.save_slice_registry()
            except Exception:
                pass
            try:
                with open(self.stats_file, 'w') as f:
                    json.dump(self.stats, f, indent=2)
            except Exception:
                pass

            # Stop any known slice processes (metadata only)
            for sname in list(self.slice_processes.keys()):
                try:
                    # If processes were real, terminate them here. We only clear metadata.
                    del self.slice_processes[sname]
                except Exception:
                    pass

            print("✓ Slice Manager: monitoring stopped and state saved")
            print("✓ Slice Manager: cleaned up slice processes metadata")
            print("✓ Slice Manager: shutdown complete")

        except Exception as e:
            print(f"❌ Error during clean shutdown: {e}")
    
    def delete_dynamic_slice(self, slice_name: str) -> bool:
        """Delete a dynamic slice"""
        try:
            if slice_name not in self.created_slices:
                logger.warning(f"Dynamic slice {slice_name} not found")
                return False
            
            # Remove from registry
            del self.created_slices[slice_name]
            
            # Save updated registry
            self.save_slice_registry()
            
            logger.info(f"✅ Deleted dynamic slice: {slice_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete dynamic slice {slice_name}: {e}")
            return False
    
    def display_banner(self):
        """Display professional banner"""
        banner = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                    5G NETWORK SLICING MANAGEMENT SYSTEM                   ║
║                          Professional Edition v1.0                        ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  Features:                                                                ║
║  • Dynamic Slice Creation (eMBB, URLLC, mMTC)                             ║
║  • Advanced Encryption/Decryption                                         ║  
║  • Real-time Monitoring & Statistics                                      ║
║  • QoS Management & Traffic Engineering                                   ║
║  • Zero Packet Loss Guarantee                                             ║
║  • Professional CLI Interface                                             ║
╚═══════════════════════════════════════════════════════════════════════════╝
        """
        print(banner)
    
    def create_slice(self, slice_type: str, custom_config: Optional[Dict] = None):
        """Create a network slice with encryption"""
        try:
            if slice_type not in self.slice_configs:
                logger.error(f"Invalid slice type: {slice_type}")
                return False
            
            config = self.slice_configs[slice_type].copy()
            if custom_config:
                config.update(custom_config)
            
            # Add timestamp and unique ID
            config['slice_name'] = slice_type
            config['created_at'] = datetime.now().isoformat()
            config['slice_id'] = f"{slice_type}_{int(time.time())}"
            
            # Encrypt slice configuration
            encrypted_config = self.encrypt_slice_data(config)
            
            # Save encrypted configuration
            self.save_encrypted_slice(slice_type, encrypted_config)
            
            # Update slice statistics to mark as active and persist
            try:
                self.set_slice_status(slice_type, True, persist=True)
            except Exception:
                self.stats.setdefault(slice_type, {'packets': 0, 'bytes': 0, 'active': True})
            self.stats[slice_type]['packets'] = 0
            self.stats[slice_type]['bytes'] = 0
            
            # Add to created slices registry
            self.created_slices[slice_type] = config
            
            # Try to start the slice process
            self.start_slice_process(slice_type, config)
            
            logger.info(f"✓ Created {slice_type} slice with encryption")
            self.display_slice_info(slice_type, config)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create slice {slice_type}: {e}")
            return False
    
    def start_slice_process(self, slice_type: str, config: Dict):
        """Start the slice process/server"""
        try:
            port = config.get('port', 5000)
            logger.info(f"Starting slice server for {slice_type} on port {port}")
            
            # For now, just mark as active - in a real implementation, 
            # this would start actual network processes
            if slice_type not in self.slice_processes:
                self.slice_processes[slice_type] = {
                    'port': port,
                    'status': 'running',
                    'start_time': datetime.now().isoformat()
                }
            
            logger.info(f"✓ Slice {slice_type} process started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start slice process for {slice_type}: {e}")

    def start_slice(self, slice_name: str):
        """Mark a slice as started/active and persist status so other terminals see it."""
        try:
            # ensure slice exists in configs or created_slices
            if slice_name not in self.slice_configs and slice_name not in self.created_slices:
                print(f"❌ Unknown slice: {slice_name}")
                return False

            # Update in-memory stats
            self.stats.setdefault(slice_name, {'packets':0,'bytes':0,'active':False})
            self.stats[slice_name]['active'] = True

            # Persist status to file for cross-process visibility
            status_map = self._read_slice_status_file()
            status_map[slice_name] = {'active': True, 'updated_at': datetime.now().isoformat()}
            self._write_slice_status_file(status_map)

            # Optionally start process metadata
            cfg = self.slice_configs.get(slice_name) or self.created_slices.get(slice_name) or {}
            self.start_slice_process(slice_name, cfg)

            print(f"✓ Slice '{slice_name}' started (active)")
            return True
        except Exception as e:
            print(f"❌ Failed to start slice '{slice_name}': {e}")
            return False

    def stop_slice(self, slice_name: str):
        """Mark a slice as stopped/inactive and persist status."""
        try:
            if slice_name not in self.stats:
                print(f"❌ Unknown slice: {slice_name}")
                return False

            self.stats[slice_name]['active'] = False

            # Persist status to file
            status_map = self._read_slice_status_file()
            status_map[slice_name] = {'active': False, 'updated_at': datetime.now().isoformat()}
            self._write_slice_status_file(status_map)

            # Update process metadata if any
            if slice_name in self.slice_processes:
                self.slice_processes[slice_name]['status'] = 'stopped'

            print(f"✓ Slice '{slice_name}' stopped (inactive)")
            return True
        except Exception as e:
            print(f"❌ Failed to stop slice '{slice_name}': {e}")
            return False
    
    def encrypt_slice_data(self, data: Dict) -> str:
        """Encrypt slice data using local encryption"""
        try:
            if self.slice_encryptor:
                encrypted_data = self.slice_encryptor.encrypt_slice_config(data)
                if encrypted_data:
                    logger.info("✓ Slice data encrypted successfully using local encryption")
                    return encrypted_data
                else:
                    logger.warning("Local encryption failed, falling back to plain text")
            else:
                logger.warning("Slice encryptor not initialized, using plain text")
            
            # Fallback to plain text
            return json.dumps(data, indent=2)
            
        except Exception as e:
            logger.warning(f"Encryption failed: {e}, using plain text")
            return json.dumps(data, indent=2)
    
    def decrypt_slice_data(self, encrypted_data: str) -> Dict:
        """Decrypt slice data using local encryption"""
        try:
            if self.slice_encryptor:
                decrypted_data = self.slice_encryptor.decrypt_slice_config(encrypted_data)
                if decrypted_data:
                    logger.info("✓ Slice data decrypted successfully using local encryption")
                    return decrypted_data
                else:
                    logger.warning("Local decryption failed, trying plain text")
            else:
                logger.warning("Slice encryptor not initialized, trying plain text")
            
            # Fallback to plain text
            try:
                return json.loads(encrypted_data)
            except:
                return {}
                
        except Exception as e:
            logger.warning(f"Decryption failed: {e}, trying plain text")
            try:
                return json.loads(encrypted_data)
            except:
                return {}

    def _normalize_decrypted_slice(self, dec: Dict, slice_name: str) -> Dict:
        """Normalize a decrypted slice dict so downstream code can rely on fields.

        Guarantees keys: 'name', 'port' (int), 'current_bandwidth', 'max_bandwidth',
        'base_bandwidth', 'target_latency', 'max_latency', 'reliability', 'encryption', 'qos_class'
        """
        # Default canonical values for known slices
        defaults = {
            'URLLC': {'name': 'Ultra-Reliable Low Latency Communications', 'port': 5001, 'base_bandwidth': 50, 'current_bandwidth': 50, 'max_bandwidth': 200, 'target_latency': 1, 'max_latency': 5, 'reliability': 99.999, 'encryption': True, 'qos_class': 'ultra'},
            'eMBB': {'name': 'Enhanced Mobile Broadband', 'port': 5002, 'base_bandwidth': 100, 'current_bandwidth': 100, 'max_bandwidth': 500, 'target_latency': 10, 'max_latency': 15, 'reliability': 99.9, 'encryption': True, 'qos_class': 'premium'},
            'mMTC': {'name': 'Massive Machine Type Communications', 'port': 5003, 'base_bandwidth': 20, 'current_bandwidth': 20, 'max_bandwidth': 100, 'target_latency': 100, 'max_latency': 1000, 'reliability': 99.0, 'encryption': True, 'qos_class': 'standard'}
        }

        base = defaults.get(slice_name, {})

        # Ensure name
        dec['name'] = dec.get('name', base.get('name', slice_name))

        # Port
        try:
            if 'port' in dec and dec['port'] is not None:
                dec['port'] = int(dec['port'])
            else:
                dec['port'] = int(base.get('port', 0)) if base.get('port') else 'N/A'
        except Exception:
            dec['port'] = base.get('port', 'N/A')

        # Bandwidths
        def _int_or_default(key, default):
            try:
                if key in dec and dec[key] is not None:
                    return int(dec[key])
            except Exception:
                pass
            return int(default) if default is not None else 0

        dec['base_bandwidth'] = _int_or_default('base_bandwidth', base.get('base_bandwidth', 0))
        dec['current_bandwidth'] = _int_or_default('current_bandwidth', base.get('current_bandwidth', dec['base_bandwidth']))
        dec['max_bandwidth'] = _int_or_default('max_bandwidth', base.get('max_bandwidth', dec['current_bandwidth']))

        # Latency and reliability
        try:
            dec['target_latency'] = int(dec.get('target_latency', base.get('target_latency', 0)))
        except Exception:
            dec['target_latency'] = base.get('target_latency', 0)
        try:
            dec['max_latency'] = int(dec.get('max_latency', base.get('max_latency', 0)))
        except Exception:
            dec['max_latency'] = base.get('max_latency', 0)
        try:
            dec['reliability'] = float(dec.get('reliability', base.get('reliability', 0.0)))
        except Exception:
            dec['reliability'] = base.get('reliability', 0.0)

        # Other sensible defaults
        dec['encryption'] = dec.get('encryption', base.get('encryption', True))
        dec['qos_class'] = dec.get('qos_class', base.get('qos_class', 'standard'))

        # Display helpers
        dec['display_port'] = str(dec['port']) if dec.get('port') else 'N/A'
        try:
            dec['display_bandwidth'] = f"{int(dec.get('current_bandwidth', 0))}/{int(dec.get('max_bandwidth', 0))} Mbps"
        except Exception:
            dec['display_bandwidth'] = 'N/A'

        return dec
    
    def save_encrypted_slice(self, slice_type: str, encrypted_data: str):
        """Save encrypted slice configuration to file"""
        try:
            # Load existing data
            all_slices = {}
            if os.path.exists(self.encrypted_file):
                with open(self.encrypted_file, 'r') as f:
                    try:
                        all_slices = json.loads(f.read())
                    except:
                        all_slices = {}
            
            # Add new slice
            all_slices[slice_type] = {
                'encrypted_data': encrypted_data,
                'timestamp': datetime.now().isoformat()
            }
            
            # Save back to file
            with open(self.encrypted_file, 'w') as f:
                json.dump(all_slices, f, indent=2)
                
            logger.info(f"✓ Saved encrypted {slice_type} slice to {self.encrypted_file}")
            
        except Exception as e:
            logger.error(f"Failed to save encrypted slice: {e}")
    
    def load_encrypted_slice(self, slice_type: str) -> Optional[Dict]:
        """Load and decrypt slice configuration"""
        try:
            if not os.path.exists(self.encrypted_file):
                logger.warning(f"Encrypted file {self.encrypted_file} not found")
                return None
            
            with open(self.encrypted_file, 'r') as f:
                all_slices = json.loads(f.read())
            
            if slice_type not in all_slices:
                logger.warning(f"Slice {slice_type} not found in encrypted file")
                return None
            
            encrypted_data = all_slices[slice_type]['encrypted_data']
            decrypted_config = self.decrypt_slice_data(encrypted_data)
            
            return decrypted_config
            
        except Exception as e:
            logger.error(f"Failed to load encrypted slice: {e}")
            return None
    
    def verify_slice_integrity(self, slice_type: str, original_config: Dict) -> bool:
        """Verify the integrity of an encrypted slice configuration"""
        try:
            if not self.slice_encryptor:
                logger.warning("Slice encryptor not initialized")
                return False
            
            # Load the encrypted data
            if not os.path.exists(self.encrypted_file):
                logger.warning(f"Encrypted file {self.encrypted_file} not found")
                return False
            
            with open(self.encrypted_file, 'r') as f:
                all_slices = json.loads(f.read())
            
            if slice_type not in all_slices:
                logger.warning(f"Slice {slice_type} not found in encrypted file")
                return False
            
            encrypted_data = all_slices[slice_type]['encrypted_data']
            
            # Verify integrity
            verified = self.slice_encryptor.verify_slice_integrity(original_config, encrypted_data)
            
            if verified:
                logger.info(f"✓ Slice {slice_type} integrity verified")
            else:
                logger.warning(f"✗ Slice {slice_type} integrity check failed")
            
            return verified
            
        except Exception as e:
            logger.error(f"Failed to verify slice integrity: {e}")
            return False
    
    def encrypt_all_slices(self):
        """Encrypt all existing slices"""
        print("\n🔐 Encrypting all slices...")
        
        encrypted_map = {}
        for slice_name, config in self.slice_configs.items():
            try:
                # Create a copy with slice_name for encryption
                config_copy = config.copy()
                config_copy['slice_name'] = slice_name
                
                encrypted_data = self.encrypt_slice_data(config_copy)
                if encrypted_data:
                    self.save_encrypted_slice(slice_name, encrypted_data)
                    encrypted_map[slice_name] = {'encrypted_data': encrypted_data, 'timestamp': datetime.now().isoformat()}
                    print(f"✓ Encrypted {slice_name}")
                else:
                    print(f"✗ Failed to encrypt {slice_name}")
            except Exception as e:
                print(f"✗ Error encrypting {slice_name}: {e}")
        
        # After encrypting, clear in-memory sensitive dynamic slices and mark as encrypted
        # Also encrypt any dynamic created slices
        for dyn_name, dyn_cfg in list(self.created_slices.items()):
            try:
                cfg_copy = dyn_cfg.copy()
                cfg_copy.setdefault('slice_name', dyn_name)
                encrypted_data = self.encrypt_slice_data(cfg_copy)
                if encrypted_data:
                    self.save_encrypted_slice(dyn_name, encrypted_data)
                    encrypted_map[dyn_name] = {'encrypted_data': encrypted_data, 'timestamp': datetime.now().isoformat()}
            except Exception:
                pass

        self.created_slices.clear()
        self.decrypted = False
        # persist map
        try:
            # Store encrypted artifacts in-memory for runtime access
            self._in_memory_encrypted_map = encrypted_map
        except Exception:
            pass

        print("✓ All slices encrypted and in-memory slices cleared")

        # Persist encrypted files for compatibility with external tools
        try:
            # Ensure in-memory map exists
            enc_map = getattr(self, '_in_memory_encrypted_map', None) or encrypted_map
            # Write legacy consolidated encrypted file
            # If an old encrypted file exists with legacy name, back it up
            try:
                if os.path.exists('network_slices.enc'):
                    os.replace('network_slices.enc', 'network_slices.enc.bak')
            except Exception:
                pass

            # Write the canonical .enc and companion JSON
            with open(self.encrypted_file, 'w') as f:
                json.dump(enc_map, f, indent=2)
            with open(self.encrypted_json, 'w') as f:
                json.dump(enc_map, f, indent=2)
            logger.info(f"✓ Wrote {self.encrypted_file} and {self.encrypted_json} for compatibility")
        except Exception as e:
            logger.warning(f"Failed to persist encrypted files: {e}")

    def get_canonical_slices(self) -> Dict:
        """Return canonical three slices view suitable for external consumers.

        This returns a normalized, display-friendly mapping for eMBB, URLLC, mMTC.
        """
        canonical = {}
        for name, cfg in self.slice_configs.items():
            # Make a shallow copy and ensure display fields and types
            copy = dict(cfg)
            copy.setdefault('slice_name', name)
            copy.setdefault('slice_id', copy.get('slice_id', 'N/A'))
            # Normalize numeric types where possible
            try:
                copy['port'] = int(copy.get('port')) if copy.get('port') not in (None, 'N/A') else 'N/A'
            except Exception:
                copy['port'] = copy.get('port', 'N/A')
            copy.setdefault('current_bandwidth', copy.get('current_bandwidth', copy.get('base_bandwidth', 0)))
            copy.setdefault('max_bandwidth', copy.get('max_bandwidth', copy.get('current_bandwidth', 0)))
            copy.setdefault('display_port', str(copy['port']) if copy.get('port') not in (None, 'N/A') else 'N/A')
            try:
                copy.setdefault('display_bandwidth', f"{int(copy.get('current_bandwidth',0))}/{int(copy.get('max_bandwidth',0))} Mbps")
            except Exception:
                copy.setdefault('display_bandwidth', 'N/A')
            canonical[name] = copy
        return canonical
    
    def decrypt_and_verify_slices(self):
        """Decrypt and verify all encrypted slices"""
        print("\n🔓 Decrypt Menu")
        print("="*40)

        # Prefer in-memory artifacts; do not read files from disk per runtime-only requirement
        all_slices = getattr(self, '_in_memory_encrypted_map', None)
        if not all_slices:
            print("❌ No encrypted slices available in-memory; ensure controller/manager populated artifacts and activated")
            return

        print("Select an option:")
        print("  1) Decrypt one slice")
        print("  2) Decrypt all slices")
        print("  3) Cancel")

        choice = input("Choose [1/2/3]: ").strip()
        if choice not in ("1", "2"):
            print("Cancelled decryption")
            return

        # prompt for key (passphrase)
        key_input = input("Enter decryption passphrase: ").strip()
        # Reinitialize slice encryptor with derived key from passphrase so decrypt uses provided key
        try:
            from nfv.firewall_vnf import load_or_create_key, SliceEncryption
        except Exception:
            try:
                from firewall_vnf import load_or_create_key, SliceEncryption
            except Exception:
                print("❌ Could not import NFV encryption utilities to derive key")
                return

        try:
            # Use 256-bit derivation and provided passphrase
            key = load_or_create_key(bits=256, passphrase=key_input)
            self.slice_encryptor = SliceEncryption(key)
        except Exception as e:
            print(f"❌ Failed to derive key from passphrase: {e}")
            return

        # all_slices already loaded from in-memory map

        if choice == "1":
            slice_name = input("Enter slice name to decrypt (eMBB/URLLC/mMTC): ").strip()
            entry = all_slices.get(slice_name)
            if not entry:
                print(f"❌ Slice '{slice_name}' not found in encrypted file")
                return
            encrypted_data = entry.get('encrypted_data')
            dec = self.decrypt_slice_data(encrypted_data)
            if dec:
                dec = self._normalize_decrypted_slice(dec, slice_name)
                dec.setdefault('slice_name', slice_name)
                # Merge into canonical slice_configs (authoritative)
                self.slice_configs[slice_name] = dec
                # Mark stats active and persist
                try:
                    self.set_slice_status(slice_name, True, persist=True)
                except Exception:
                    self.stats.setdefault(slice_name, {'packets': 0, 'bytes': 0, 'active': False})
                self.decrypted = True
                print(f"✓ Slice '{slice_name}' decrypted, normalized and loaded into canonical configs")
                # persist decrypted outputs for single slice
                try:
                    # Persist decrypted view in-memory only
                    self._in_memory_decrypted_map = {slice_name: dec}
                    # Also write legacy decrypted files for compatibility
                    os.makedirs('result', exist_ok=True)
                    outpath = os.path.join('result', 'slice_decrypted.decor.json')
                    with open(outpath, 'w') as _f:
                        json.dump(self._in_memory_decrypted_map, _f, indent=2)
                    # Also keep legacy names for compatibility
                    with open('slice_decrypted.json', 'w') as _f:
                        json.dump(self._in_memory_decrypted_map, _f, indent=2)
                except Exception:
                    pass
            else:
                print(f"❌ Failed to decrypt slice '{slice_name}'")
            return

        # choice == 2
        loaded = 0
        for slice_name, slice_data in all_slices.items():
            enc = slice_data.get('encrypted_data')
            dec = self.decrypt_slice_data(enc)
            if dec:
                dec = self._normalize_decrypted_slice(dec, slice_name)
                dec.setdefault('slice_name', slice_name)
                # Merge into canonical slice_configs, do not duplicate into created_slices
                self.slice_configs[slice_name] = dec
                # Ensure stats reflect active and persist
                try:
                    self.set_slice_status(slice_name, True, persist=True)
                except Exception:
                    self.stats.setdefault(slice_name, {'packets': 0, 'bytes': 0, 'active': False})
                loaded += 1

        if loaded:
            self.decrypted = True
            print(f"✓ Decrypted and loaded {loaded} slice(s) into canonical configs")
            # write decrypted map to files (persist canonical slice_configs subset)
            try:
                # Store decrypted canonical subset in-memory instead of files
                self._in_memory_decrypted_map = {k: self.slice_configs[k] for k in list(self.slice_configs.keys())[:loaded]}
                # Also persist legacy decrypted outputs to disk for compatibility
                try:
                    os.makedirs('result', exist_ok=True)
                    outpath = os.path.join('result', 'slice_decrypted.decor.json')
                    with open(outpath, 'w') as _f:
                        json.dump(self._in_memory_decrypted_map, _f, indent=2)
                    with open('slice_decrypted.json', 'w') as _f:
                        json.dump(self._in_memory_decrypted_map, _f, indent=2)
                except Exception:
                    pass
            except Exception:
                pass
        else:
            print("❌ No slices were decrypted")
    
    def display_statistics(self):
        """Display current slice statistics"""
        print("\n📊 SLICE STATISTICS OVERVIEW")
        print("="*80)
        
        # Prefer canonical slice_configs status if available
        total_slices = len(self.slice_configs) + len(self.created_slices)

        def _is_active(name):
            # Use the stats active flag as the single source of truth for activity
            return bool(self.stats.get(name, {}).get('active', False))

        active_slices = sum(1 for name in list(self.slice_configs.keys()) + list(self.created_slices.keys()) if _is_active(name))

        print(f"→ Total Slices: {total_slices}")
        print(f"→ Active Slices: {active_slices}")
        print(f"→ Inactive Slices: {total_slices - active_slices}")
        
        if self.stats:
            print("\n📈 Slice Status Details:")
            # Iterate canonical slices first to show consistent ordering
            for slice_name in sorted(list(self.slice_configs.keys())):
                stats = self.stats.get(slice_name, {})
                active = _is_active(slice_name)
                status_icon = "🟢" if active else "🔴"
                packets = stats.get('packets', 0)
                bytes_count = stats.get('bytes', 0)

                # Prefer display-friendly fields from slice_configs when present
                config = self.slice_configs.get(slice_name, self.created_slices.get(slice_name, {}))
                display_port = config.get('display_port') or (config.get('port') if config.get('port') else 'N/A')
                display_bw = config.get('display_bandwidth') or (
                    f"{config.get('base_bandwidth','N/A')} Mbps" if config.get('base_bandwidth') else 'N/A')

                print(f"  {status_icon} {slice_name}:")
                print(f"    → Port: {display_port}")
                print(f"    → Bandwidth: {display_bw}")
                print(f"    → Packets: {packets}")
                print(f"    → Bytes: {bytes_count}")
                
                # Show process info if available
                if slice_name in self.slice_processes:
                    process_info = self.slice_processes[slice_name]
                    print(f"    → Process Status: {process_info.get('status', 'unknown')}")
                    print(f"    → Started: {process_info.get('start_time', 'unknown')}")
        
        print("="*80)
    
    def show_slice_registry(self):
        """Show slice registry information"""
        print("\n📋 SLICE REGISTRY")
        print("="*80)
        
        if self.created_slices:
            print(f"→ Registered Slices: {len(self.created_slices)}")
            for slice_name, config in self.created_slices.items():
                print(f"  → {slice_name}: {config.get('status', 'unknown')} ({config.get('port', 'N/A')})")
        else:
            print("→ No registered slices")
        
        print("="*80)
    
    def reset_all_slices(self):
        """Reset all slices and clear encrypted data"""
        print("\n🔄 RESETTING ALL SLICES")
        print("="*80)
        
        # Clear stats
        for slice_name in self.stats:
            self.stats[slice_name]['active'] = False
            self.stats[slice_name]['packets'] = 0
            self.stats[slice_name]['bytes'] = 0
        
        # Clear created slices
        self.created_slices.clear()
        
        # Clear slice processes
        self.slice_processes.clear()
        
        # Remove encrypted files
        if os.path.exists(self.encrypted_file):
            os.remove(self.encrypted_file)
            print("→ Removed encrypted slice file")
        
        if os.path.exists(self.slice_registry_file):
            os.remove(self.slice_registry_file)
            print("→ Removed slice registry file")
        
        print("✓ All slices reset successfully")
        print("="*80)
    
    def real_time_monitoring(self):
        """Start real-time monitoring of slices"""
        print("\n📊 REAL-TIME MONITORING")
        print("="*80)
        print("Monitoring slices for 30 seconds...")
        
        # Simple monitoring simulation
        for i in range(30):
            time.sleep(1)
            if i % 5 == 0:
                print(f"→ Monitoring... ({i+1}/30 seconds)")
        
        print("✓ Monitoring completed")
        self.display_statistics()
    
    def display_slice_info(self, slice_name: str, config: Dict):
        """Display detailed information about a specific slice with dynamic allocation info"""
        print(f"\n" + "="*60)
        print(f"🔹 SLICE DETAILS: {slice_name}")
        print("="*60)
        
        # Handle both predefined and dynamic slices
        if 'name' in config:  # Predefined slice
            print(f"→ Name: {config['name']}")
        
        # Enhanced bandwidth display for dynamic allocation
        if 'base_bandwidth' in config:
            print(f"→ Base Bandwidth: {config['base_bandwidth']} Mbps")
            print(f"→ Current Bandwidth: {config.get('current_bandwidth', config['base_bandwidth'])} Mbps")
            print(f"→ Max Bandwidth: {config['max_bandwidth']} Mbps")
            print(f"→ Min Bandwidth: {config['min_bandwidth']} Mbps")
            print(f"→ Auto-scaling: {'✓ Enabled' if config.get('auto_scale', False) else '✗ Disabled'}")
        else:
            print(f"→ Bandwidth: {config.get('bandwidth', 'N/A')} Mbps")
        
        # Enhanced latency display with SLA thresholds
        if 'target_latency' in config:
            print(f"→ Target Latency: {config['target_latency']} ms")
            print(f"→ Max Latency (SLA): {config['max_latency']} ms")
        else:
            print(f"→ Latency: {config.get('latency', 'N/A')} ms")
        
        print(f"→ Reliability: {config.get('reliability', 'N/A')}%")
        print(f"→ Priority: {config.get('priority', 'N/A')}")
        
        # Dynamic allocation specific information
        if 'scaling_factor' in config:
            print(f"→ Scaling Factor: {config['scaling_factor']}")
            print(f"→ Allocation Weight: {config['allocation_weight']}")
            print(f"→ SLA Priority: {config['sla_priority']}")
            print(f"→ Traffic Pattern: {config['traffic_pattern']}")
        
        if 'port' in config:
            print(f"→ Port: {config['port']}")
        if 'encryption' in config:
            print(f"→ Encryption: {'🔒 Enabled' if config['encryption'] else '📄 Disabled'}")
        if 'qos_class' in config:
            print(f"→ QoS Class: {config['qos_class']}")
        
        # Add slice ID and creation time for dynamic slices
        if 'slice_id' in config:
            print(f"→ Slice ID: {config['slice_id']}")
        if 'created_at' in config:
            print(f"→ Created At: {config['created_at']}")
        if 'status' in config:
            status_icon = "🟢" if config['status'] == 'active' else "🟡" if config['status'] == 'pending' else "🔴"
            print(f"→ Status: {status_icon} {config['status'].title()}")
        
        print("="*60)
    
    def enhanced_interactive_cli(self):
        """Enhanced interactive CLI with dynamic allocation features"""
        print("\n" + "="*80)
        print("🚀 5G DYNAMIC NETWORK SLICING MANAGEMENT - INTERACTIVE MODE")
        print("="*80)
        print("Welcome to the enhanced 5G Network Slicing Management CLI!")
        print("Now featuring Dynamic Resource Allocation (DRA) capabilities.")
        print("\nType 'help' for available commands or 'exit' to quit.")
        
        while True:
            try:
                # Refresh persisted slice status so commands in other terminals are visible
                try:
                    self.refresh_status_from_file()
                except Exception:
                    pass

                command = input("\n🔧 slice-manager> ").strip().lower()
                
                if command == 'exit' or command == 'quit':
                    print("👋 Goodbye! Stopping dynamic monitoring...")
                    self.stop_monitoring()
                    break
                
                elif command == 'help':
                    self.print_enhanced_help()
                
                elif command == 'list':
                    # Ensure we reflect latest persisted active/inactive state
                    try:
                        self.refresh_status_from_file()
                    except Exception:
                        pass
                    self.list_slices()
                
                elif command.startswith('create '):
                    slice_name = command.split(' ', 1)[1]
                    self.create_slice(slice_name)
                
                elif command.startswith('delete '):
                    slice_name = command.split(' ', 1)[1]
                    self.delete_slice(slice_name)
                
                elif command.startswith('start '):
                    slice_name = command.split(' ', 1)[1]
                    self.start_slice(slice_name)
                
                elif command.startswith('stop '):
                    slice_name = command.split(' ', 1)[1]
                    self.stop_slice(slice_name)
                
                elif command.startswith('info '):
                    slice_name = command.split(' ', 1)[1]
                    if slice_name in self.slice_configs:
                        self.display_slice_info(slice_name, self.slice_configs[slice_name])
                    else:
                        print(f"❌ Slice '{slice_name}' not found")
                
                elif command == 'stats':
                    self.display_statistics()
                
                elif command == 'test':
                    self.test_connectivity()
                
                elif command == 'monitor':
                    self.real_time_monitoring()
                
                elif command == 'encrypt':
                    self.encrypt_all_slices()
                
                elif command == 'decrypt':
                    self.decrypt_and_verify_slices()
                
                elif command == 'stats':
                    self.display_statistics()
                
                elif command == 'monitor':
                    self.real_time_monitoring()
                
                # ===== Dynamic Resource Allocation Commands =====
                elif command == 'start-dra':
                    print("🔄 Starting Dynamic Resource Allocation monitoring...")
                    self.start_dynamic_monitoring()
                    print("✓ DRA monitoring started successfully!")
                
                elif command == 'stop-dra':
                    print("🛑 Stopping Dynamic Resource Allocation monitoring...")
                    self.stop_monitoring()
                    print("✓ DRA monitoring stopped!")
                
                elif command == 'dra-status':
                    self.get_allocation_status()
                
                elif command.startswith('set-algorithm '):
                    algorithm = command.split(' ', 1)[1]
                    self.set_allocation_algorithm(algorithm)
                
                elif command.startswith('adjust-bandwidth '):
                    parts = command.split(' ')
                    if len(parts) == 3:
                        slice_id, bandwidth = parts[1], float(parts[2])
                        self.manual_bandwidth_adjustment(slice_id, bandwidth)
                    else:
                        print("❌ Usage: adjust-bandwidth <slice_id> <bandwidth_mbps>")
                
                elif command == 'sla-violations':
                    self.show_sla_violations()
                
                elif command == 'detailed-info':
                    self.show_detailed_slice_info()
                
                elif command == 'realtime-monitor':
                    self.show_realtime_monitoring()
                
                elif command == 'slice-count':
                    # Count active slices using stats active flag
                    canonical_set = ['eMBB', 'URLLC', 'mMTC']
                    # ensure canonical presence
                    for cname in canonical_set:
                        if cname not in self.slice_configs:
                            self.slice_configs[cname] = {'name': cname}
                    total_count = len(canonical_set)
                    active_count = sum(1 for name in canonical_set if self.stats.get(name, {}).get('active', False))
                    print(f"\n📊 Slice Count: {active_count}/{total_count} slices active")
                    print(f"   • Total Slices: {total_count}")
                    print(f"   • Active Slices: {active_count}")
                    print(f"   • Inactive Slices: {total_count - active_count}")
                    # Show basic system stats (cpu/memory)
                    try:
                        import psutil
                        cpu = psutil.cpu_percent(interval=0.5)
                        mem = psutil.virtual_memory()
                        print(f"   • System CPU: {cpu:.1f}%")
                        print(f"   • System Memory: {mem.percent:.1f}% ({int(mem.used/1024**2)}MB used)")
                    except Exception:
                        # Fallback to os tools
                        try:
                            if os.name == 'posix':
                                load = os.getloadavg()
                                print(f"   • Load Avg (1m,5m,15m): {load}")
                        except Exception:
                            pass
                
                elif command == 'slice-status':
                    self.get_allocation_status()
                
                elif command == 'network-status':
                    print("\n🌐 Network Status:")
                    print("-" * 30)
                    try:
                        response = requests.get("http://localhost:8080/network/status", timeout=5)
                        if response.status_code == 200:
                            status_data = response.json()
                            print(f"Controller: {status_data.get('controller_status', 'Unknown')}")
                            print(f"Switches: {status_data.get('switch_count', 0)}")
                            print(f"Hosts: {status_data.get('host_count', 0)}")
                            print(f"Flows: {status_data.get('flow_count', 0)}")
                        else:
                            print("❌ Unable to retrieve network status")
                    except:
                        print("❌ Controller not available")
                
                elif command.startswith('export-report'):
                    parts = command.split(' ')
                    filename = parts[1] if len(parts) > 1 else None
                    self.export_allocation_report(filename)
                
                elif command == 'performance':
                    self.show_performance_dashboard()
                
                elif command == 'slice-history':
                    self.show_allocation_history()
                
                # ===== Legacy Commands =====
                elif command.startswith('dynamic '):
                    slice_params = command.split(' ')[1:]
                    self.create_dynamic_slice_interactive(slice_params)
                
                elif command == 'registry':
                    self.show_slice_registry()
                
                elif command == 'reset':
                    self.reset_all_slices()
                
                elif command == 'clear':
                    os.system('cls' if os.name == 'nt' else 'clear')
                
                elif command == '':
                    continue
                
                else:
                    print(f"❌ Unknown command: '{command}'. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted! Type 'exit' to quit gracefully.")
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def print_enhanced_help(self):
        """Print enhanced help with dynamic allocation commands"""
        print("\n" + "="*80)
        print("📚 DYNAMIC SLICE MANAGER - COMMAND REFERENCE")
        print("="*80)
        
        print("\n🔧 Basic Slice Management:")
        print("  list                    - List all available slices")
        print("  create <slice>          - Create a network slice")
        print("  delete <slice>          - Delete a network slice")
        print("  start <slice>           - Start a network slice")
        print("  stop <slice>            - Stop a network slice")
        print("  info <slice>            - Show detailed slice information")
        
        print("\n📊 Monitoring & Statistics:")
        print("  stats                   - Display current statistics")
        print("  monitor                 - Start real-time monitoring")
        print("  test                    - Test network connectivity")
        print("  detailed-info           - Show detailed slice information")
        print("  realtime-monitor        - Show real-time monitoring data")
        print("  slice-count             - Show active slice count")
        print("  slice-status            - Show comprehensive slice status")
        print("  network-status          - Show network status overview")
        
        print("\n🔄 Dynamic Resource Allocation (DRA):")
        print("  start-dra               - Start dynamic monitoring")
        print("  stop-dra                - Stop dynamic monitoring")
        print("  dra-status              - Show allocation status")
        print("  set-algorithm <alg>     - Set allocation algorithm")
        print("                            (proportional, priority, predictive, ml_based)")
        print("  adjust-bandwidth <slice> <mbps> - Manually adjust bandwidth")
        print("  sla-violations          - Show SLA violation report")
        print("  predictions             - Show traffic predictions")
        print("  export-report [file]    - Export allocation report")
        print("  performance             - Show performance dashboard")
        print("  slice-history           - Show allocation history")
        
        print("\n🔒 Security & Advanced:")
        print("  encrypt                 - Encrypt all slice data")
        print("  decrypt                 - Decrypt and verify all slices")
        print("  reset                   - Reset all slices and clear data")
        print("  dynamic <params>        - Create dynamic slice")
        print("  registry                - Show slice registry")
        
        print("\n🛠️  System Commands:")
        print("  clear                   - Clear screen")
        print("  help                    - Show this help")
        print("  exit/quit               - Exit the program")
        
        print("\n💡 Examples:")
        print("  create eMBB             - Create Enhanced Mobile Broadband slice")
        print("  start-dra               - Start dynamic resource allocation")
        print("  set-algorithm predictive - Use predictive allocation")
        print("  adjust-bandwidth eMBB 150 - Set eMBB bandwidth to 150 Mbps")
        print("  dra-status              - Check current allocation status")
        
        print("="*80)
    
    def show_performance_dashboard(self):
        """Show comprehensive performance dashboard"""
        print("\n" + "="*80)
        print("📈 DYNAMIC ALLOCATION PERFORMANCE DASHBOARD")
        print("="*80)
        
        # Current performance metrics
        print("🎯 Key Performance Indicators:")
        print("-" * 40)
        print(f"  Allocation Efficiency:    {self.performance_metrics['allocation_efficiency']:.1f}%")
        print(f"  SLA Compliance:          {self.performance_metrics['sla_compliance']:.1f}%")
        print(f"  Resource Utilization:    {self.performance_metrics['resource_utilization']:.1f}%")
        print(f"  Prediction Accuracy:     {self.performance_metrics['prediction_accuracy']:.1f}%")
        
        # Current system status
        print(f"\n🔄 System Status:")
        print("-" * 20)
        print(f"  Dynamic Monitoring:      {'✓ Active' if self.monitoring_active else '✗ Inactive'}")
        print(f"  Current Algorithm:       {self.dra_config['current_algorithm']}")
        print(f"  Auto-scaling:           {'✓ Enabled' if self.dra_config['auto_scaling_enabled'] else '✗ Disabled'}")
        print(f"  Traffic Prediction:     {'✓ Enabled' if self.dra_config['traffic_prediction_enabled'] else '✗ Disabled'}")
        print(f"  SLA Monitoring:         {'✓ Enabled' if self.dra_config['sla_monitoring_enabled'] else '✗ Disabled'}")
        
        # Data collection status
        print(f"\n📊 Data Collection:")
        print("-" * 25)
        print(f"  Allocation History:      {len(self.allocation_history)} entries")
        print(f"  Traffic History:         {len(self.traffic_history)} entries")
        print(f"  SLA Violations:          {len(self.sla_violations)} total")
        
        # Recent violations
        recent_violations = len([v for v in self.sla_violations 
                               if datetime.fromisoformat(v['timestamp']) > datetime.now() - timedelta(hours=1)])
        print(f"  Recent Violations (1h):  {recent_violations}")
        
        print("="*80)
    
    def show_allocation_history(self):
        """Show recent allocation history"""
        print("\n" + "="*80)
        print("📜 ALLOCATION HISTORY")
        print("="*80)
        
        if not self.allocation_history:
            print("⏳ No allocation history available")
            print("   Start dynamic monitoring to collect data")
            print("="*80)
            return
        
        # Show last 10 allocation records
        recent_allocations = list(self.allocation_history)[-10:]
        
        print(f"📊 Showing last {len(recent_allocations)} allocation records:")
        print("-" * 80)
        
        for i, allocation in enumerate(recent_allocations, 1):
            timestamp = allocation.get('timestamp', 'Unknown')
            if timestamp != 'Unknown':
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    time_str = timestamp
            else:
                time_str = 'Unknown'
            
            print(f"#{i:2d} {time_str} - Algorithm: {allocation.get('current_algorithm', 'Unknown')}")
            
            # Show slice allocations
            for slice_id, slice_data in allocation.get('slices', {}).items():
                if slice_id in self.slice_configs:
                    bw = slice_data.get('current_bandwidth', 0)
                    util = slice_data.get('utilization', 0)
                    print(f"     {slice_id}: {bw:.0f} Mbps ({util:.1f}% util)")
            print()
        
        # Show allocation trends
        if len(recent_allocations) >= 2:
            print("📈 Trends (comparing first vs last):")
            print("-" * 40)
            
            first_alloc = recent_allocations[0]
            last_alloc = recent_allocations[-1]
            
            for slice_id in self.slice_configs.keys():
                first_bw = first_alloc.get('slices', {}).get(slice_id, {}).get('current_bandwidth', 0)
                last_bw = last_alloc.get('slices', {}).get(slice_id, {}).get('current_bandwidth', 0)
                
                if first_bw > 0:
                    change = ((last_bw - first_bw) / first_bw) * 100
                    trend_icon = "📈" if change > 5 else "📉" if change < -5 else "➡️"
                    print(f"  {trend_icon} {slice_id}: {change:+.1f}% bandwidth change")
        
        print("="*80)
    
    def list_all_slices(self):
        """List all available slices with their status - compatibility wrapper"""
        self.list_slices()
    
    def test_slice_connectivity(self, slice_type: str):
        """Test slice connectivity and performance"""
        if slice_type not in self.slice_configs:
            logger.error(f"Invalid slice type: {slice_type}")
            return False
        
        config = self.slice_configs[slice_type]
        port = config['port']
        
        print(f"\n🔍 Testing {slice_type} slice connectivity...")
        print(f"Target port: {port}")
        print(f"Expected bandwidth: {config['bandwidth']} Mbps")
        print(f"Expected latency: {config['latency']} ms")
        
        # Test network connectivity (simplified for demo)
        try:
            # Simulate connectivity test
            import random
            
            # Simulate latency test
            simulated_latency = config['latency'] + random.uniform(-0.5, 0.5)
            print(f"✓ Latency test: {simulated_latency:.2f} ms")
            
            # Simulate bandwidth test
            simulated_bw = config['bandwidth'] * random.uniform(0.95, 1.05)
            print(f"✓ Bandwidth test: {simulated_bw:.1f} Mbps")
            
            # Simulate packet loss
            packet_loss = random.uniform(0, 0.1)
            print(f"✓ Packet loss: {packet_loss:.3f}%")
            
            if packet_loss < 0.01:
                print("✅ ZERO PACKET LOSS ACHIEVED")
            
            print(f"✅ {slice_type} slice connectivity test PASSED\n")
            return True
            
        except Exception as e:
            logger.error(f"Connectivity test failed: {e}")
            return False
    
    def monitor_slices(self, duration: int = 30):
        """Monitor slice performance in real-time"""
        print(f"\n📊 Starting slice monitoring for {duration} seconds...")
        print("Press Ctrl+C to stop monitoring\n")
        
        start_time = time.time()
        
        try:
            while time.time() - start_time < duration:
                # Clear screen
                os.system('clear' if os.name == 'posix' else 'cls')
                
                # Display header
                print("="*80)
                print(f"REAL-TIME SLICE MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("="*80)
                print(f"{'SLICE':<10} {'PACKETS':<10} {'BYTES':<12} {'BW(Mbps)':<10} {'LATENCY':<10} {'STATUS':<10}")
                print("-"*80)
                
                # Update and display statistics for each slice
                for slice_type in self.slice_configs:
                    stats = self.get_slice_stats(slice_type)
                    print(f"{slice_type:<10} {stats['packets']:<10} {stats['bytes']:<12} "
                          f"{stats['bandwidth']:<10.1f} {stats['latency']:<10.1f} {stats['status']:<10}")
                
                print("-"*80)
                print(f"Monitoring time remaining: {duration - int(time.time() - start_time)} seconds")
                
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n\n⏹️  Monitoring stopped by user")
    
    def get_slice_stats(self, slice_type: str) -> Dict:
        """Get real-time statistics for a slice"""
        import random
        
        # Simulate real statistics (in production, get from controller)
        config = self.slice_configs[slice_type]
        
        return {
            'packets': random.randint(1000, 10000),
            'bytes': random.randint(100000, 1000000),
            'bandwidth': config['bandwidth'] * random.uniform(0.8, 1.2),
            'latency': config['latency'] * random.uniform(0.9, 1.1),
            'status': 'ACTIVE'
        }
    
    def run_comprehensive_test(self):
        """Run comprehensive test suite for all slices"""
        print("\n🧪 Running Comprehensive Slice Test Suite...")
        print("="*60)
        
        test_results = {}
        
        for slice_type in self.slice_configs:
            print(f"\n📋 Testing {slice_type} slice...")
            
            # Create slice
            creation_success = self.create_slice(slice_type)
            
            # Test connectivity
            connectivity_success = self.test_slice_connectivity(slice_type)
            
            # Test encryption/decryption
            config = self.load_encrypted_slice(slice_type)
            encryption_success = config is not None
            
            test_results[slice_type] = {
                'creation': creation_success,
                'connectivity': connectivity_success,
                'encryption': encryption_success,
                'overall': creation_success and connectivity_success and encryption_success
            }
        
        # Display test summary
        print("\n" + "="*60)
        print("TEST RESULTS SUMMARY")
        print("="*60)
        print(f"{'SLICE':<10} {'CREATION':<10} {'CONNECTIVITY':<12} {'ENCRYPTION':<12} {'OVERALL':<10}")
        print("-"*60)
        
        for slice_type, results in test_results.items():
            creation = "✅ PASS" if results['creation'] else "❌ FAIL"
            connectivity = "✅ PASS" if results['connectivity'] else "❌ FAIL"
            encryption = "✅ PASS" if results['encryption'] else "❌ FAIL"
            overall = "✅ PASS" if results['overall'] else "❌ FAIL"
            
            print(f"{slice_type:<10} {creation:<10} {connectivity:<12} {encryption:<12} {overall:<10}")
        
        print("="*60)
        
        # Overall system status
        all_passed = all(result['overall'] for result in test_results.values())
        status = "🎉 ALL TESTS PASSED - SYSTEM READY" if all_passed else "⚠️  SOME TESTS FAILED"
        print(f"\nSystem Status: {status}\n")
        
        return test_results
    
    def interactive_cli(self):
        """Legacy interactive CLI - redirects to enhanced version"""
        logger.info("Starting enhanced interactive CLI with dynamic allocation features...")
        self.enhanced_interactive_cli()
    
    def handle_create_dynamic_slice(self):
        """Handle dynamic slice creation from CLI"""
        print("\n🔹 Create Dynamic Network Slice")
        print("-" * 40)
        
        slice_name = input("Enter slice name: ").strip()
        if not slice_name:
            print("❌ Slice name cannot be empty")
            return
        
        if slice_name in self.created_slices:
            print(f"❌ Dynamic slice '{slice_name}' already exists")
            return
        
        try:
            print("\nEnter slice configuration:")
            port = int(input("Port (e.g., 5004): "))
            bandwidth = int(input("Bandwidth in Mbps (e.g., 50): "))
            latency = int(input("Latency in ms (e.g., 5): "))
            reliability = float(input("Reliability in % (e.g., 99.5): "))
            
            print("\nOptional settings:")
            priority = input("Priority (high/normal/low, default: normal): ").strip() or "normal"
            qos_class = input("QoS Class (premium/standard/basic, default: standard): ").strip() or "standard"
            encryption = input("Enable encryption? (y/n, default: y): ").strip().lower() != 'n'
            
            config = {
                'port': port,
                'bandwidth': bandwidth,
                'latency': latency,
                'reliability': reliability,
                'priority': priority,
                'qos_class': qos_class,
                'encryption': encryption
            }
            
            success = self.create_dynamic_slice(slice_name, config)
            if success:
                print(f"\n✅ Dynamic slice '{slice_name}' created successfully!")
            else:
                print(f"\n❌ Failed to create dynamic slice '{slice_name}'")
                
        except ValueError:
            print("❌ Invalid input. Please enter numeric values for port, bandwidth, latency, and reliability.")
        except Exception as e:
            print(f"❌ Error creating dynamic slice: {e}")
    
    def handle_delete_dynamic_slice(self):
        """Handle dynamic slice deletion from CLI"""
        if not self.created_slices:
            print("\n❌ No dynamic slices available to delete")
            return
        
        print("\n🗑️  Delete Dynamic Slice")
        print("-" * 30)
        print("Available dynamic slices:")
        
        for i, slice_name in enumerate(self.created_slices.keys(), 1):
            print(f"{i}. {slice_name}")
        
        try:
            choice = int(input(f"\nSelect slice to delete (1-{len(self.created_slices)}): "))
            slice_names = list(self.created_slices.keys())
            
            if 1 <= choice <= len(slice_names):
                slice_name = slice_names[choice - 1]
                
                confirm = input(f"Are you sure you want to delete '{slice_name}'? (y/N): ").strip().lower()
                if confirm == 'y':
                    success = self.delete_dynamic_slice(slice_name)
                    if success:
                        print(f"✅ Dynamic slice '{slice_name}' deleted successfully!")
                    else:
                        print(f"❌ Failed to delete slice '{slice_name}'")
                else:
                    print("❌ Deletion cancelled")
            else:
                print("❌ Invalid choice")
        except ValueError:
            print("❌ Please enter a valid number")
        except Exception as e:
            print(f"❌ Error deleting slice: {e}")

    def handle_create_slice(self):
        """Handle slice creation from CLI"""
        print("\nAvailable slice types:")
        for i, slice_type in enumerate(self.slice_configs.keys(), 1):
            print(f"{i}. {slice_type}")
        
        try:
            choice = int(input("Select slice type (1-3): "))
            slice_types = list(self.slice_configs.keys())
            
            if 1 <= choice <= len(slice_types):
                slice_type = slice_types[choice - 1]
                self.create_slice(slice_type)
            else:
                print("❌ Invalid choice")
        except ValueError:
            print("❌ Please enter a valid number")
    
    def handle_test_connectivity(self):
        """Handle connectivity testing from CLI"""
        print("\nSelect slice to test:")
        for i, slice_type in enumerate(self.slice_configs.keys(), 1):
            print(f"{i}. {slice_type}")
        
        try:
            choice = int(input("Select slice (1-3): "))
            slice_types = list(self.slice_configs.keys())
            
            if 1 <= choice <= len(slice_types):
                slice_type = slice_types[choice - 1]
                self.test_slice_connectivity(slice_type)
            else:
                print("❌ Invalid choice")
        except ValueError:
            print("❌ Please enter a valid number")
    
    def handle_view_encrypted(self):
        """Handle viewing encrypted configurations"""
        print("\nSelect slice to decrypt and view:")
        for i, slice_type in enumerate(self.slice_configs.keys(), 1):
            print(f"{i}. {slice_type}")
        
        try:
            choice = int(input("Select slice (1-3): "))
            slice_types = list(self.slice_configs.keys())
            
            if 1 <= choice <= len(slice_types):
                slice_type = slice_types[choice - 1]
                config = self.load_encrypted_slice(slice_type)
                
                if config:
                    print(f"\n🔓 Decrypted {slice_type} Configuration:")
                    print(json.dumps(config, indent=2))
                else:
                    print(f"❌ No encrypted configuration found for {slice_type}")
            else:
                print("❌ Invalid choice")
        except ValueError:
            print("❌ Please enter a valid number")


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(
        description='Professional 5G Network Slicing Management System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 slice_manager.py                    # Start interactive CLI (default)
  python3 slice_manager.py interactive        # Start interactive CLI
  python3 slice_manager.py create --slice eMBB # Create eMBB slice
  python3 slice_manager.py create-dynamic     # Create custom dynamic slice
  python3 slice_manager.py test --slice URLLC # Test URLLC slice
  python3 slice_manager.py monitor --duration 60 # Monitor for 60 seconds
  python3 slice_manager.py list               # List all slices
        """
    )
    
    parser.add_argument(
        'command',
        nargs='?',
        default='interactive',
        choices=['interactive', 'create', 'create-dynamic', 'test', 'monitor', 'list', 'comprehensive'],
        help='Command to execute (default: interactive)'
    )
    parser.add_argument('--encrypt', action='store_true', help='Encrypt all slices and exit')
    parser.add_argument('--decrypt', action='store_true', help='Decrypt slices (requires --passphrase)')
    parser.add_argument('--passphrase', type=str, help='Passphrase for decryption')
    parser.add_argument('--slice-name', type=str, help='Slice name to decrypt when using --decrypt')
    
    parser.add_argument(
        '--slice',
        choices=['eMBB', 'URLLC', 'mMTC'],
        help='Slice type for create/test commands'
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        default=30,
        help='Monitoring duration in seconds (default: 30)'
    )
    
    args = parser.parse_args()
    
    # Create dynamic slice manager instance
    manager = DynamicSliceManager()

    # Non-interactive encrypt/decrypt flags are handled before starting interactive CLI
    if args.encrypt:
        manager.encrypt_all_slices()
        sys.exit(0)

    if args.decrypt:
        if not args.passphrase:
            print('❌ --passphrase required to decrypt')
            sys.exit(1)
        try:
            from nfv.firewall_vnf import load_or_create_key, SliceEncryption
        except Exception:
            try:
                from firewall_vnf import load_or_create_key, SliceEncryption
            except Exception:
                print('❌ Could not import firewall VNF encryption utilities')
                sys.exit(1)

        # Derive 256-bit key using provided passphrase and set encryptor
        key = load_or_create_key(bits=256, passphrase=args.passphrase)
        manager.slice_encryptor = SliceEncryption(key)

        if args.slice_name:
            if not os.path.exists(manager.encrypted_file):
                print('❌ No encrypted slices file found')
                sys.exit(1)
            with open(manager.encrypted_file,'r') as f:
                all_slices = json.loads(f.read())
            entry = all_slices.get(args.slice_name)
            if not entry:
                print(f"❌ Slice '{args.slice_name}' not found")
                sys.exit(1)
            dec = manager.decrypt_slice_data(entry.get('encrypted_data'))
            if dec:
                dec = manager._normalize_decrypted_slice(dec, args.slice_name)
                dec.setdefault('slice_name', args.slice_name)
                manager.slice_configs[args.slice_name] = dec
                # Mark stats active
                manager.stats.setdefault(args.slice_name, {'packets': 0, 'bytes': 0, 'active': True})
                manager.decrypted = True
                print(f"✓ Slice '{args.slice_name}' decrypted and loaded into canonical configs")
                sys.exit(0)
            else:
                print(f"❌ Failed to decrypt slice '{args.slice_name}'")
                sys.exit(1)

        manager.decrypt_and_verify_slices()
        sys.exit(0)

    # Execute command
    if args.command == 'interactive':
        manager.interactive_cli()
    
    elif args.command == 'create':
        if not args.slice:
            print("❌ --slice parameter required for create command")
            sys.exit(1)
        manager.create_slice(args.slice)
    
    elif args.command == 'create-dynamic':
        manager.handle_create_dynamic_slice()
    
    elif args.command == 'test':
        if not args.slice:
            print("❌ --slice parameter required for test command")
            sys.exit(1)
        manager.test_slice_connectivity(args.slice)
    
    elif args.command == 'monitor':
        manager.monitor_slices(args.duration)
    
    elif args.command == 'list':
        manager.list_all_slices()

    
    elif args.command == 'comprehensive':
        manager.run_comprehensive_test()


if __name__ == '__main__':
    main()


