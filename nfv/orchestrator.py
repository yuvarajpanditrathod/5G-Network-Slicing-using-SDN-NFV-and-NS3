#!/usr/bin/env python3
"""
Orchestrator: small CLI to start/stop/status the firewall VNF subprocess.

Usage:
  python3 orchestrator.py start --port 9000
  python3 orchestrator.py stop
  python3 orchestrator.py status
"""
import argparse
import os
import signal
import subprocess
import time
from pathlib import Path
import logging
import sys

LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("orchestrator")

PID_FILE = Path("nfv_firewall.pid")
LOG_FILE = Path("nfv_firewall.log")
VNF_SCRIPT = Path(__file__).parent / "firewall_vnf.py"


def start(port=9000):
    if PID_FILE.exists():
        logger.error("PID file exists. Is the VNF already running?")
        return
    cmd = [sys.executable, str(VNF_SCRIPT), "--port", str(port)]
    logfile = open(str(LOG_FILE), "ab")
    proc = subprocess.Popen(cmd, stdout=logfile, stderr=logfile)
    PID_FILE.write_text(str(proc.pid))
    logger.info("Started firewall VNF (pid=%d). Logs: %s", proc.pid, LOG_FILE)


def stop():
    if not PID_FILE.exists():
        logger.error("No PID file found; nothing to stop.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to pid %d", pid)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            logger.warning("Process did not exit; sending SIGKILL")
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        logger.warning("Process not found (may have exited).")
    finally:
        try:
            PID_FILE.unlink()
        except Exception:
            pass


def status():
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        logger.info("VNF PID file found: %s", pid)
    else:
        logger.info("VNF is not running.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    s = sub.add_parser("start")
    s.add_argument("--port", type=int, default=9000)
    sub.add_parser("stop")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.cmd == "start":
        start(port=args.port)
    elif args.cmd == "stop":
        stop()
    elif args.cmd == "status":
        status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
