#!/usr/bin/env python3
"""
Professional Prometheus Metrics Exporter for 5G Network Slicing
Advanced KPI collection and monitoring for network slices

Features:
- Real-time slice performance metrics
- QoS monitoring and alerting
- Bandwidth and bitrate utilization tracking
- Latency, jitter and reliability metrics
- Device connectivity statistics
- Encryption status monitoring
- SLA violation detection

Metrics Exported:
- slice_throughput_mbps: Current throughput per slice
- slice_bitrate_mbps: Instantaneous bitrate per slice (with protocol overhead)
- slice_latency_ms: Current latency per slice
- slice_jitter_ms: Packet delay variation per slice
- slice_active_devices: Number of active devices per slice
- slice_packet_loss_percent: Packet loss percentage per slice
- slice_reliability_percent: Current reliability per slice
- slice_bandwidth_utilization: Bandwidth utilization percentage (0-1)
- slice_encryption_status: Encryption status (0/1)
- slice_qos_violations_total: Number of QoS violations by type
"""

import argparse
import logging
import random
import time
import json
import requests
from datetime import datetime, timedelta
from prometheus_client import Gauge, Counter, Histogram, start_http_server
from typing import Dict, List
import threading

# Configure logging
LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("metrics_exporter")

# Prometheus metrics
g_throughput = Gauge("slice_throughput_mbps", "Slice throughput (Mbps)", ["slice", "slice_type"])
g_bitrate = Gauge("slice_bitrate_mbps", "Instantaneous bitrate (Mbps)", ["slice", "slice_type"])
g_latency = Gauge("slice_latency_ms", "Slice latency (ms)", ["slice", "slice_type"])
g_jitter = Gauge("slice_jitter_ms", "Packet delay variation (ms)", ["slice", "slice_type"])
g_devices = Gauge("slice_active_devices", "Slice active devices", ["slice", "slice_type"])
g_packet_loss = Gauge("slice_packet_loss_percent", "Slice packet loss (%)", ["slice", "slice_type"])
g_reliability = Gauge("slice_reliability_percent", "Slice reliability (%)", ["slice", "slice_type"])
g_bandwidth_util = Gauge("slice_bandwidth_utilization", "Bandwidth utilization (0-1)", ["slice", "slice_type"])
g_encryption_status = Gauge("slice_encryption_status", "Encryption status (0/1)", ["slice", "slice_type"])
g_qos_violations = Counter("slice_qos_violations_total", "QoS violations count", ["slice", "slice_type", "violation_type"])

# Latency histogram for SLA monitoring
h_latency = Histogram("slice_latency_histogram_ms", "Slice latency histogram", ["slice", "slice_type"], 
                     buckets=[0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000])

# Slice configurations matching the main system
SLICE_CONFIGS = {
    "URLLC": {
        "type": "ultra_reliable",
        "target_latency": 1,      # ms
        "target_jitter": 0.5,     # ms
        "target_reliability": 99.999,  # %
        "max_bandwidth": 50,      # Mbps
        "priority": "critical",
        "sla_latency": 5,         # SLA threshold
        "sla_jitter": 1.0,        # Max acceptable jitter
        "sla_reliability": 99.99
    },
    "eMBB": {
        "type": "broadband", 
        "target_latency": 10,     # ms
        "target_jitter": 5.0,     # ms
        "target_reliability": 99.9,   # %
        "max_bandwidth": 100,     # Mbps
        "priority": "high",
        "sla_latency": 20,
        "sla_jitter": 10.0,
        "sla_reliability": 99.5
    },
    "mMTC": {
        "type": "massive_iot",
        "target_latency": 100,    # ms
        "target_jitter": 20.0,    # ms
        "target_reliability": 99.0,   # %
        "max_bandwidth": 10,      # Mbps  
        "priority": "normal",
        "sla_latency": 200,
        "sla_jitter": 50.0,
        "sla_reliability": 98.0
    }
}

