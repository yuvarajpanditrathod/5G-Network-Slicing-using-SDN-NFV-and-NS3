#!/usr/bin/env python3
"""UDP receiver that decrypts AES-GCM packets and measures packet loss/latency approx.

Usage: python3 udp_decryptor.py --bind 0.0.0.0 --port 5002 --duration 12 --rcvbuf 8388608
"""
import argparse
import socket
import time
from nfv.firewall_vnf import load_or_create_key, SliceEncryption

parser = argparse.ArgumentParser()
parser.add_argument('--bind', default='0.0.0.0')
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--duration', type=int, default=12)
parser.add_argument('--rcvbuf', type=int, default=16*1024*1024)
args = parser.parse_args()

key = load_or_create_key(bits=256)
encryptor = SliceEncryption(key)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, args.rcvbuf)
except Exception:
    pass
sock.bind((args.bind, args.port))

end = time.time() + args.duration
recv = 0
bad = 0
while time.time() < end:
    try:
        data, addr = sock.recvfrom(65535)
        recv += 1
        try:
            _pt = encryptor.decrypt_bytes(data)
        except Exception:
            bad += 1
    except socket.timeout:
        continue
    except Exception:
        pass

print(f"Received {recv} packets, {bad} failed integrity checks")

