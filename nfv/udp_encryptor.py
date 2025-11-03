#!/usr/bin/env python3
"""High-performance UDP sender that encrypts payloads with AES-256-GCM and sends to a receiver.

Usage: python3 udp_encryptor.py --dst 10.0.0.100 --port 5002 --rate 100M --duration 10 --parallel 4

This script uses the project's load_or_create_key and SliceEncryption.encrypt_batch to prepare encrypted
packets in parallel and then sends them as fast as possible. It's intended for testing encrypted UDP throughput
inside Mininet hosts.
"""
import argparse
import socket
import time
import os
from nfv.firewall_vnf import load_or_create_key, SliceEncryption

parser = argparse.ArgumentParser()
parser.add_argument('--dst', required=True)
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--duration', type=int, default=10)
parser.add_argument('--packet-size', type=int, default=1400)
parser.add_argument('--parallel', type=int, default=4)
parser.add_argument('--batch', type=int, default=128)
parser.add_argument('--sndbuf', type=int, default=8*1024*1024)
args = parser.parse_args()

key = load_or_create_key(bits=256)
encryptor = SliceEncryption(key)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, args.sndbuf)
except Exception:
    pass

end = time.time() + args.duration
sent = 0
batch_plain = [b'A' * (args.packet_size) for _ in range(args.batch)]

while time.time() < end:
    # encrypt a batch in parallel
    encs = encryptor.encrypt_batch(batch_plain, max_workers=args.parallel)
    for e in encs:
        try:
            sock.sendto(e, (args.dst, args.port))
            sent += 1
        except Exception:
            pass

# Report simple stat
print(f"Sent {sent} encrypted packets in {args.duration}s")


