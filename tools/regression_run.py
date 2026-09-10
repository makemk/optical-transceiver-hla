#!/usr/bin/env python3
"""Drive the optical HLA over a real capture through the Logic 2 MCP server and
export its decoded data table. Used to capture a baseline and to diff each
stage of the CMIS expansion against it.

    python tools/regression_run.py --out baseline.csv
    python tools/regression_run.py --out after.csv --diff baseline.csv

Notes learned the hard way (Stage 0 probes):
  * add_high_level_analyzer REQUIRES every setting the HLA declares.
  * export_data_table_csv only includes the HLA when it is named explicitly,
    via `analyzers: [{"analyzerId": N}]`.
  * the HLA module is re-imported from disk on every add_high_level_analyzer
    call, so edits are picked up without restarting Logic 2.
"""

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logic2_cli import mcp_call  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_SAL = os.path.join(ROOT, "samples", "CMIS_IIC.sal")
HLA_DIR = os.path.join(ROOT, "extensions", "optical_transceiver_hla")
HLA_NAME = "Optical Transceiver Decoder"


def load_rows(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def key_of(row):
    """Stable identity for a decoded row, independent of export ordering."""
    return "|".join([
        row.get("type", ""),
        row.get("field", ""),
        row.get("summary", ""),
        row.get("value", ""),
        row.get("protocol", ""),
        row.get("start_time", ""),
    ])


def run(args):
    ok, res = mcp_call("load_capture", {"filepath": args.sal}, timeout=120)
    if not ok:
        print("load_capture failed:", res)
        return 1
    cap_id = res.get("captureId")
    print("captureId =", cap_id)

    ok, res = mcp_call("add_analyzer", {
        "captureId": cap_id,
        "analyzerName": "I2C",
        "analyzerLabel": "Regress I2C",
        "settings": {"SDA": {"numberValue": args.sda}, "SCL": {"numberValue": args.scl}},
    })
    if not ok:
        print("add_analyzer failed:", res)
        mcp_call("close_capture", {"captureId": cap_id})
        return 1
    i2c_id = res.get("analyzerId")

    ok, res = mcp_call("add_high_level_analyzer", {
        "captureId": cap_id,
        "extensionDirectory": HLA_DIR,
        "hlaName": HLA_NAME,
        "hlaLabel": args.label,
        "inputAnalyzerId": i2c_id,
        # Every setting the HLA declares must be supplied or Logic 2 rejects the
        # call outright - adding a setting to the HLA means adding it here too.
        "settings": {
            "module_standard": {"stringValue": args.standard},
            "filter_mode": {"stringValue": args.filter},
            "output_mode": {"stringValue": args.output_mode},
            "compliance_mode": {"stringValue": args.compliance},
        },
    }, timeout=120)
    if not ok:
        print("add_high_level_analyzer failed:", res)
        mcp_call("close_capture", {"captureId": cap_id})
        return 1
    hla_id = res.get("analyzerId")
    print("hla analyzerId =", hla_id)

    time.sleep(args.settle)

    ok, res = mcp_call("export_data_table_csv", {
        "captureId": cap_id,
        "filepath": os.path.abspath(args.out),
        "analyzers": [{"analyzerId": hla_id}],
    }, timeout=300)
    print("export ->", ok, str(res)[:160])
    mcp_call("close_capture", {"captureId": cap_id})

    if not ok or not os.path.exists(args.out):
        return 1

    rows = load_rows(args.out)
    print("rows = %d" % len(rows))
    return 0


def diff(baseline_path, current_path):
    base = load_rows(baseline_path)
    cur = load_rows(current_path)
    print("\n" + "=" * 72)
    print("DIFF  baseline=%d rows  current=%d rows" % (len(base), len(cur)))
    print("=" * 72)

    from collections import Counter
    b, c = Counter(key_of(r) for r in base), Counter(key_of(r) for r in cur)

    gone = list((b - c).elements())
    added = list((c - b).elements())

    if not gone and not added:
        print("IDENTICAL - no decoded row changed.")
        return 0

    print("\n--- REMOVED (%d) ---" % len(gone))
    for k in gone[:40]:
        print("  " + k)
    if len(gone) > 40:
        print("  ... and %d more" % (len(gone) - 40))

    print("\n--- ADDED (%d) ---" % len(added))
    for k in added[:40]:
        print("  " + k)
    if len(added) > 40:
        print("  ... and %d more" % (len(added) - 40))
    return 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sal", default=DEFAULT_SAL)
    p.add_argument("--out", required=True)
    p.add_argument("--diff", default=None, help="Baseline CSV to diff against")
    p.add_argument("--standard", default="CMIS (QSFP-DD/OSFP)")
    p.add_argument("--filter", default="Show All")
    p.add_argument("--output-mode", default="Per Byte",
                   choices=["Per Byte", "Transaction Summary"])
    p.add_argument("--compliance", default="Warnings + Errors",
                   choices=["Warnings + Errors", "Errors Only", "Off"])
    p.add_argument("--label", default="Regress HLA")
    p.add_argument("--sda", type=int, default=1)
    p.add_argument("--scl", type=int, default=0)
    p.add_argument("--settle", type=float, default=5.0)
    args = p.parse_args()

    rc = run(args)
    if rc == 0 and args.diff:
        rc = diff(args.diff, args.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