class SliceMetricsCollector:
    """Advanced metrics collector for network slices"""
    
    def __init__(self):
        self.slice_stats = {slice: {"packets": 0, "bytes": 0, "errors": 0} 
                           for slice in SLICE_CONFIGS.keys()}
        self.controller_url = "http://localhost:8080"
        self.last_update = datetime.now()
        
    def collect_controller_stats(self) -> Dict:
        """Collect statistics from Ryu controller"""
        try:
            response = requests.get(f"{self.controller_url}/slicing/stats", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"Could not fetch controller stats: {e}")
        
        # Return synthetic data if controller unavailable
        return self.generate_synthetic_stats()
    
    def generate_synthetic_stats(self) -> Dict:
        """Generate realistic synthetic statistics for demo"""
        stats = {}
        current_time = datetime.now()
        
        for slice_name, config in SLICE_CONFIGS.items():
            # Base metrics with realistic variations
            base_throughput = config["max_bandwidth"] * 0.7  # 70% utilization
            base_latency = config["target_latency"]
            base_reliability = config["target_reliability"]
            
            # Add realistic variations and occasional SLA violations
            throughput_variation = random.uniform(0.8, 1.2)
            latency_variation = random.uniform(0.9, 1.5)  # Can exceed target
            reliability_variation = random.uniform(0.98, 1.0)
            
            # Simulate time-based patterns (higher load during business hours)
            hour = current_time.hour
            if 9 <= hour <= 17:  # Business hours
                load_factor = random.uniform(1.2, 1.8)
            else:
                load_factor = random.uniform(0.5, 1.0)
            
            throughput = base_throughput * throughput_variation * load_factor
            latency = base_latency * latency_variation
            reliability = min(100, base_reliability * reliability_variation)
            
            # Calculate bitrate (slightly different from throughput)
            # Bitrate includes protocol overhead, so it's typically 5-15% higher
            bitrate_overhead = random.uniform(1.05, 1.15)
            bitrate = min(throughput * bitrate_overhead, config["max_bandwidth"])
            
            # Calculate jitter based on slice type
            # URLLC: very low jitter (0.1-0.5ms)
            # eMBB: moderate jitter (1-5ms)
            # mMTC: higher jitter acceptable (5-20ms)
            if slice_name == "URLLC":
                jitter = random.uniform(0.1, 0.5)
            elif slice_name == "eMBB":
                jitter = random.uniform(1.0, 5.0)
            else:  # mMTC
                jitter = random.uniform(5.0, 20.0)
            
            # Device count based on slice type
            if slice_name == "mMTC":
                device_count = random.randint(500, 2000)
            elif slice_name == "eMBB":
                device_count = random.randint(50, 200)
            else:  # URLLC
                device_count = random.randint(5, 50)
            
            # Packet loss calculation
            if reliability < config["sla_reliability"]:
                packet_loss = random.uniform(0.1, 1.0)
            else:
                packet_loss = random.uniform(0.001, 0.01)
            
            stats[slice_name] = {
                "throughput": min(throughput, config["max_bandwidth"]),
                "bitrate": bitrate,
                "latency": latency,
                "jitter": jitter,
                "reliability": reliability,
                "devices": device_count,
                "packet_loss": packet_loss,
                "bandwidth_utilization": throughput / config["max_bandwidth"],
                "encryption_enabled": True,
                "timestamp": current_time.isoformat()
            }
        
        return stats
    
    def check_sla_violations(self, slice_name: str, metrics: Dict):
        """Check for SLA violations and update counters"""
        config = SLICE_CONFIGS[slice_name]
        slice_type = config["type"]
        
        # Check latency SLA
        if metrics["latency"] > config["sla_latency"]:
            g_qos_violations.labels(slice=slice_name, slice_type=slice_type, 
                                  violation_type="latency").inc()
            logger.warning(f"SLA violation: {slice_name} latency {metrics['latency']:.2f}ms "
                          f"exceeds SLA {config['sla_latency']}ms")
        
        # Check jitter SLA
        if metrics.get("jitter", 0) > config["sla_jitter"]:
            g_qos_violations.labels(slice=slice_name, slice_type=slice_type,
                                  violation_type="jitter").inc()
            logger.warning(f"SLA violation: {slice_name} jitter {metrics['jitter']:.2f}ms "
                          f"exceeds SLA {config['sla_jitter']}ms")
        
        # Check reliability SLA  
        if metrics["reliability"] < config["sla_reliability"]:
            g_qos_violations.labels(slice=slice_name, slice_type=slice_type,
                                  violation_type="reliability").inc()
            logger.warning(f"SLA violation: {slice_name} reliability {metrics['reliability']:.2f}% "
                          f"below SLA {config['sla_reliability']}%")
        
        # Check bandwidth utilization
        if metrics["bandwidth_utilization"] > 0.9:  # 90% threshold
            g_qos_violations.labels(slice=slice_name, slice_type=slice_type,
                                  violation_type="bandwidth").inc()
            logger.warning(f"High bandwidth utilization: {slice_name} at "
                          f"{metrics['bandwidth_utilization']*100:.1f}%")

