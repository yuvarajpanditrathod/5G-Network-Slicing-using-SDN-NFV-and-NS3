#!/usr/bin/env python3
"""
List classification results for files under input-data/ and optionally create a registry
"""
import os
import sys
import argparse
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from radio import classify_input_file


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input-dir', default='input-data')
    p.add_argument('--write-registry', action='store_true', help='Write slice_registry.json using orchestrator')
    p.add_argument('--activate-slices', action='store_true', help='Activate classified slices via slice_manager (maps to taps)')
    args = p.parse_args()

    inp = os.path.abspath(args.input_dir)
    if not os.path.isdir(inp):
        print('Input dir not found:', inp)
        return

    files = [f for f in sorted(os.listdir(inp)) if os.path.isfile(os.path.join(inp, f))]
    mapping = {}
    for f in files:
        typ = classify_input_file(f)
        print(f"{f} -> {typ}")
        mapping.setdefault(typ, []).append(f)

    if args.write_registry:
        # call orchestrator
        from orchestrator import build_registry_from_files, write_registry
        full_paths = [os.path.join(inp, f) for f in files]
        reg = build_registry_from_files(full_paths)
        write_registry(reg)

    if args.activate_slices:
        try:
            from slice_manager import DynamicSliceManager
            mgr = DynamicSliceManager()
            # mapping from slice -> tap name (assumed default)
            tap_map = {'eMBB': 'tap-embb', 'URLLC': 'tap-urllc', 'mMTC': 'tap-mmtc'}
            for slice_name in mapping.keys():
                tap = tap_map.get(slice_name)
                if not tap:
                    print(f"No tap mapping for slice {slice_name}; skipping")
                    continue
                ok = mgr.activate_slice(slice_name, tap)
                print(f"Activated {slice_name} -> {tap}: {ok}")
        except Exception as e:
            print('Failed to activate slices:', e)


if __name__ == '__main__':
    main()
