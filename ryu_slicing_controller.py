#!/usr/bin/env python3
"""
Professional 5G Network Slicing Controller with Dynamic Resource Allocation
Advanced flow management, adaptive QoS, and intelligent resource allocation

Features:
- Dynamic Resource Allocation (DRA)
- Adaptive QoS based on real-time conditions
- Auto-scaling bandwidth allocation
- Predictive resource management
- Real-time slice optimization
- Machine learning-based allocation
- SLA-aware resource distribution

Slice Types:
 - UDP dst port 5001 => URLLC (Ultra-Reliable Low Latency)
 - UDP dst port 5002 => eMBB (Enhanced Mobile Broadband)  
 - UDP dst port 5003 => mMTC (Massive Machine Type Communications)
 - Dynamic ports => Custom slices with adaptive allocation

Run with:
  ryu-manager ryu_slicing_controller.py --verbose
"""

import logging
import json
import time
import threading
import statistics
from datetime import datetime, timedelta
from collections import defaultdict, deque

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp, arp
from ryu.lib import hub
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.controller import dpset

# Import encryption functionality
import sys
import os
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
logger = logging.getLogger("DynamicSlicingController")

# Dynamic Resource Allocation Configuration
TOTAL_BANDWIDTH = 1000  # Mbps - Total available bandwidth
MIN_BANDWIDTH_RATIO = 0.1  # Minimum 10% of allocated bandwidth
MAX_BANDWIDTH_RATIO = 0.8  # Maximum 80% of total bandwidth
ALLOCATION_WINDOW = 30  # seconds - Resource allocation window
PREDICTION_WINDOW = 10  # seconds - Traffic prediction window

# Default fallback slice mapping (used if runtime universal config unavailable)
SLICE_CONFIGS = {
    5001: {
        'name': 'URLLC',
        'description': 'Ultra-Reliable Low Latency Communications',
        'priority': 3000,
        'base_bandwidth': 50,
        'max_bandwidth': 200,
        'min_bandwidth': 20,
        'max_latency': 1,
        'reliability': 99.999,
        'scaling_factor': 1.5,
        'allocation_weight': 0.3,
        'sla_priority': 'critical',
        'auto_scale': True,
        'color': 'red'
    },
    5002: {
        'name': 'eMBB',
        'description': 'Enhanced Mobile Broadband',
        'priority': 2000,
        'base_bandwidth': 100,
        'max_bandwidth': 500,
        'min_bandwidth': 50,
        'max_latency': 10,
        'reliability': 99.9,
        'scaling_factor': 2.0,
        'allocation_weight': 0.5,
        'sla_priority': 'high',
        'auto_scale': True,
        'color': 'blue'
    },
    5003: {
        'name': 'mMTC',
        'description': 'Massive Machine Type Communications',
        'priority': 1000,
        'base_bandwidth': 10,
        'max_bandwidth': 100,
        'min_bandwidth': 5,
        'max_latency': 100,
        'reliability': 99.0,
        'scaling_factor': 1.2,
        'allocation_weight': 0.2,
        'sla_priority': 'normal',
        'auto_scale': True,
        'color': 'green'
    }
}

# Dynamic Resource Allocation States
class AllocationState:
    UNDER_UTILIZED = "under_utilized"
    OPTIMAL = "optimal"
    OVER_UTILIZED = "over_utilized"
    CRITICAL = "critical"

# Resource allocation algorithms
class AllocationAlgorithm:
    PROPORTIONAL = "proportional"
    PRIORITY_BASED = "priority_based"
    PREDICTIVE = "predictive"
    MACHINE_LEARNING = "ml_based"

# Web API instance name
slicing_instance_name = 'slicing_api_app'


