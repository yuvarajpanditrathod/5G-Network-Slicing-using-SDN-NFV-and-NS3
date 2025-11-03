#!/usr/bin/env python3
"""
Simple radio resource models: GNB, DU, CU and allocation helpers
Used by slice_manager and topology for basic radio logic and allocation simulation.
"""
import os
from dataclasses import dataclass
from typing import Dict, Any
import random

@dataclass
class GNB:
    id: str
    total_prbs: int = 100
    used_prbs: int = 0

    def allocate_prbs(self, amount: int) -> bool:
        if self.used_prbs + amount > self.total_prbs:
            return False
        self.used_prbs += amount
        return True

    def release_prbs(self, amount: int):
        self.used_prbs = max(0, self.used_prbs - amount)


@dataclass
class DU:
    id: str
    connected_gnb: str
    processed_sf: int = 0

    def process(self, load: float):
        self.processed_sf += int(load * 10)


@dataclass
class CU:
    id: str
    connected_du: str

    def schedule(self):
        # Simplified scheduling
        return random.randint(1, 10)


def classify_input_file(filename: str) -> str:
    """Classify input file into slice type based on filename heuristics.
    - video -> eMBB
    - iot  -> mMTC
    - lowlatency -> URLLC
    """
    lower = filename.lower()
    # Video heuristics
    if '4k' in lower or 'video' in lower or lower.endswith(('.mp4', '.mkv')):
        return 'eMBB'

    # URLLC-specific keywords (check before generic .csv rule)
    if any(k in lower for k in ('urllc', 'url', 'lowlatency', 'low-latency', 'low_latency', 'latency', 'low')):
        return 'URLLC'

    # CSV files: attempt lightweight content sniffing to differentiate URLLC vs mMTC
    if lower.endswith('.csv'):
        try:
            path = filename
            # If filename is not an absolute path, try to locate in cwd
            if not os.path.exists(path):
                path = os.path.join(os.getcwd(), filename)
            if os.path.exists(path):
                with open(path, 'r', errors='ignore') as fh:
                    sample = ''.join([next(fh) for _ in range(8)])
                s = sample.lower()
                # URLLC traces often include latency, timestamp/arrival_time/seq or inter-arrival columns
                if any(k in s for k in ('latency', 'arrival_time', 'inter_arrival', 'inter-arrival', 'timestamp', 'seq', 'sequence')):
                    return 'URLLC'
                # mMTC traces often contain sensor/id/reading fields
                if any(k in s for k in ('sensor', 'device_id', 'device', 'temperature', 'humidity', 'payload')):
                    return 'mMTC'
        except Exception:
            # fall back to name heuristics below
            pass

    # mMTC / IoT heuristics: csv files that are sensor/iot telemetry
    if 'iot' in lower or 'sensor' in lower or lower.endswith('.csv'):
        return 'mMTC'
    # fallback random
    return random.choice(['eMBB', 'URLLC', 'mMTC'])


def generate_traffic_pattern(slice_type: str, duration: int = 10):
    """Return a simple traffic pattern dict for the slice type"""
    if slice_type == 'eMBB':
        return {'pattern': 'bursty', 'pps': 500, 'pkt_size': 1400, 'duration': duration}
    if slice_type == 'URLLC':
        return {'pattern': 'constant', 'pps': 2000, 'pkt_size': 64, 'duration': duration}
    return {'pattern': 'periodic', 'pps': 50, 'pkt_size': 200, 'duration': duration}


if __name__ == '__main__':
    print('Radio module loaded - provides GNB/DU/CU and classification helpers')

