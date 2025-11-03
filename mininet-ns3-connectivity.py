#!/usr/bin/env python3
"""
Professional Mininet Network Slicing Monitor
Advanced traffic visualization and slice-to-slice communication tracking
Features:
- Real-time packet capture and analysis
- Professional formatting with colors and tables
- Detailed traffic statistics and flow visualization
- Cross-slice communication monitoring
"""

import subprocess
import re
import sys
import logging
from datetime import datetime
from collections import defaultdict
import threading
import time
import os

# Color codes for professional output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ORANGE = '\033[38;5;208m'
    PURPLE = '\033[38;5;135m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'
    
    @staticmethod
    def disable():
        """Disable colors for log files"""
        Colors.HEADER = ''
        Colors.BLUE = ''
        Colors.CYAN = ''
        Colors.GREEN = ''
        Colors.YELLOW = ''
        Colors.RED = ''
        Colors.ORANGE = ''
        Colors.PURPLE = ''
        Colors.BOLD = ''
        Colors.UNDERLINE = ''
        Colors.END = ''

# Custom formatter for colored console output
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        # Apply colors based on log level and content
        if 'ECHO_REQUEST' in record.getMessage():
            record.msg = f"{Colors.GREEN}{record.msg}{Colors.END}"
        elif 'ECHO_REPLY' in record.getMessage():
            record.msg = f"{Colors.CYAN}{record.msg}{Colors.END}"
        elif 'STATISTICS' in record.getMessage():
            record.msg = f"{Colors.YELLOW}{Colors.BOLD}{record.msg}{Colors.END}"
        elif record.levelname == 'ERROR':
            record.msg = f"{Colors.RED}{record.msg}{Colors.END}"
        elif 'Source:' in record.getMessage() or 'Destination:' in record.getMessage():
            record.msg = f"{Colors.BLUE}{record.msg}{Colors.END}"
        
        return super().format(record)

# Configure professional logging
def setup_logging():
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter('[%(asctime)s] %(message)s'))
    
    # File handler without colors
    file_handler = logging.FileHandler('/tmp/mininet_slice_traffic.log')
    file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
    
    logger = logging.getLogger('MinenetSliceMonitor')
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()