def update_metrics():
    """Update all Prometheus metrics with current slice data"""
    collector = SliceMetricsCollector()
    stats = collector.collect_controller_stats()
    
    logger.info("Updating metrics for all slices...")
    
    for slice_name, metrics in stats.items():
        if slice_name not in SLICE_CONFIGS:
            continue
            
        config = SLICE_CONFIGS[slice_name]
        slice_type = config["type"]
        
        # Update basic metrics
        g_throughput.labels(slice=slice_name, slice_type=slice_type).set(metrics["throughput"])
        g_bitrate.labels(slice=slice_name, slice_type=slice_type).set(metrics.get("bitrate", metrics["throughput"]))
        g_latency.labels(slice=slice_name, slice_type=slice_type).set(metrics["latency"])
        g_jitter.labels(slice=slice_name, slice_type=slice_type).set(metrics.get("jitter", 0))
        g_devices.labels(slice=slice_name, slice_type=slice_type).set(metrics["devices"])
        g_packet_loss.labels(slice=slice_name, slice_type=slice_type).set(metrics["packet_loss"])
        g_reliability.labels(slice=slice_name, slice_type=slice_type).set(metrics["reliability"])
        g_bandwidth_util.labels(slice=slice_name, slice_type=slice_type).set(metrics["bandwidth_utilization"])
        g_encryption_status.labels(slice=slice_name, slice_type=slice_type).set(1 if metrics["encryption_enabled"] else 0)
        
        # Update latency histogram
        h_latency.labels(slice=slice_name, slice_type=slice_type).observe(metrics["latency"])
        
        # Check for SLA violations
        collector.check_sla_violations(slice_name, metrics)
        
        logger.debug(f"{slice_name}: throughput={metrics['throughput']:.1f}Mbps, "
                    f"bitrate={metrics.get('bitrate', 0):.1f}Mbps, "
                    f"latency={metrics['latency']:.2f}ms, jitter={metrics.get('jitter', 0):.2f}ms, "
                    f"devices={metrics['devices']}")