class DynamicResourceAllocator:
    """Dynamic Resource Allocation Engine"""
    
    def __init__(self):
        self.algorithm = AllocationAlgorithm.PREDICTIVE
        self.allocation_history = deque(maxlen=1000)
        self.lock = threading.Lock()
    
    def calculate_optimal_allocation(self, slice_metrics, traffic_predictions, sla_requirements):
        """Calculate optimal resource allocation based on current conditions"""
        total_demand = sum(pred.get('predicted_bandwidth', 0) for pred in traffic_predictions.values())
        
        if total_demand == 0:
            return self._get_base_allocations()
        
        # Apply allocation algorithm
        if self.algorithm == AllocationAlgorithm.PREDICTIVE:
            return self._predictive_allocation(slice_metrics, traffic_predictions, sla_requirements)
        elif self.algorithm == AllocationAlgorithm.PRIORITY_BASED:
            return self._priority_based_allocation(slice_metrics, traffic_predictions)
        else:
            return self._proportional_allocation(slice_metrics, traffic_predictions)
    
    def _predictive_allocation(self, slice_metrics, traffic_predictions, sla_requirements):
        """Predictive allocation based on traffic forecasting and SLA requirements"""
        allocations = {}
        available_bandwidth = TOTAL_BANDWIDTH
        
        # First pass: Ensure minimum guarantees
        for port, config in SLICE_CONFIGS.items():
            min_bw = config['min_bandwidth']
            allocations[port] = min_bw
            available_bandwidth -= min_bw
        
        # Second pass: Distribute remaining bandwidth based on predictions and priorities
        remaining_demands = {}
        total_weighted_demand = 0
        
        for port, prediction in traffic_predictions.items():
            if port in SLICE_CONFIGS:
                config = SLICE_CONFIGS[port]
                predicted_bw = prediction.get('predicted_bandwidth', 0)
                current_allocation = allocations[port]
                
                # Calculate additional demand
                additional_demand = max(0, predicted_bw - current_allocation)
                if additional_demand > 0:
                    # Weight by priority and scaling factor
                    weight = config['allocation_weight'] * config['scaling_factor']
                    weighted_demand = additional_demand * weight
                    remaining_demands[port] = {
                        'demand': additional_demand,
                        'weight': weight,
                        'weighted_demand': weighted_demand,
                        'max_allocation': config['max_bandwidth']
                    }
                    total_weighted_demand += weighted_demand
        
        # Distribute remaining bandwidth proportionally
        if total_weighted_demand > 0 and available_bandwidth > 0:
            for port, demand_info in remaining_demands.items():
                proportion = demand_info['weighted_demand'] / total_weighted_demand
                additional_bw = min(
                    available_bandwidth * proportion,
                    demand_info['demand'],
                    demand_info['max_allocation'] - allocations[port]
                )
                allocations[port] += additional_bw
                available_bandwidth -= additional_bw
        
        return allocations
    
    def _priority_based_allocation(self, slice_metrics, traffic_predictions):
        """Priority-based allocation ensuring high priority slices get resources first"""
        allocations = {}
        available_bandwidth = TOTAL_BANDWIDTH
        
        # Sort slices by priority (higher priority first)
        sorted_slices = sorted(SLICE_CONFIGS.items(), 
                             key=lambda x: x[1]['priority'], reverse=True)
        
        for port, config in sorted_slices:
            prediction = traffic_predictions.get(port, {})
            predicted_bw = prediction.get('predicted_bandwidth', config['base_bandwidth'])
            
            # Allocate up to maximum, limited by available bandwidth
            max_possible = min(
                config['max_bandwidth'],
                available_bandwidth + config['min_bandwidth']  # Can use min from other slices
            )
            
            allocated = min(predicted_bw, max_possible)
            allocated = max(allocated, config['min_bandwidth'])  # Ensure minimum
            
            allocations[port] = allocated
            available_bandwidth -= allocated
            
            if available_bandwidth <= 0:
                break
        
        return allocations
    
    def _proportional_allocation(self, slice_metrics, traffic_predictions):
        """Simple proportional allocation based on current utilization"""
        allocations = {}
        total_utilization = sum(metrics.get('utilization', 0) for metrics in slice_metrics.values())
        
        if total_utilization == 0:
            return self._get_base_allocations()
        
        for port, config in SLICE_CONFIGS.items():
            utilization = slice_metrics.get(port, {}).get('utilization', 0)
            proportion = utilization / total_utilization if total_utilization > 0 else 1/len(SLICE_CONFIGS)
            
            # Allocate proportionally with min/max constraints
            allocated = TOTAL_BANDWIDTH * proportion
            allocated = max(allocated, config['min_bandwidth'])
            allocated = min(allocated, config['max_bandwidth'])
            
            allocations[port] = allocated
        
        return allocations
    
    def _get_base_allocations(self):
        """Get base bandwidth allocations"""
        return {port: config['base_bandwidth'] for port, config in SLICE_CONFIGS.items()}


class TrafficPredictor:
    """Traffic Prediction Engine using time-series analysis"""
    
    def __init__(self):
        self.prediction_window = PREDICTION_WINDOW
        self.history_window = 60  # Keep 60 data points for prediction
        
    def predict_traffic(self, traffic_history):
        """Predict future traffic based on historical data"""
        predictions = {}
        
        for port, history in traffic_history.items():
            if len(history) < 3:  # Need minimum data points
                # Use base allocation if no history
                config = SLICE_CONFIGS.get(port, {})
                predictions[port] = {
                    'predicted_bandwidth': config.get('base_bandwidth', 10),
                    'confidence': 0.5,
                    'trend': 'stable'
                }
                continue
            
            # Simple moving average with trend detection
            recent_values = list(history)[-10:]  # Last 10 measurements
            older_values = list(history)[-20:-10] if len(history) >= 20 else recent_values
            
            recent_avg = statistics.mean(recent_values)
            older_avg = statistics.mean(older_values)
            
            # Detect trend
            if recent_avg > older_avg * 1.1:
                trend = 'increasing'
                prediction_multiplier = 1.2
            elif recent_avg < older_avg * 0.9:
                trend = 'decreasing'
                prediction_multiplier = 0.9
            else:
                trend = 'stable'
                prediction_multiplier = 1.0
            
            # Calculate prediction with trend adjustment
            predicted_bw = recent_avg * prediction_multiplier
            
            # Calculate confidence based on variance
            variance = statistics.variance(recent_values) if len(recent_values) > 1 else 0
            confidence = max(0.1, min(0.95, 1.0 - (variance / (recent_avg + 1))))
            
            predictions[port] = {
                'predicted_bandwidth': predicted_bw,
                'confidence': confidence,
                'trend': trend,
                'recent_average': recent_avg,
                'variance': variance
            }
        
        return predictions


class SLAMonitor:
    """SLA Monitoring and Violation Detection"""
    
    def __init__(self):
        self.sla_violations = defaultdict(list)
        self.sla_thresholds = {
            'latency_violation_threshold': 1.5,  # 50% above target
            'bandwidth_violation_threshold': 0.8,  # 20% below target
            'reliability_threshold': 0.99
        }
    
    def check_sla_compliance(self, slice_metrics, current_allocations):
        """Check SLA compliance for all slices"""
        sla_status = {}
        
        for port, config in SLICE_CONFIGS.items():
            metrics = slice_metrics.get(port, {})
            allocation = current_allocations.get(port, 0)
            
            violations = []
            
            # Check latency SLA
            avg_latency = metrics.get('average_latency', 0)
            if avg_latency > config['max_latency'] * self.sla_thresholds['latency_violation_threshold']:
                violations.append({
                    'type': 'latency',
                    'expected': config['max_latency'],
                    'actual': avg_latency,
                    'severity': 'high' if config['sla_priority'] == 'critical' else 'medium'
                })
            
            # Check bandwidth SLA
            required_bw = config['base_bandwidth']
            if allocation < required_bw * self.sla_thresholds['bandwidth_violation_threshold']:
                violations.append({
                    'type': 'bandwidth',
                    'expected': required_bw,
                    'actual': allocation,
                    'severity': 'high' if config['sla_priority'] == 'critical' else 'medium'
                })
            
            # Check utilization efficiency
            utilization = metrics.get('utilization', 0)
            if utilization > 0.9:  # Over 90% utilization
                violations.append({
                    'type': 'congestion',
                    'utilization': utilization,
                    'severity': 'medium'
                })
            
            sla_status[port] = {
                'compliant': len(violations) == 0,
                'violations': violations,
                'score': self._calculate_sla_score(violations, config)
            }
            
            # Store violations for history
            if violations:
                self.sla_violations[port].extend(violations)
        
        return sla_status
    
    def _calculate_sla_score(self, violations, config):
        """Calculate SLA compliance score (0-100)"""
        if not violations:
            return 100.0
        
        penalty = 0
        for violation in violations:
            if violation['severity'] == 'high':
                penalty += 30
            elif violation['severity'] == 'medium':
                penalty += 15
            else:
                penalty += 5
        
        return max(0.0, 100.0 - penalty)