class ProfessionalMinenetMonitor:
    """Professional Network Slicing Monitor with Enhanced Visualization"""
    
    def _init_(self, interface='any'):
        self.interface = interface
        self.traffic_stats = defaultdict(int)
        self.packet_count = 0
        self.session_start = datetime.now()
        self.tcpdump_process = None
        self.last_stats_time = time.time()
        
        # Professional slice configuration with enhanced metadata
        self.slice_config = {
            'eMBB': {
                'host': 'embb_h1',
                'ip': '10.0.0.10',
                'color': Colors.GREEN,
                'symbol': '📱',
                'description': 'Enhanced Mobile Broadband',
                'priority': 'High Throughput'
            },
            'URLLC': {
                'host': 'urllc_h1',
                'ip': '10.0.0.11',
                'color': Colors.RED,
                'symbol': '⚡',
                'description': 'Ultra-Reliable Low Latency',
                'priority': 'Low Latency'
            },
            'mMTC': {
                'host': 'mmtc_h1',
                'ip': '10.0.0.12',
                'color': Colors.BLUE,
                'symbol': '🌐',
                'description': 'Massive Machine Type Communications',
                'priority': 'High Connectivity'
            }
        }
        
        self._display_professional_header()
        
    def _display_professional_header(self):
        """Display professional header with system information"""
        terminal_width = 100
        
        # Clear screen for fresh start
        os.system('clear' if os.name == 'posix' else 'cls')
        
        # Main header
        logger.info(f"{Colors.BOLD}{Colors.HEADER}{'═' * terminal_width}{Colors.END}")
        logger.info(f"{Colors.BOLD}{Colors.HEADER}║{' ' * 35}MININET NETWORK SLICING MONITOR{' ' * 32}║{Colors.END}")
        logger.info(f"{Colors.BOLD}{Colors.HEADER}║{' ' * 45}Dashboard{' ' * 44}║{Colors.END}")
        logger.info(f"{Colors.BOLD}{Colors.HEADER}{'═' * terminal_width}{Colors.END}")
        
        # Session information
        logger.info(f"{Colors.CYAN}📊 Session Started: {Colors.BOLD}{self.session_start.strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
        logger.info(f"{Colors.CYAN}🔍 Monitoring Interface: {Colors.BOLD}{self.interface}{Colors.END}")
        logger.info(f"{Colors.CYAN}📝 Log File: {Colors.BOLD}/tmp/mininet_slice_traffic.log{Colors.END}")
        logger.info("")
        
        # Slice configuration table
        self._display_slice_table()
        
        # Monitoring status
        logger.info(f"{Colors.YELLOW}{'─' * terminal_width}{Colors.END}")
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}🎯 TRAFFIC MONITORING STATUS{Colors.END}")
        logger.info(f"{Colors.YELLOW}{'─' * terminal_width}{Colors.END}")
        logger.info(f"{Colors.GREEN}✓ ICMP Packet Capture: {Colors.BOLD}ACTIVE{Colors.END}")
        logger.info(f"{Colors.GREEN}✓ Slice Classification: {Colors.BOLD}ENABLED{Colors.END}")
        logger.info(f"{Colors.GREEN}✓ Real-time Analysis: {Colors.BOLD}RUNNING{Colors.END}")
        logger.info("")
    
    def _display_slice_table(self):
        """Display professional slice configuration table"""
        logger.info(f"{Colors.BOLD}{Colors.PURPLE}📋 NETWORK SLICE CONFIGURATION{Colors.END}")
        logger.info(f"{Colors.PURPLE}{'─' * 100}{Colors.END}")
        
        # Table header
        header = f"{'SLICE':<8} {'HOST':<12} {'IP ADDRESS':<15} {'DESCRIPTION':<35} {'PRIORITY':<15}"
        logger.info(f"{Colors.BOLD}{Colors.PURPLE}{header}{Colors.END}")
        logger.info(f"{Colors.PURPLE}{'─' * 100}{Colors.END}")
        
        # Table rows
        for slice_name, config in self.slice_config.items():
            symbol = config['symbol']
            host = config['host']
            ip = config['ip']
            desc = config['description']
            priority = config['priority']
            color = config['color']
            
            row = f"{symbol} {slice_name:<6} {host:<12} {ip:<15} {desc:<35} {priority:<15}"
            logger.info(f"{color}{row}{Colors.END}")
        
        logger.info(f"{Colors.PURPLE}{'─' * 100}{Colors.END}")
        logger.info("")
        
    def get_slice_from_ip(self, ip_address):
        """Map IP address to slice name"""
        for slice_name, config in self.slice_config.items():
            if ip_address == config['ip']:
                return slice_name, config['host']
        return None, ip_address
    
    def get_host_from_ip(self, ip_address):
        """Get host name from IP address"""
        for slice_name, config in self.slice_config.items():
            if ip_address == config['ip']:
                return config['host']
        return ip_address
    
    def parse_icmp_packet(self, line):
        """Parse tcpdump output line to extract ICMP packet info
        
        Expected tcpdump format:
        IP 10.0.0.10 > 10.0.0.11: ICMP echo request, id 12345, seq 1, length 64
        IP 10.0.0.11 > 10.0.0.10: ICMP echo reply, id 12345, seq 1, length 64
        """
        try:
            if 'ICMP' not in line:
                return None
            
            # Extract source and destination IPs
            ip_pattern = r'IP (\d+\.\d+\.\d+\.\d+) > (\d+\.\d+\.\d+\.\d+):'
            ip_match = re.search(ip_pattern, line)
            if not ip_match:
                return None
            
            src_ip = ip_match.group(1)
            dst_ip = ip_match.group(2)
            
            # Extract ICMP type (echo request or echo reply)
            icmp_type = None
            if 'echo request' in line:
                icmp_type = 'ECHO_REQUEST'
            elif 'echo reply' in line:
                icmp_type = 'ECHO_REPLY'
            else:
                return None
            
            # Extract ICMP ID and sequence
            id_pattern = r'id (\d+)'
            seq_pattern = r'seq (\d+)'
            
            id_match = re.search(id_pattern, line)
            seq_match = re.search(seq_pattern, line)
            
            icmp_id = int(id_match.group(1)) if id_match else 0
            icmp_seq = int(seq_match.group(1)) if seq_match else 0
            
            # Get source and destination slices
            src_slice, src_host = self.get_slice_from_ip(src_ip)
            dst_slice, dst_host = self.get_slice_from_ip(dst_ip)
            
            if not src_slice or not dst_slice:
                return None
            
            return {
                'src_ip': src_ip,
                'dst_ip': dst_ip,
                'src_slice': src_slice,
                'dst_slice': dst_slice,
                'src_host': src_host,
                'dst_host': dst_host,
                'type': icmp_type,
                'id': icmp_id,
                'seq': icmp_seq,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return None
    
    def log_professional_packet(self, packet_info):
        """Log captured traffic with professional formatting and visualization"""
        if not packet_info:
            return
        
        self.packet_count += 1
        src_slice = packet_info['src_slice']
        dst_slice = packet_info['dst_slice']
        pkt_type = packet_info['type']
        
        # Get slice colors and symbols
        src_config = self.slice_config[src_slice]
        dst_config = self.slice_config[dst_slice]
        
        # Professional packet header
        if pkt_type == 'ECHO_REQUEST':
            direction_symbol = "📤"
            type_color = Colors.GREEN
            traffic_key = f"{src_slice} → {dst_slice}"
            flow_description = f"{src_config['symbol']} {src_slice} → {dst_config['symbol']} {dst_slice}"
        else:
            direction_symbol = "📥"
            type_color = Colors.CYAN
            traffic_key = f"{dst_slice} ← {src_slice}"
            flow_description = f"{dst_config['symbol']} {dst_slice} ← {src_config['symbol']} {src_slice}"
        
        self.traffic_stats[traffic_key] += 1
        
        # Professional packet display
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        logger.info(f"{Colors.BOLD}{'─' * 100}{Colors.END}")
        logger.info(f"{type_color}{Colors.BOLD}{direction_symbol} PACKET #{self.packet_count:04d} | {pkt_type} | {timestamp}{Colors.END}")
        logger.info(f"{Colors.BOLD}🔄 FLOW: {flow_description}{Colors.END}")
        
        # Source information
        logger.info(f"{src_config['color']}📍 SOURCE      : {packet_info['src_ip']:<15} ({packet_info['src_host']:<10}) [{src_slice}]{Colors.END}")
        
        # Destination information  
        logger.info(f"{dst_config['color']}🎯 DESTINATION : {packet_info['dst_ip']:<15} ({packet_info['dst_host']:<10}) [{dst_slice}]{Colors.END}")
        
        # Packet details
        logger.info(f"{Colors.YELLOW}📊 PACKET INFO : ID={packet_info['id']:<6} Seq={packet_info['seq']:<4} Size=64 bytes{Colors.END}")
        
        # Flow statistics
        total_flow_packets = self.traffic_stats[traffic_key]
        logger.info(f"{Colors.PURPLE}📈 FLOW STATS  : {traffic_key} - {total_flow_packets} packets{Colors.END}")
        
        # Real-time throughput calculation
        current_time = time.time()
        time_elapsed = current_time - self.last_stats_time
        if time_elapsed >= 1.0:  # Update every second
            pps = self.packet_count / (current_time - time.mktime(self.session_start.timetuple()))
            logger.info(f"{Colors.ORANGE}⚡ THROUGHPUT  : {pps:.2f} packets/second{Colors.END}")
            self.last_stats_time = current_time
    
    def start_monitoring(self):
        """Start professional monitoring with enhanced visualization"""
        logger.info(f"{Colors.GREEN}{Colors.BOLD}🚀 STARTING PACKET CAPTURE...{Colors.END}")
        logger.info(f"{Colors.GREEN}{'═' * 100}{Colors.END}")
        
        try:
            # Professional tcpdump command
            cmd = f"sudo tcpdump -i {self.interface} -n 'icmp' 2>/dev/null"
            
            self.tcpdump_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                universal_newlines=True,
                bufsize=1
            )
            
            # Start professional statistics thread
            stats_thread = threading.Thread(target=self._periodic_stats, daemon=True)
            stats_thread.start()
            
            logger.info(f"{Colors.GREEN}✅ MONITORING ACTIVE - Listening for ICMP traffic...{Colors.END}")
            logger.info("")
            
            # Process packets with professional display
            for line in self.tcpdump_process.stdout:
                if not line.strip():
                    continue
                
                packet_info = self.parse_icmp_packet(line)
                if packet_info:
                    self.log_professional_packet(packet_info)
                
        except KeyboardInterrupt:
            self._display_session_summary()
        except Exception as e:
            logger.error(f"🚨 MONITORING ERROR: {e}")
        finally:
            if self.tcpdump_process:
                self.tcpdump_process.terminate()
    
    def _periodic_stats(self):
        """Display professional statistics every 30 seconds"""
        while True:
            try:
                time.sleep(30)
                if self.traffic_stats:
                    self.print_statistics()
            except:
                break
    
    def print_statistics(self):
        """Display professional traffic statistics with enhanced formatting"""
        logger.info("")
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}{'═' * 100}{Colors.END}")
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}║{' ' * 30}SLICE-TO-SLICE TRAFFIC STATISTICS{' ' * 30}║{Colors.END}")
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}{'═' * 100}{Colors.END}")
        
        # Calculate session duration
        session_duration = datetime.now() - self.session_start
        total_packets = sum(self.traffic_stats.values())
        avg_pps = total_packets / session_duration.total_seconds() if session_duration.total_seconds() > 0 else 0
        
        # Session summary
        logger.info(f"{Colors.CYAN}📊 SESSION SUMMARY:{Colors.END}")
        logger.info(f"{Colors.CYAN}   Duration: {str(session_duration).split('.')[0]:<15} Total Packets: {total_packets:<10} Avg PPS: {avg_pps:.2f}{Colors.END}")
        logger.info("")
        
        # Traffic flows table
        logger.info(f"{Colors.PURPLE}🔄 TRAFFIC FLOWS:{Colors.END}")
        logger.info(f"{Colors.PURPLE}{'─' * 80}{Colors.END}")
        header = f"{'FLOW DIRECTION':<30} {'PACKETS':<15} {'PERCENTAGE':<15} {'RATE (PPS)':<15}"
        logger.info(f"{Colors.BOLD}{Colors.PURPLE}{header}{Colors.END}")
        logger.info(f"{Colors.PURPLE}{'─' * 80}{Colors.END}")
        
        for flow, count in sorted(self.traffic_stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total_packets * 100) if total_packets > 0 else 0
            rate = count / session_duration.total_seconds() if session_duration.total_seconds() > 0 else 0
            
            # Add visual indicators
            if '→' in flow:
                indicator = "📤"
            else:
                indicator = "📥"
                
            row = f"{indicator} {flow:<28} {count:<15} {percentage:>6.1f}%{' ':<8} {rate:>6.2f}{' ':<8}"
            logger.info(f"{Colors.GREEN}{row}{Colors.END}")
        
        logger.info(f"{Colors.PURPLE}{'─' * 80}{Colors.END}")
        logger.info("")
    
    def _display_session_summary(self):
        """Display comprehensive session summary when monitoring stops"""
        logger.info("")
        logger.info(f"{Colors.RED}{Colors.BOLD}🛑 MONITORING STOPPED BY USER{Colors.END}")
        
        # Final statistics
        self.print_statistics()
        
        # Session details
        session_duration = datetime.now() - self.session_start
        total_packets = sum(self.traffic_stats.values())
        
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}📋 FINAL SESSION REPORT{Colors.END}")
        logger.info(f"{Colors.YELLOW}{'═' * 60}{Colors.END}")
        logger.info(f"{Colors.CYAN}🕐 Session Duration    : {str(session_duration).split('.')[0]}{Colors.END}")
        logger.info(f"{Colors.CYAN}📦 Total Packets      : {total_packets}{Colors.END}")
        logger.info(f"{Colors.CYAN}🌊 Unique Flows       : {len(self.traffic_stats)}{Colors.END}")
        logger.info(f"{Colors.CYAN}💾 Log File Location  : /tmp/mininet_slice_traffic.log{Colors.END}")
        logger.info(f"{Colors.YELLOW}{'═' * 60}{Colors.END}")
        logger.info(f"{Colors.GREEN}✅ SESSION COMPLETED SUCCESSFULLY{Colors.END}")
        logger.info("")
        
    def get_slice_from_ip(self, ip_address):
        """Map IP address to slice name with enhanced error handling"""
        for slice_name, config in self.slice_config.items():
            if ip_address == config['ip']:
                return slice_name, config['host']
        return None, ip_address


def main():
    """Main entry point for professional monitor"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Professional Mininet Network Slicing Monitor - Enhanced Edition',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 %(prog)s                    # Monitor all interfaces
  python3 %(prog)s -i eth0            # Monitor specific interface
  sudo python3 %(prog)s               # Run with sudo for full access
        """
    )
    parser.add_argument(
        '-i', '--interface',
        default='any',
        help='Network interface to monitor (default: any)'
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )
    
    args = parser.parse_args()
    
    # Disable colors if requested
    if args.no_color:
        Colors.disable()
    
    # Create and start professional monitor
    monitor = ProfessionalMinenetMonitor(interface=args.interface)
    monitor.start_monitoring()


if _name_ == '_main_':
    main()