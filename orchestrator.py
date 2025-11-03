#!/usr/bin/env python3
"""
Orchestrator to create slices from input-data files.

Usage:
  python3 orchestrator.py --input-file input-data/urllc_traffic.csv
  python3 orchestrator.py --input-dir input-data/

This script classifies files using `radio.classify_input_file` and writes
`slice_registry.json` containing the slices to create. Only slices derived
from the provided inputs are created.
"""
import os
import sys
import json
import argparse
from pathlib import Path

sys.path.append(os.path.dirname(__file__))
from radio import classify_input_file


DEFAULT_PORTS = {
    'URLLC': 5001,
    'eMBB': 5002,
    'mMTC': 5003
}


DEFAULT_SLICE_TEMPLATES = {
    'eMBB': {
        'name': 'eMBB',
        'port': DEFAULT_PORTS['eMBB'],
        'base_bandwidth': 100,
        'max_bandwidth': 500,
        'min_bandwidth': 50,
        'pkt_size': 1400,
        'target_latency': 10,
        'reliability': 99.9
    },
    'URLLC': {
        'name': 'URLLC',
        'port': DEFAULT_PORTS['URLLC'],
        'base_bandwidth': 50,
        'max_bandwidth': 200,
        'min_bandwidth': 20,
        'pkt_size': 64,
        'target_latency': 1,
        'reliability': 99.999
    },
    'mMTC': {
        'name': 'mMTC',
        'port': DEFAULT_PORTS['mMTC'],
        'base_bandwidth': 20,
        'max_bandwidth': 100,
        'min_bandwidth': 5,
        'pkt_size': 200,
        'target_latency': 100,
        'reliability': 99.0
    }
}


def build_registry_from_files(files):
    """Return a mapping of slice_name -> config for files list."""
    slices_needed = {}
    for f in files:
        name = os.path.basename(f)
        s_type = classify_input_file(name)
        if s_type not in slices_needed:
            # copy template
            tpl = dict(DEFAULT_SLICE_TEMPLATES.get(s_type, {}))
            # give a user-friendly slice_id
            tpl['slice_id'] = f"slice_{s_type.lower()}_{int(os.path.getmtime(f))}"
            tpl['created_from'] = [name]
            slices_needed[s_type] = tpl
        else:
            slices_needed[s_type].setdefault('created_from', []).append(name)
    return slices_needed


def write_registry(registry, path='slice_registry.json'):
    # Merge with existing registry if present
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                existing = json.load(f) or {}
        except Exception:
            existing = {}

    # Merge (new registry entries override older ones)
    merged = dict(existing)
    for k, v in registry.items():
        merged[k] = v

    with open(path, 'w') as f:
        json.dump(merged, f, indent=2)
    print(f"Wrote slice registry to {path} ({len(merged)} slices)")
    return merged


def activate_slices_in_status(registry, status_path='slice_status.json'):
    """Mark slices in registry as active in slice_status.json for cross-process visibility."""
    status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path, 'r') as f:
                status = json.load(f)
        except Exception:
            status = {}

    # Preserve existing entries and only set active=True for the provided registry
    for sname in registry.keys():
        status.setdefault(sname, {})
        status[sname]['active'] = True
        status[sname]['updated_at'] = datetime_now_iso()

    try:
        tmp = status_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(status, f, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, status_path)
        print(f"Activated {len(registry)} slice(s) in {status_path}")
    except Exception as e:
        print(f"Failed to activate slices in status file: {e}")