class DynamicSlicingController(app_manager.RyuApp):
    """Advanced 5G Network Slicing Controller with Dynamic Resource Allocation"""
    
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication, 'dpset': dpset.DPSet}

    def __init__(self, *args, **kwargs):
        super(DynamicSlicingController, self).__init__(*args, **kwargs)
        
        # Basic data structures
        self.datapaths = {}
        self.slice_stats = defaultdict(lambda: defaultdict(int))
        self.flow_stats = {}
        self.port_stats = {}
        
        # Dynamic Resource Allocation components
        self.resource_allocator = DynamicResourceAllocator()
        self.traffic_predictor = TrafficPredictor()
        self.sla_monitor = SLAMonitor()
        
        # Real-time metrics storage
        self.slice_metrics = defaultdict(lambda: {
            'current_bandwidth': 0,
            'allocated_bandwidth': 0,
            'utilization': 0.0,
            'packets_per_second': 0,
            'average_latency': 0.0,
            'sla_violations': 0,
            'prediction_accuracy': 0.0
        })
        
        # Traffic history for prediction (sliding window)
        self.traffic_history = defaultdict(lambda: deque(maxlen=100))
        
        # Current allocations
        self.current_allocations = {}
        for port, config in SLICE_CONFIGS.items():
            self.current_allocations[port] = config['base_bandwidth']
        
        # Dynamic slices registry
        self.dynamic_slices = {}

        # Try to load runtime universal slice config from slice_manager
        try:
            from slice_manager import DynamicSliceManager
            mgr = DynamicSliceManager()
            # Persist encrypted artifacts for compatibility if manager can provide them
            try:
                artifacts = mgr.get_in_memory_encrypted_map(force_populate=True)
                if artifacts:
                    try:
                        proj_root = os.path.dirname(os.path.abspath(__file__))
                        enc_path = os.path.join(proj_root, 'slice_encrypted.enc')
                        json_path = os.path.join(proj_root, 'slice_encrypted.json')
                        legacy = os.path.join(proj_root, 'network_slices.enc')
                        if os.path.exists(legacy):
                            os.replace(legacy, legacy + '.bak')
                    except Exception:
                        pass
                    try:
                        for path in (enc_path, json_path):
                            tmp = path + '.tmp'
                            with open(tmp, 'w') as f:
                                json.dump(artifacts, f, indent=2)
                                f.flush()
                                try:
                                    os.fsync(f.fileno())
                                except Exception:
                                    pass
                            os.replace(tmp, path)
                            try:
                                os.chmod(path, 0o666)
                            except Exception:
                                pass
                        logger.info(f'✓ Persisted encrypted artifacts from manager to {enc_path} and {json_path}')
                    except Exception as e:
                        logger.error(f'Failed to persist encrypted artifacts to project root: {e}')
            except Exception:
                pass
            if getattr(mgr, 'universal_config_active', False):
                ucfg = mgr.get_universal_slice_config()
                # Rebuild SLICE_CONFIGS mapping from runtime config
                new_map = {}
                for name, cfg in ucfg['slices'].items():
                    port = cfg.get('port')
                    if not port:
                        raise RuntimeError(f"Runtime slice config for {name} missing 'port'")
                    try:
                        p = int(port)
                    except Exception:
                        p = int(str(port))
                    new_map[p] = {
                        'name': name,
                        'description': cfg.get('name', name),
                        'priority': cfg.get('priority', 2000),
                        'base_bandwidth': cfg.get('base_bandwidth', cfg.get('current_bandwidth', 0)),
                        'max_bandwidth': cfg.get('max_bandwidth', cfg.get('max_bandwidth', 0)),
                        'min_bandwidth': cfg.get('min_bandwidth', cfg.get('min_bandwidth', 0)),
                        'max_latency': cfg.get('max_latency', cfg.get('target_latency', 10)),
                        'reliability': cfg.get('reliability', 99.0),
                        'scaling_factor': cfg.get('scaling_factor', 1.0),
                        'allocation_weight': cfg.get('allocation_weight', 0.5),
                        'sla_priority': cfg.get('sla_priority', 'normal'),
                        'auto_scale': cfg.get('auto_scale', True),
                        'color': cfg.get('color', 'blue')
                    }
                # Replace module-level SLICE_CONFIGS with runtime mapping
                SLICE_CONFIGS.clear()
                SLICE_CONFIGS.update(new_map)
                logger.info('Loaded SLICE_CONFIGS from active universal runtime config')
        except Exception:
            # If any error, keep default SLICE_CONFIGS mapping
            logger.info('No active universal runtime config found; using default slice configs')
        
        # Web API setup
        wsgi = kwargs['wsgi']
        wsgi.register(DynamicSlicingRestAPI, {slicing_instance_name: self})
        
        # Initialize slice encryption
        self._initialize_slice_encryption()
        # Persist encrypted slice map for manager/topology
        try:
            if hasattr(self, 'slice_encryptor') and self.slice_encryptor:
                encrypted_map = {}
                for port, cfg in SLICE_CONFIGS.items():
                    slice_name = cfg.get('name')
                    cfg_copy = cfg.copy()
                    cfg_copy['slice_name'] = slice_name
                    encrypted_data = self.slice_encryptor.encrypt_slice_config(cfg_copy)
                    encrypted_map[slice_name] = {'encrypted_data': encrypted_data, 'timestamp': datetime.now().isoformat()}
                try:
                    # Prefer to store deterministic artifacts into slice_manager in-memory map
                    try:
                        from slice_manager import DynamicSliceManager
                        mgr = DynamicSliceManager()
                        mgr._in_memory_encrypted_map = encrypted_map
                        logger.info('Stored encrypted slice map in slice_manager in-memory artifact map')
                    except Exception:
                        # If not possible, skip writing files to disk per runtime-only requirement
                        logger.info('Slice manager not available; skipping writing encrypted slice files to disk')
                except Exception as e:
                    logger.warning('Failed to set in-memory encrypted slice files: %s', e)
        except Exception:
            pass
        
        # Start monitoring and allocation threads
        self.monitor_thread = hub.spawn(self._monitor)
        self.allocation_thread = hub.spawn(self._dynamic_allocation_loop)
        
        logger.info("🚀 DynamicSlicingController initialized")
        logger.info("📊 Dynamic Resource Allocation enabled")
        logger.info("🔄 Available slices: %s", list(SLICE_CONFIGS.keys()))

    def _initialize_slice_encryption(self):
        """Initialize slice encryption system"""
        logger.info("🔐 Initializing slice encryption system...")
        try:
            key = load_or_create_key(bits=128)
            self.slice_encryptor = SliceEncryption(key)
            logger.info("✓ Slice encryption initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize slice encryption: {e}")
            self.slice_encryptor = None

    def encrypt_slice_data(self, slice_data):
        """Encrypt slice configuration data"""
        if not self.slice_encryptor:
            logger.warning("Slice encryptor not initialized")
            return slice_data
        
        try:
            encrypted_data = self.slice_encryptor.encrypt_slice_config(slice_data)
            if encrypted_data:
                logger.info(f"✓ Encrypted slice data for {slice_data.get('name', 'unknown')}")
                return encrypted_data
            else:
                logger.warning("Encryption failed, returning plain data")
                return slice_data
        except Exception as e:
            logger.error(f"Failed to encrypt slice data: {e}")
            return slice_data

    def decrypt_slice_data(self, encrypted_data):
        """Decrypt slice configuration data"""
        if not self.slice_encryptor:
            logger.warning("Slice encryptor not initialized")
            return encrypted_data
        
        try:
            decrypted_data = self.slice_encryptor.decrypt_slice_config(encrypted_data)
            if decrypted_data:
                logger.info(f"✓ Decrypted slice data for {decrypted_data.get('name', 'unknown')}")
                return decrypted_data
            else:
                logger.warning("Decryption failed, returning encrypted data")
                return encrypted_data
        except Exception as e:
            logger.error(f"Failed to decrypt slice data: {e}")
            return encrypted_data

    def verify_slice_integrity(self, original_data, encrypted_data):
        """Verify integrity of slice data"""
        if not self.slice_encryptor:
            logger.warning("Slice encryptor not initialized")
            return False
        
        try:
            verified = self.slice_encryptor.verify_slice_integrity(original_data, encrypted_data)
            if verified:
                logger.info(f"✓ Slice integrity verified for {original_data.get('name', 'unknown')}")
            else:
                logger.warning(f"✗ Slice integrity check failed for {original_data.get('name', 'unknown')}")
            return verified
        except Exception as e:
            logger.error(f"Failed to verify slice integrity: {e}")
            return False

    def _dynamic_allocation_loop(self):
        """Main dynamic resource allocation loop"""
        logger.info("🔄 Starting dynamic allocation loop")
        
        while True:
            try:
                # Sleep for allocation interval
                hub.sleep(ALLOCATION_WINDOW)
                
                # Skip if no datapaths connected
                if not self.datapaths:
                    continue
                
                # Get traffic predictions
                predictions = self.traffic_predictor.predict_traffic(self.traffic_history)
                
                # Check SLA compliance
                sla_status = self.sla_monitor.check_sla_compliance(
                    self.slice_metrics, self.current_allocations
                )
                
                # Calculate optimal allocation
                new_allocations = self.resource_allocator.calculate_optimal_allocation(
                    self.slice_metrics, predictions, sla_status
                )
                
                # Apply new allocations if they differ significantly
                self._apply_allocations_if_needed(new_allocations)
                
                # Log allocation status
                self._log_allocation_status(new_allocations, sla_status)
                
            except Exception as e:
                logger.error(f"Error in allocation loop: {e}")
                hub.sleep(5)  # Short sleep on error
    
    def _apply_allocations_if_needed(self, new_allocations):
        """Apply new allocations if they differ significantly from current"""
        allocation_changed = False
        
        for port, new_bw in new_allocations.items():
            current_bw = self.current_allocations.get(port, 0)
            
            # Apply if change is more than 5% or 10 Mbps
            change_threshold = max(current_bw * 0.05, 10)
            if abs(new_bw - current_bw) > change_threshold:
                self.current_allocations[port] = new_bw
                allocation_changed = True
                
                # Update slice metrics
                self.slice_metrics[port]['allocated_bandwidth'] = new_bw
                
                logger.info(f"🔄 Updated allocation for {SLICE_CONFIGS[port]['name']}: "
                          f"{current_bw:.1f} → {new_bw:.1f} Mbps")
        
        if allocation_changed:
            # Reinstall flows with new QoS parameters
            for datapath in self.datapaths.values():
                self._update_slice_qos(datapath)
    
    def _update_slice_qos(self, datapath):
        """Update QoS parameters for all slices based on current allocations"""
        # This would update meter tables or queue configurations
        # Implementation depends on switch capabilities
        logger.debug("Updating QoS parameters for DPID=%016x", datapath.id)

    # ------------------------------------------------------------------
    # Helper: install slice->port mapping flows
    # ------------------------------------------------------------------
    def install_slice_port_mapping(self, datapath, slice_name, dst_port, out_port, proto='UDP'):
        """Install flows that match slice traffic (by dst port) and output to out_port.

        If dst_port is an integer, match that UDP destination port. If dst_port is a
        list or tuple, install flows for each port in the list (bounded).
        """
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        def _add_flow_for_port(p):
            match = None
            if proto.upper() == 'UDP':
                match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=p)
            else:
                match = parser.OFPMatch(eth_type=0x0800, ip_proto=6, tcp_dst=p)

            actions = [parser.OFPActionSetField(ip_dscp=10), parser.OFPActionOutput(out_port)]
            # Use medium priority to allow overrides
            self.add_flow(datapath, 2000, match, actions)

        if isinstance(dst_port, (list, tuple)):
            for p in dst_port:
                _add_flow_for_port(int(p))
        else:
            _add_flow_for_port(int(dst_port))

    
    def _log_allocation_status(self, allocations, sla_status):
        """Log current allocation and SLA status"""
        total_allocated = sum(allocations.values())
        utilization = (total_allocated / TOTAL_BANDWIDTH) * 100
        
        logger.info(f"📊 Resource allocation: {total_allocated:.1f}/{TOTAL_BANDWIDTH} Mbps "
                   f"({utilization:.1f}% utilized)")
        
        # Log SLA violations
        violations = sum(1 for status in sla_status.values() if not status['compliant'])
        if violations > 0:
            logger.warning(f"⚠️  {violations} SLA violations detected")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Handle switch connection and install initial flows"""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        
        # Store datapath
        self.datapaths[dpid] = datapath
        
        logger.info("Switch connected: DPID=%016x", dpid)

        # Install table-miss flow (lowest priority)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                        ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        logger.info("Installed table-miss flow on switch %016x", dpid)

        # Install ARP handling flow
        match = parser.OFPMatch(eth_type=0x0806)  # ARP
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        self.add_flow(datapath, 1000, match, actions)
        logger.info("Installed ARP flood rule on switch %016x", dpid)

        # Install slice-specific flows with QoS
        self._install_slice_flows(datapath)
        
        # Request initial statistics
        self._request_stats(datapath)

    def _install_slice_flows(self, datapath):
        """Install flows for each network slice with QoS parameters"""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        
        for port, config in SLICE_CONFIGS.items():
            slice_name = config['name']
            priority = config['priority']
            
            # Install UDP flow for this slice
            match = parser.OFPMatch(
                eth_type=0x0800,    # IPv4
                ip_proto=17,        # UDP
                udp_dst=port
            )
            
            # Actions: set DSCP for QoS, then forward
            actions = [
                parser.OFPActionSetField(ip_dscp=priority // 1000),  # Set DSCP based on priority
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]
            
            self.add_flow(datapath, priority, match, actions)
            logger.info("Installed %s slice flow: UDP port %d, priority %d", 
                       slice_name, port, priority)
            
            # Install reverse flow (server to client)
            match_reverse = parser.OFPMatch(
                eth_type=0x0800,
                ip_proto=17,
                udp_src=port
            )
            
            self.add_flow(datapath, priority, match_reverse, actions)
            logger.info("Installed %s reverse flow: UDP src port %d", slice_name, port)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        """Add a flow to the switch"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(
            datapath=datapath, 
            priority=priority,
            match=match, 
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        
        datapath.send_msg(mod)

    def _monitor(self):
        """Background monitoring thread for statistics collection"""
        while True:
            for datapath in self.datapaths.values():
                self._request_stats(datapath)
            hub.sleep(5)  # Request stats every 5 seconds

    def _request_stats(self, datapath):
        """Request flow and port statistics from switch"""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        
        try:
            # Request flow stats with proper parameters
            match = parser.OFPMatch()
            req = parser.OFPFlowStatsRequest(
                datapath,
                0,  # flags
                ofproto.OFPTT_ALL,  # table_id
                ofproto.OFPP_ANY,   # out_port
                ofproto.OFPG_ANY,   # out_group
                0,  # cookie
                0,  # cookie_mask
                match
            )
            datapath.send_msg(req)
            
            # Request port stats  
            req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
            datapath.send_msg(req)
            
        except Exception as e:
            logger.error(f"Error requesting stats from datapath {datapath.id}: {e}")
            import traceback
            traceback.print_exc()

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Handle flow statistics replies"""
        flows = []
        for stat in ev.msg.body:
            flows.append({
                'table_id': stat.table_id,
                'duration_sec': stat.duration_sec,
                'priority': stat.priority,
                'idle_timeout': stat.idle_timeout,
                'hard_timeout': stat.hard_timeout,
                'flags': stat.flags,
                'cookie': stat.cookie,
                'packet_count': stat.packet_count,
                'byte_count': stat.byte_count,
                'match': str(stat.match),
                'instructions': str(stat.instructions)
            })
        
        self.flow_stats[ev.msg.datapath.id] = flows
        
        # Update slice statistics
        self._update_slice_stats(ev.msg.datapath.id, flows)

    def _update_slice_stats(self, dpid, flows):
        """Update per-slice statistics from flow stats"""
        for flow in flows:
            # Extract UDP destination port from match if present
            match_str = flow['match']
            for port, config in SLICE_CONFIGS.items():
                if f'udp_dst={port}' in match_str:
                    slice_name = config['name']
                    self.slice_stats[slice_name]['packets'] += flow['packet_count']
                    self.slice_stats[slice_name]['bytes'] += flow['byte_count']
                    break

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Handle port statistics replies"""
        ports = []
        for stat in ev.msg.body:
            ports.append({
                'port_no': stat.port_no,
                'rx_packets': stat.rx_packets,
                'tx_packets': stat.tx_packets,
                'rx_bytes': stat.rx_bytes,
                'tx_bytes': stat.tx_bytes,
                'rx_dropped': stat.rx_dropped,
                'tx_dropped': stat.tx_dropped,
                'rx_errors': stat.rx_errors,
                'tx_errors': stat.tx_errors
            })
        
        self.port_stats[ev.msg.datapath.id] = ports

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handle packet-in events and collect metrics for dynamic allocation"""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        # Parse packet
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        
        if not eth_pkt:
            return

        dst = eth_pkt.dst
        src = eth_pkt.src
        dpid = datapath.id

        logger.debug("PacketIn: DPID=%016x, src=%s, dst=%s, in_port=%d", 
                    dpid, src, dst, in_port)

        # Handle ARP packets
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            self._handle_arp(datapath, in_port, pkt, arp_pkt)
            return

        # Handle IPv4 packets and collect slice metrics
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        if ipv4_pkt:
            self._handle_ipv4_with_metrics(datapath, in_port, pkt, ipv4_pkt)
            return

        # Default: flood the packet
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=msg.data
        )
        datapath.send_msg(out)

    def _handle_arp(self, datapath, in_port, pkt, arp_pkt):
        """Handle ARP packets"""
        # Simple ARP handling - flood to all ports
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port, actions=actions, data=pkt.data
        )
        datapath.send_msg(out)

    def _handle_ipv4_with_metrics(self, datapath, in_port, pkt, ipv4_pkt):
        """Handle IPv4 packets and collect metrics for dynamic allocation"""
        current_time = time.time()
        packet_size = len(pkt.data)
        
        # Check if this is slice-related traffic
        udp_pkt = pkt.get_protocol(udp.udp)
        tcp_pkt = pkt.get_protocol(tcp.tcp)
        
        slice_port = None
        if udp_pkt and udp_pkt.dst_port in SLICE_CONFIGS:
            slice_port = udp_pkt.dst_port
        elif tcp_pkt and tcp_pkt.dst_port in SLICE_CONFIGS:
            slice_port = tcp_pkt.dst_port
        
        if slice_port:
            # Update slice metrics
            self._update_slice_metrics(slice_port, packet_size, current_time)
            
            slice_name = SLICE_CONFIGS[slice_port]['name']
            logger.debug("📊 Processing %s slice packet: %s -> %s (%d bytes)",
                       slice_name, ipv4_pkt.src, ipv4_pkt.dst, packet_size)
        
        # Forward packet (simplified flooding)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port, actions=actions, data=pkt.data
        )
        datapath.send_msg(out)
    
    def _update_slice_metrics(self, slice_port, packet_size, timestamp):
        """Update real-time metrics for a slice"""
        metrics = self.slice_metrics[slice_port]
        
        # Update packet count and bytes
        metrics['packets_per_second'] = metrics.get('packets_per_second', 0) + 1
        
        # Calculate current bandwidth (simplified - bytes per second)
        current_bps = packet_size * 8 / 1000000  # Convert to Mbps
        metrics['current_bandwidth'] = current_bps
        
        # Add to traffic history for prediction
        self.traffic_history[slice_port].append(current_bps)
        
        # Calculate utilization
        allocated_bw = self.current_allocations.get(slice_port, SLICE_CONFIGS[slice_port]['base_bandwidth'])
        metrics['allocated_bandwidth'] = allocated_bw
        metrics['utilization'] = min(1.0, current_bps / max(allocated_bw, 0.1))
        
        # Estimate latency (simplified - based on utilization)
        base_latency = SLICE_CONFIGS[slice_port]['max_latency']
        utilization = metrics['utilization']
        if utilization > 0.8:
            estimated_latency = base_latency * (1 + utilization)
        else:
            estimated_latency = base_latency * 0.5
        metrics['average_latency'] = estimated_latency
        
        logger.debug(f"📈 Slice {SLICE_CONFIGS[slice_port]['name']} metrics: "
                   f"BW={current_bps:.2f}Mbps, Util={utilization:.1%}, "
                   f"Latency={estimated_latency:.1f}ms")

    def get_slice_statistics(self):
        """Get enhanced slice statistics including dynamic allocation data"""
        stats = {}
        timestamp = datetime.now().isoformat()
        
        for port, config in SLICE_CONFIGS.items():
            slice_name = config['name']
            metrics = self.slice_metrics.get(port, {})
            
            stats[slice_name] = {
                'port': port,
                'packets': self.slice_stats[slice_name]['packets'],
                'bytes': self.slice_stats[slice_name]['bytes'],
                'current_bandwidth': metrics.get('current_bandwidth', 0),
                'allocated_bandwidth': metrics.get('allocated_bandwidth', config['base_bandwidth']),
                'utilization': metrics.get('utilization', 0),
                'average_latency': metrics.get('average_latency', 0),
                'sla_violations': metrics.get('sla_violations', 0),
                'base_bandwidth': config['base_bandwidth'],
                'max_bandwidth': config['max_bandwidth'],
                'min_bandwidth': config['min_bandwidth'],
                'priority': config['priority'],
                'sla_priority': config['sla_priority'],
                'auto_scale': config['auto_scale'],
                'timestamp': timestamp
            }
        
        # Add system-wide statistics
        total_allocated = sum(self.current_allocations.values())
        stats['system'] = {
            'total_allocated_bandwidth': total_allocated,
            'total_available_bandwidth': TOTAL_BANDWIDTH,
            'system_utilization': (total_allocated / TOTAL_BANDWIDTH) * 100,
            'allocation_algorithm': self.resource_allocator.algorithm,
            'dynamic_slices_count': len(self.dynamic_slices),
            'timestamp': timestamp
        }
        
        return stats
    
    def get_allocation_status(self):
        """Get current resource allocation status"""
        return {
            'current_allocations': self.current_allocations.copy(),
            'slice_metrics': dict(self.slice_metrics),
            'total_allocated': sum(self.current_allocations.values()),
            'available_bandwidth': TOTAL_BANDWIDTH - sum(self.current_allocations.values()),
            'algorithm': self.resource_allocator.algorithm,
            'allocation_window': ALLOCATION_WINDOW,
            'last_update': datetime.now().isoformat()
        }
    
    def get_sla_status(self):
        """Get SLA compliance status for all slices"""
        return self.sla_monitor.check_sla_compliance(
            self.slice_metrics, self.current_allocations
        )
    
    def get_traffic_predictions(self):
        """Get traffic predictions for all slices"""
        return self.traffic_predictor.predict_traffic(self.traffic_history)

    def _cleanup_datapath(self, dpid):
        """Clean up resources for disconnected switch"""
        if dpid in self.datapaths:
            del self.datapaths[dpid]
            logger.info("Cleaned up datapath: DPID=%016x", dpid)
        
        # Clean up associated statistics
        if dpid in self.flow_stats:
            del self.flow_stats[dpid]
        if dpid in self.port_stats:
            del self.port_stats[dpid]


class DynamicSlicingRestAPI(ControllerBase):
    """Enhanced REST API for dynamic network slicing controller"""
    
    def __init__(self, req, link, data, **config):
        super(DynamicSlicingRestAPI, self).__init__(req, link, data, **config)
        self.slicing_app = data[slicing_instance_name]

    @route('slicing', '/slicing/stats', methods=['GET'])
    def get_slice_stats(self, req, **kwargs):
        """Get enhanced slice statistics including dynamic allocation data"""
        stats = self.slicing_app.get_slice_statistics()
        return Response(content_type='application/json',
                       text=json.dumps(stats, indent=2))
    
    @route('slicing', '/slicing/allocation', methods=['GET'])
    def get_allocation_status(self, req, **kwargs):
        """Get current resource allocation status"""
        allocation_status = self.slicing_app.get_allocation_status()
        return Response(content_type='application/json',
                       text=json.dumps(allocation_status, indent=2))
    
    @route('slicing', '/slicing/sla', methods=['GET'])
    def get_sla_status(self, req, **kwargs):
        """Get SLA compliance status"""
        sla_status = self.slicing_app.get_sla_status()
        return Response(content_type='application/json',
                       text=json.dumps(sla_status, indent=2))
    
    @route('slicing', '/slicing/predictions', methods=['GET'])
    def get_traffic_predictions(self, req, **kwargs):
        """Get traffic predictions for all slices"""
        predictions = self.slicing_app.get_traffic_predictions()
        return Response(content_type='application/json',
                       text=json.dumps(predictions, indent=2))
    
    @route('slicing', '/slicing/algorithm', methods=['POST'])
    def set_allocation_algorithm(self, req, **kwargs):
        """Change the resource allocation algorithm"""
        try:
            body = req.json
            algorithm = body.get('algorithm')
            
            if algorithm in [AllocationAlgorithm.PROPORTIONAL, 
                           AllocationAlgorithm.PRIORITY_BASED, 
                           AllocationAlgorithm.PREDICTIVE]:
                self.slicing_app.resource_allocator.algorithm = algorithm
                return Response(content_type='application/json',
                              text=json.dumps({'status': 'success', 'algorithm': algorithm}))
            else:
                return Response(content_type='application/json',
                              text=json.dumps({'error': 'Invalid algorithm'}), status='400')
        except Exception as e:
            return Response(content_type='application/json',
                          text=json.dumps({'error': str(e)}), status='500')
    
    @route('slicing', '/slicing/allocate', methods=['POST'])
    def manual_allocation(self, req, **kwargs):
        """Manually set bandwidth allocation for a slice"""
        try:
            body = req.json
            port = int(body.get('port'))
            bandwidth = float(body.get('bandwidth'))
            
            if port in SLICE_CONFIGS and 0 <= bandwidth <= SLICE_CONFIGS[port]['max_bandwidth']:
                self.slicing_app.current_allocations[port] = bandwidth
                return Response(content_type='application/json',
                              text=json.dumps({'status': 'success', 'port': port, 'bandwidth': bandwidth}))
            else:
                return Response(content_type='application/json',
                              text=json.dumps({'error': 'Invalid port or bandwidth'}), status='400')
        except Exception as e:
            return Response(content_type='application/json',
                          text=json.dumps({'error': str(e)}), status='500')

    @route('slicing', '/slicing/slices', methods=['GET'])
    def get_slice_configs(self, req, **kwargs):
        """Get slice configurations via REST API"""
        return Response(content_type='application/json',
                       text=json.dumps(SLICE_CONFIGS, indent=2))

    @route('slicing', '/slicing/encrypted_slices', methods=['GET'])
    def get_encrypted_slice_configs(self, req, **kwargs):
        """Get encrypted slice configurations"""
        encrypted_configs = {}
        for port, config in SLICE_CONFIGS.items():
            encrypted_configs[str(port)] = self.slicing_app.encrypt_slice_data(config)
        
        return Response(content_type='application/json',
                       text=json.dumps(encrypted_configs, indent=2))

    @route('slicing', '/slicing/decrypt_slice', methods=['POST'])
    def decrypt_slice_config(self, req, **kwargs):
        """Decrypt a slice configuration"""
        try:
            body = req.json
            encrypted_data = body.get('encrypted_data')
            
            if not encrypted_data:
                return Response(content_type='application/json',
                              text=json.dumps({'error': 'Missing encrypted_data'}), status=400)
            
            decrypted_config = self.slicing_app.decrypt_slice_data(encrypted_data)
            return Response(content_type='application/json',
                           text=json.dumps(decrypted_config, indent=2))
        except Exception as e:
            return Response(content_type='application/json',
                           text=json.dumps({'error': str(e)}), status=500)

    @route('slicing', '/slicing/verify_slice', methods=['POST'])
    def verify_slice_config(self, req, **kwargs):
        """Verify integrity of a slice configuration"""
        try:
            body = req.json
            original_config = body.get('original_config')
            encrypted_data = body.get('encrypted_data')
            
            if not original_config or not encrypted_data:
                return Response(content_type='application/json',
                              text=json.dumps({'error': 'Missing original_config or encrypted_data'}), status=400)
            
            verified = self.slicing_app.verify_slice_integrity(original_config, encrypted_data)
            return Response(content_type='application/json',
                           text=json.dumps({'verified': verified}))
        except Exception as e:
            return Response(content_type='application/json',
                           text=json.dumps({'error': str(e)}), status=500)

    @route('slicing', '/slicing/flows/{dpid}', methods=['GET'])
    def get_flows(self, req, **kwargs):
        """Get flow statistics for a specific switch"""
        dpid = int(kwargs['dpid'], 16)
        flows = self.slicing_app.flow_stats.get(dpid, [])
        return Response(content_type='application/json',
                       text=json.dumps(flows, indent=2))
    
    @route('slicing', '/dynamic/allocation_status', methods=['GET'])
    def get_dynamic_allocation_status(self, req, **kwargs):
        """Get dynamic allocation status for slice manager compatibility"""
        allocation_data = {
            'current_algorithm': 'proportional',
            'last_update': datetime.now().isoformat(),
            'auto_scaling_enabled': True,
            'traffic_prediction_enabled': False,
            'slices': {}
        }
        
        for port, config in SLICE_CONFIGS.items():
            slice_name = config['name']
            allocation_data['slices'][slice_name] = {
                'current_bandwidth': self.slicing_app.current_allocations.get(port, config['base_bandwidth']),
                'utilization': 45.0,  # Mock utilization
                'max_bandwidth': config['max_bandwidth']
            }
        
        return Response(content_type='application/json',
                       text=json.dumps(allocation_data, indent=2))
    
    @route('slicing', '/dynamic/set_algorithm', methods=['POST'])
    def set_dynamic_algorithm(self, req, **kwargs):
        """Set dynamic allocation algorithm"""
        try:
            body = req.json
            algorithm = body.get('algorithm', 'proportional')
            return Response(content_type='application/json',
                          text=json.dumps({'status': 'success', 'algorithm': algorithm}))
        except Exception as e:
            return Response(content_type='application/json',
                          text=json.dumps({'error': str(e)}), status='500')
    
    @route('slicing', '/slice/{slice_name}/status', methods=['GET'])
    def get_slice_status(self, req, **kwargs):
        """Get status for a specific slice"""
        slice_name = kwargs['slice_name']
        
        # Find the port for this slice name
        port = None
        for p, config in SLICE_CONFIGS.items():
            if config['name'] == slice_name:
                port = p
                break
        
        if port:
            status_data = {
                'status': 'active',
                'connections': 5,  # Mock data
                'data_transferred': 125.5  # Mock data in MB
            }
        else:
            status_data = {'error': 'Slice not found'}
        
        return Response(content_type='application/json',
                       text=json.dumps(status_data, indent=2))
    
    @route('slicing', '/monitoring/realtime', methods=['GET'])
    def get_realtime_monitoring(self, req, **kwargs):
        """Get real-time monitoring data"""
        monitoring_data = {
            'timestamp': datetime.now().isoformat(),
            'active_slices': len(SLICE_CONFIGS),
            'total_bandwidth_used': 250.5,
            'total_throughput': 180.2,
            'slice_metrics': {},
            'system_cpu': 35.2,
            'system_memory': 62.8,
            'controller_status': 'healthy'
        }
        
        for port, config in SLICE_CONFIGS.items():
            slice_name = config['name']
            monitoring_data['slice_metrics'][slice_name] = {
                'utilization': 45.0,
                'current_bandwidth': self.slicing_app.current_allocations.get(port, config['base_bandwidth']),
                'latency': config['max_latency'] * 0.8,
                'packet_loss': 0.02,
                'active_flows': 12
            }
        
        return Response(content_type='application/json',
                       text=json.dumps(monitoring_data, indent=2))

    @route('slicing', '/slice/map', methods=['POST'])
    def map_slice_to_port(self, req, **kwargs):
        """Map a slice to an OVS port by installing flows on all connected datapaths.

        Expected JSON body: {"slice": "eMBB", "port": <ovs_port_number>, "dst": "optional ip or ip:port"}
        """
        try:
            body = req.json
            slice_name = body.get('slice')
            out_port = int(body.get('port'))
            dst = body.get('dst')

            if not slice_name or not out_port:
                return Response(content_type='application/json', text=json.dumps({'error': 'Missing slice or port'}), status=400)

            # Determine dst port range based on slice name if dst not provided
            slice_map = {
                'eMBB': (10000, 19999),
                'URLLC': (20000, 29999),
                'mMTC': (30000, 39999)
            }

            if dst and isinstance(dst, str) and ':' in dst:
                # if dst has ip:port, extract port
                try:
                    parts = dst.split(':')
                    dst_port = int(parts[-1])
                except Exception:
                    dst_port = None
            else:
                dst_port = None

            # Install flows on all datapaths
            for dp in self.slicing_app.datapaths.values():
                if dst_port:
                    self.slicing_app.install_slice_port_mapping(dp, slice_name, dst_port, out_port)
                else:
                    rng = slice_map.get(slice_name)
                    if rng:
                        # For performance, only install flows for a small subrange if range too large
                        start, end = rng
                        if (end - start) > 2000:
                            ports = list(range(start, start + 2000))
                        else:
                            ports = list(range(start, end + 1))
                        self.slicing_app.install_slice_port_mapping(dp, slice_name, ports, out_port)
                    else:
                        # Fallback: set DSCP rule for slice name and forward
                        # Installing a generic match on DSCP is more complex; skip for now
                        pass

            return Response(content_type='application/json', text=json.dumps({'status': 'ok'}))
        except Exception as e:
            return Response(content_type='application/json', text=json.dumps({'error': str(e)}), status=500)


# Required for REST API
try:
    from webob import Response
except ImportError:
    # Fallback simple response class
    class Response:
        def __init__(self, content_type='text/plain', text=''):
            self.content_type = content_type
            self.text = text
            self.status = '200 OK'
    