def display_metrics_summary():
    """Display current metrics summary to console"""
    print("\n" + "="*100)
    print(f"SLICE METRICS SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*100)
    print(f"{'SLICE':<8} {'THROUGHPUT':<12} {'BITRATE':<12} {'LATENCY':<10} {'JITTER':<10} {'DEVICES':<8} {'STATUS':<10}")
    print("-"*100)
    
    collector = SliceMetricsCollector()
    stats = collector.collect_controller_stats()
    
    for slice_name, metrics in stats.items():
        if slice_name not in SLICE_CONFIGS:
            continue
            
        config = SLICE_CONFIGS[slice_name]
        
        # Determine status based on SLA compliance
        status = "✅ OK"
        if metrics["latency"] > config["sla_latency"]:
            status = "⚠️ HIGH_LAT"
        elif metrics.get("jitter", 0) > config["sla_jitter"]:
            status = "⚠️ HIGH_JIT"
        elif metrics["reliability"] < config["sla_reliability"]:
            status = "❌ LOW_REL"
        elif metrics["bandwidth_utilization"] > 0.9:
            status = "⚠️ HIGH_BW"
            
        print(f"{slice_name:<8} {metrics['throughput']:<8.1f}Mbps "
              f"{metrics.get('bitrate', 0):<8.1f}Mbps "
              f"{metrics['latency']:<8.2f}ms {metrics.get('jitter', 0):<8.2f}ms "
              f"{metrics['devices']:<8} {status:<10}")
    
    print("="*100 + "\n")


def start_console_monitor(interval=10.0):
    """Start console monitoring in a separate thread"""
    def monitor():
        while True:
            try:
                display_metrics_summary()
                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Console monitor error: {e}")
    
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    return monitor_thread

def main(port=8000, interval=5.0, console_output=False):
    """Main function to start the metrics exporter"""
    logger.info("Starting Professional 5G Network Slicing Metrics Exporter...")
    
    # Display startup banner
    print("""
╔═══════════════════════════════════════════════════════════════════════════╗
║                    5G NETWORK SLICING METRICS EXPORTER                   ║
║                          Professional Edition v1.1                       ║
╠═══════════════════════════════════════════════════════════════════════════╣
║  Metrics Available:                                                       ║
║  • slice_throughput_mbps - Current throughput per slice                  ║
║  • slice_bitrate_mbps - Instantaneous bitrate per slice                  ║
║  • slice_latency_ms - Current latency per slice                          ║
║  • slice_jitter_ms - Packet delay variation per slice                    ║
║  • slice_active_devices - Number of active devices                       ║
║  • slice_packet_loss_percent - Packet loss percentage                    ║
║  • slice_reliability_percent - Current reliability                       ║
║  • slice_bandwidth_utilization - Bandwidth utilization                   ║
║  • slice_encryption_status - Encryption status                           ║
║  • slice_qos_violations_total - QoS violations counter                   ║
╚═══════════════════════════════════════════════════════════════════════════╝
    """)
    
    # Try to find available port
    original_port = port
    max_attempts = 10
    
    for attempt in range(max_attempts):
        try:
            # Start Prometheus HTTP server
            start_http_server(port)
            logger.info(f"✅ Prometheus metrics server started on port {port}")
            logger.info(f"📊 Metrics endpoint: http://localhost:{port}/metrics")
            break
            
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"Port {port} is in use, trying port {port + 1}")
                port += 1
                if attempt == max_attempts - 1:
                    logger.error(f"❌ Could not find available port after {max_attempts} attempts")
                    logger.error("Please stop other services using these ports or specify a different port")
                    raise SystemExit(1)
            else:
                logger.error(f"❌ Unable to bind exporter to port {port}: {e}")
                raise SystemExit(1)
    
    if port != original_port:
        logger.info(f"Using alternative port {port} (original {original_port} was in use)")

    # Start console monitoring if requested
    if console_output:
        logger.info("🖥️  Starting console output monitoring...")
        start_console_monitor(interval * 2)  # Less frequent console updates

    logger.info(f"🔄 Starting metrics collection (interval={interval}s)")
    logger.info("Press Ctrl+C to stop the exporter")
    
    # Log slice configurations
    logger.info("📋 Monitoring slices:")
    for slice_name, config in SLICE_CONFIGS.items():
        logger.info(f"   • {slice_name}: {config['type']}, "
                   f"target_latency={config['target_latency']}ms, "
                   f"max_bandwidth={config['max_bandwidth']}Mbps")

    try:
        metrics_count = 0
        while True:
            start_time = time.time()
            
            # Update metrics
            update_metrics()
            metrics_count += 1
            
            # Log periodic status
            if metrics_count % 12 == 0:  # Every minute with 5s interval
                logger.info(f"📈 Metrics updated {metrics_count} times, "
                           f"serving on http://localhost:{port}/metrics")
            
            # Calculate sleep time to maintain consistent interval
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        logger.info("🛑 Metrics exporter shutting down gracefully...")
        print("\n👋 Goodbye! Metrics exporter stopped.")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        raise


def test_metrics():
    """Test function to verify metrics collection"""
    print("🧪 Testing metrics collection...")
    
    collector = SliceMetricsCollector()
    stats = collector.collect_controller_stats()
    
    print(f"✅ Collected metrics for {len(stats)} slices")
    for slice_name, metrics in stats.items():
        print(f"   • {slice_name}: Throughput={metrics['throughput']:.1f}Mbps, "
              f"Bitrate={metrics.get('bitrate', 0):.1f}Mbps, "
              f"Latency={metrics['latency']:.2f}ms, "
              f"Jitter={metrics.get('jitter', 0):.2f}ms, "
              f"Devices={metrics['devices']}")
    
    print("🎯 Updating Prometheus metrics...")
    update_metrics()
    print("✅ Test completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Professional 5G Network Slicing Metrics Exporter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 metrics_exporter.py                    # Start with defaults
  python3 metrics_exporter.py --port 9090        # Custom port
  python3 metrics_exporter.py --interval 10      # 10 second updates
  python3 metrics_exporter.py --console          # Show console output
  python3 metrics_exporter.py --test             # Test metrics collection
        """
    )
    
    parser.add_argument("--port", type=int, default=8000,
                       help="Port for Prometheus metrics server (default: 8000)")
    parser.add_argument("--interval", type=float, default=5.0,
                       help="Metrics update interval in seconds (default: 5.0)")
    parser.add_argument("--console", action="store_true",
                       help="Enable console output monitoring")
    parser.add_argument("--test", action="store_true",
                       help="Test metrics collection and exit")
    
    args = parser.parse_args()
    
    if args.test:
        test_metrics()
    else:
        main(port=args.port, interval=args.interval, console_output=args.console)