def write_universal_runtime(registry, path='universal_runtime.json'):
    """Write a runtime universal slice config file that other processes (slice_manager)
    can pick up to activate runtime behaviour.
    """
    try:
        from datetime import datetime
        cfg = {
            'generated_at': datetime.now().isoformat(),
            'slices': {},
            'source': 'runtime',
            'active': True
        }
        for name, v in registry.items():
            entry = dict(v)
            # map some fields expected by slice_manager runtime config
            entry.setdefault('current_bandwidth', entry.get('base_bandwidth'))
            entry.setdefault('max_bandwidth', entry.get('max_bandwidth'))
            entry.setdefault('target_latency', entry.get('target_latency') or entry.get('target_latency'))
            entry.setdefault('port', entry.get('port', 5000))
            entry['activated_at'] = datetime.now().isoformat()
            cfg['slices'][name] = entry

        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(cfg, f, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        print(f"Wrote runtime universal config to {path}")
    except Exception as e:
        print(f"Failed to write universal runtime config: {e}")


def datetime_now_iso():
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        import time
        return str(int(time.time()))


def parse_args():
    p = argparse.ArgumentParser(description='Orchestrator: create slices from input files')
    p.add_argument('--input-file', help='Single input file to classify')
    p.add_argument('--input-dir', help='Directory of input files to classify')
    p.add_argument('--out', default='slice_registry.json', help='Output registry file')
    p.add_argument('--daemon', action='store_true', help='Run as a daemon/long-running process and keep slices active')
    p.add_argument('--no-activate', action='store_true', help="Don't mark slices active in status file")
    return p.parse_args()


def main():
    args = parse_args()
    files = []
    # Accept either a single file via --input-file, or a directory via --input-dir.
    # Also allow providing a single file path to --input-dir for convenience.
    if args.input_file:
        if not os.path.exists(args.input_file):
            print('Input file not found:', args.input_file)
            sys.exit(1)
        files.append(args.input_file)
    if args.input_dir:
        # If the provided path is a file, accept it as a single input file.
        if os.path.isfile(args.input_dir):
            files.append(args.input_dir)
        elif os.path.isdir(args.input_dir):
            for f in sorted(os.listdir(args.input_dir)):
                full = os.path.join(args.input_dir, f)
                if os.path.isfile(full):
                    files.append(full)
        else:
            print('Input path not found (file or dir):', args.input_dir)
            sys.exit(1)

    if not files:
        print('No input files provided. Use --input-file or --input-dir')
        sys.exit(1)

    registry = build_registry_from_files(files)
    # Print classification and created slices for user's visibility
    print('\nInput files analyzed:')
    for f in files:
        print(' -', f, '->', classify_input_file(os.path.basename(f)))

    if registry:
        print('\nSlices created:')
        for sname, cfg in registry.items():
            print(f" - {sname}: port={cfg.get('port')} created_from={cfg.get('created_from')}")
    else:
        print('No slices required from inputs')

    merged = write_registry(registry, args.out)

    # Activate unless explicitly disabled
    if not args.no_activate:
        try:
            activate_slices_in_status(registry)
            # Also write a runtime universal config to help slice_manager pick up full details
            # Use the registry (only slices derived from inputs) rather than the merged
            # registry so that previously-existing slices are not accidentally marked active.
            write_universal_runtime(registry)
        except Exception as e:
            print(f"Could not activate slices in status file: {e}")

    # Auto-enable daemon mode when user provided --input-file so orchestrator
    # behaves like a controller (keeps slices active) unless explicitly
    # requested otherwise via --no-activate.
    if args.input_file and not args.daemon:
        print('Auto-enabling daemon mode to keep slices active. Use --no-activate to avoid activation.')
        args.daemon = True

    # If daemon mode chosen, keep running and heartbeat status for the slices
    if args.daemon:
        print('Running in daemon mode. Press Ctrl+C to exit.')
        try:
            import time
            while True:
                # refresh activation timestamp for each slice to indicate liveness
                try:
                    activate_slices_in_status(registry)
                except Exception:
                    pass
                time.sleep(5)
        except KeyboardInterrupt:
            print('\nDaemon exiting; deactivating slices...')
            # mark them inactive on exit
            try:
                # load existing status and mark these slices inactive
                sp = 'slice_status.json'
                s = {}
                if os.path.exists(sp):
                    try:
                        with open(sp,'r') as _f:
                            s = json.load(_f)
                    except Exception:
                        s = {}
                for sn in registry.keys():
                    s[sn] = {'active': False, 'updated_at': datetime_now_iso()}
                tmp = sp + '.tmp'
                with open(tmp,'w') as _f:
                    json.dump(s, _f, indent=2)
                os.replace(tmp, sp)
            except Exception:
                pass


if __name__ == '__main__':
    main()

