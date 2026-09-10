#!/usr/bin/env python3
"""
Saleae Logic 2 MCP Command-Line Utility for Antigravity & Embedded Engineers
Full feature-set:
  - Query hardware and simulation devices
  - Timed capture & Hardware edge trigger capture
  - Built-in multi-protocol analyzers (I2C, UART/Async Serial, SPI, CAN)
  - Automatic digital waveform signal analysis (transitions, pulse width, frequency estimation)
  - Decoded protocol packet table preview
  - Health-check and auto-launch Logic 2 application
"""

import sys
import os
import json
import urllib.request
import urllib.error
import argparse
import subprocess
import time

LOGIC2_MCP_URL = "http://127.0.0.1:10530/"
DEFAULT_LOGIC_PATH = r"C:\Users\J03378\AppData\Local\Programs\Logic\Logic.exe"

def mcp_call(tool_name, arguments=None, timeout=60):
    if arguments is None:
        arguments = {}
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 100000,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    req = urllib.request.Request(
        LOGIC2_MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                return False, data["error"]
            result = data.get("result", {})
            struct = result.get("structuredContent")
            if struct is not None:
                return True, struct
            content = result.get("content", [])
            if content and content[0].get("text"):
                try:
                    return True, json.loads(content[0]["text"])
                except Exception:
                    return True, content[0]["text"]
            return True, result
    except urllib.error.HTTPError as he:
        return False, f"HTTP Error {he.code}: {he.read().decode('utf-8', errors='ignore')}"
    except Exception as ex:
        return False, f"Connection failed: {ex}. Ensure Logic 2 is running and MCP Server is enabled."

def check_server_health():
    try:
        req = urllib.request.Request(
            LOGIC2_MCP_URL,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False

def cmd_status(args):
    print("================================================================================")
    print("                      Saleae Logic 2 MCP Server Status                          ")
    print("================================================================================")
    online = check_server_health()
    if not online:
        print(f"[-] Status: OFFLINE (Cannot connect to {LOGIC2_MCP_URL})")
        print("    Please ensure Logic 2 is running and MCP Server is enabled in Settings.")
        print(f"    To auto-launch: python {os.path.basename(__file__)} launch")
        return

    print(f"[+] Status: ONLINE (Connected to {LOGIC2_MCP_URL})")

    # Get device list
    ok, res = mcp_call("get_devices")
    if ok:
        devices = res.get("devices", []) if isinstance(res, dict) else []
        print(f"[+] Connected Devices: {len(devices)}")
        for d in devices:
            dev_id = d.get("deviceId", "N/A")
            dev_type = d.get("deviceType", "Unknown")
            sim = " [Simulation]" if d.get("isSimulation") else " [Hardware]"
            print(f"    - Model: {dev_type:<10} | ID: {dev_id:<20}{sim}")
    else:
        print(f"[-] Device query error: {res}")
    print("================================================================================")

def cmd_launch(args):
    if check_server_health():
        print("[+] Logic 2 MCP Server is already running and online!")
        return

    path = args.path if args.path else DEFAULT_LOGIC_PATH
    if not os.path.exists(path):
        print(f"[-] Logic.exe not found at: {path}")
        return

    print(f"[+] Launching Logic 2 from: {path} ...")
    subprocess.Popen([path, "--automation"])
    print("[*] Waiting for MCP Server on port 10530 to initialize...")
    for _ in range(15):
        time.sleep(1)
        if check_server_health():
            print("[+] Logic 2 started and MCP Server is now ONLINE!")
            return
    print("[!] Logic 2 process started, but MCP port 10530 is not responding yet. Please check UI.")

def cmd_devices(args):
    ok, res = mcp_call("get_devices")
    if not ok:
        print(f"[Error] Failed to get devices: {res}")
        sys.exit(1)
    devices = res.get("devices", []) if isinstance(res, dict) else []
    if not devices:
        print("[Devices] No devices found or connected.")
        return
    print(f"[Devices] Found {len(devices)} device(s):")
    for d in devices:
        dev_id = d.get("deviceId", "N/A")
        dev_type = d.get("deviceType", "Unknown")
        sim = " (Simulation)" if d.get("isSimulation") else " (Hardware)"
        print(f"  - ID: {dev_id} | Type: {dev_type}{sim}")

def print_signal_summary(csv_file):
    if not os.path.exists(csv_file):
        return

    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        if len(lines) < 2:
            return

        header = lines[0].split(",")
        channels = header[1:]
        events = [l.split(",") for l in lines[1:]]

        print("\n---------------------- [Captured Signal Analysis] ----------------------")
        print(f"Channels analyzed: {', '.join(channels)} | Total transition events: {len(events)}")

        times = [float(e[0]) for e in events]
        total_duration = times[-1] - times[0] if len(times) > 1 else 0

        for idx, ch_name in enumerate(channels):
            col_idx = idx + 1
            levels = [int(e[col_idx]) for e in events]
            transitions = 0
            high_times = []
            low_times = []

            for i in range(1, len(levels)):
                if levels[i] != levels[i - 1]:
                    transitions += 1
                    dt = times[i] - times[i - 1]
                    if levels[i - 1] == 1:
                        high_times.append(dt)
                    else:
                        low_times.append(dt)

            if transitions == 0:
                state_str = "CONSTANT LOW (0 / Idle)" if levels[0] == 0 else "CONSTANT HIGH (1 / VCC)"
                print(f"  * {ch_name:<12}: {state_str} (No pulse detected in {total_duration:.4f}s)")
            else:
                avg_high = sum(high_times) / len(high_times) if high_times else 0
                avg_low = sum(low_times) / len(low_times) if low_times else 0
                period = avg_high + avg_low
                freq_str = f"~{1.0 / period:.2f} Hz" if period > 0 else "N/A"
                print(f"  * {ch_name:<12}: {transitions} transitions | Est. Freq: {freq_str} | Min pulse: {min(high_times + low_times):.6f}s")
        print("------------------------------------------------------------------------\n")
    except Exception as e:
        print(f"[Summary Note] Could not analyze CSV: {e}")

def print_table_summary(table_csv):
    if not os.path.exists(table_csv):
        return

    try:
        with open(table_csv, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        if len(lines) <= 1:
            print("[Decoded Table] No protocol packets detected in captured duration.")
            return

        header = lines[0].split(",")
        rows = [l.split(",") for l in lines[1:]]

        print(f"\n------------------ [Decoded Protocol Packets ({len(rows)} entries)] ------------------")
        print(f"{'Time':<14} | {'Type':<12} | {'Description / Data'}")
        print("-" * 72)
        for r in rows[:15]:
            t_str = f"{float(r[2]):.6f}s" if len(r) > 2 else "0s"
            type_str = r[1] if len(r) > 1 else "DATA"
            data_str = r[0] if len(r) > 0 else ""
            print(f"{t_str:<14} | {type_str:<12} | {data_str}")
        if len(rows) > 15:
            print(f"... ({len(rows) - 15} more packets omitted, see full CSV)")
        print("------------------------------------------------------------------------\n")
    except Exception as e:
        print(f"[Table Note] Could not read decoded table: {e}")

def cmd_capture(args):
    channels = [int(c.strip()) for c in args.channels.split(",") if c.strip()]

    # Configure capture timing or trigger
    if args.trigger_channel is not None:
        trig_type = 1 if args.trigger_edge.lower() == "rising" else 2
        edge_name = "RISING (0->1)" if trig_type == 1 else "FALLING (1->0)"
        print(f"[Capture] Configured Hardware Trigger on CH{args.trigger_channel} ({edge_name})...")
        print(f"[Capture] Will record {args.after_trigger}s after trigger fires.")
        capture_cfg = {
            "digitalCaptureMode": {
                "triggerType": trig_type,
                "triggerChannelIndex": args.trigger_channel,
                "afterTriggerSeconds": args.after_trigger
            }
        }
    else:
        print(f"[Capture] Starting timed capture on channels {channels} for {args.duration}s at {args.rate} Sa/s...")
        capture_cfg = {
            "timedCaptureMode": {
                "durationSeconds": args.duration
            }
        }

    start_args = {
        "logicDeviceConfiguration": {
            "logicChannels": {
                "digitalChannels": channels
            },
            "digitalSampleRate": args.rate
        },
        "captureConfiguration": capture_cfg
    }
    if args.device:
        start_args["deviceId"] = args.device

    ok, res = mcp_call("start_capture", start_args)
    if not ok:
        print(f"[Error] Start capture failed: {res}")
        sys.exit(1)

    cap_id = res.get("captureId")
    print(f"[Capture] Capture started with ID: {cap_id}. Waiting for completion...")

    ok, wait_res = mcp_call("wait_capture", {"captureId": cap_id}, timeout=300)
    if not ok:
        print(f"[Error] Wait capture failed: {wait_res}")
        mcp_call("close_capture", {"captureId": cap_id})
        sys.exit(1)

    print("[Capture] Capture finished successfully!")

    # Protocol Analyzers
    analyzers_added = []

    # 1. I2C
    if args.i2c:
        print(f"[Analyzer] Adding I2C protocol analyzer (SDA: CH{args.i2c_sda}, SCL: CH{args.i2c_scl})...")
        ok, ares = mcp_call("add_analyzer", {
            "captureId": cap_id,
            "analyzerName": "I2C",
            "analyzerLabel": f"I2C (SDA:{args.i2c_sda}, SCL:{args.i2c_scl})",
            "settings": {
                "SDA": {"numberValue": args.i2c_sda},
                "SCL": {"numberValue": args.i2c_scl}
            }
        })
        if ok:
            aid = ares.get("analyzerId")
            analyzers_added.append(aid)
            print(f"[Analyzer] I2C analyzer active! (ID: {aid})")
        else:
            print(f"[Warning] Failed to add I2C analyzer: {ares}")

    # 2. UART / Async Serial
    if args.uart:
        print(f"[Analyzer] Adding UART / Async Serial analyzer (RX: CH{args.uart_rx}, Baud: {args.baud})...")
        ok, ares = mcp_call("add_analyzer", {
            "captureId": cap_id,
            "analyzerName": "Async Serial",
            "analyzerLabel": f"UART ({args.baud}bps, CH{args.uart_rx})",
            "settings": {
                "Input Channel": {"numberValue": args.uart_rx},
                "Bit Rate (Bits/s)": {"numberValue": args.baud}
            }
        })
        if ok:
            aid = ares.get("analyzerId")
            analyzers_added.append(aid)
            print(f"[Analyzer] UART analyzer active! (ID: {aid})")
        else:
            print(f"[Warning] Failed to add UART analyzer: {ares}")

    # 3. SPI
    if args.spi:
        print(f"[Analyzer] Adding SPI analyzer (CLK: CH{args.spi_clk}, MOSI: CH{args.spi_mosi})...")
        spi_settings = {
            "Clock": {"numberValue": args.spi_clk},
            "MOSI": {"numberValue": args.spi_mosi}
        }
        if args.spi_miso is not None:
            spi_settings["MISO"] = {"numberValue": args.spi_miso}
        if args.spi_cs is not None:
            spi_settings["Enable"] = {"numberValue": args.spi_cs}

        ok, ares = mcp_call("add_analyzer", {
            "captureId": cap_id,
            "analyzerName": "SPI",
            "analyzerLabel": f"SPI (CLK:{args.spi_clk}, MOSI:{args.spi_mosi})",
            "settings": spi_settings
        })
        if ok:
            aid = ares.get("analyzerId")
            analyzers_added.append(aid)
            print(f"[Analyzer] SPI analyzer active! (ID: {aid})")
        else:
            print(f"[Warning] Failed to add SPI analyzer: {ares}")

    # 4. CAN
    if args.can:
        print(f"[Analyzer] Adding CAN analyzer (RX: CH{args.can_channel}, Baud: {args.can_baud})...")
        ok, ares = mcp_call("add_analyzer", {
            "captureId": cap_id,
            "analyzerName": "CAN",
            "analyzerLabel": f"CAN ({args.can_baud}bps, CH{args.can_channel})",
            "settings": {
                "CAN": {"numberValue": args.can_channel},
                "Bit Rate (Bits/s)": {"numberValue": args.can_baud}
            }
        })
        if ok:
            aid = ares.get("analyzerId")
            analyzers_added.append(aid)
            print(f"[Analyzer] CAN analyzer active! (ID: {aid})")
        else:
            print(f"[Warning] Failed to add CAN analyzer: {ares}")

    # 5. MDIO
    if args.mdio:
        print(f"[Analyzer] Adding MDIO analyzer (MDIO: CH{args.mdio_pin}, MDC: CH{args.mdc_pin})...")
        ok, ares = mcp_call("add_analyzer", {
            "captureId": cap_id,
            "analyzerName": "MDIO",
            "analyzerLabel": f"MDIO (MDIO:{args.mdio_pin}, MDC:{args.mdc_pin})",
            "settings": {
                "MDIO": {"numberValue": args.mdio_pin},
                "MDC": {"numberValue": args.mdc_pin}
            }
        })
        if ok:
            aid = ares.get("analyzerId")
            analyzers_added.append(aid)
            print(f"[Analyzer] MDIO analyzer active! (ID: {aid})")
        else:
            print(f"[Warning] Failed to add MDIO analyzer: {ares}")

    # 6. Optical Transceiver HLA (CMIS / SFF-8472 / SFF-8436)
    if args.optical:
        # Ensure underlying I2C bus analyzer is added
        i2c_id = None
        if not args.i2c:
            print(f"[Analyzer] Adding underlying I2C bus analyzer for Optical Module (SDA: CH{args.optical_sda}, SCL: CH{args.optical_scl})...")
            ok, ares = mcp_call("add_analyzer", {
                "captureId": cap_id,
                "analyzerName": "I2C",
                "analyzerLabel": f"Optical I2C (SDA:{args.optical_sda}, SCL:{args.optical_scl})",
                "settings": {
                    "SDA": {"numberValue": args.optical_sda},
                    "SCL": {"numberValue": args.optical_scl}
                }
            })
            if ok:
                i2c_id = ares.get("analyzerId")
                analyzers_added.append(i2c_id)
        else:
            i2c_id = analyzers_added[0] if analyzers_added else None

        if i2c_id:
            ext_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "extensions", "optical_transceiver_hla"))
            if len(ext_dir) >= 2 and ext_dir[1] == ':':
                ext_dir = ext_dir[0].upper() + ext_dir[1:]
            print(f"[HLA] Attaching Optical Transceiver Protocol Decoder (CMIS/SFF-8472/SFF-8436) on I2C ID {i2c_id}...")
            ok, ares = mcp_call("add_high_level_analyzer", {
                "captureId": cap_id,
                "extensionDirectory": ext_dir,
                "hlaName": "Optical Transceiver Decoder",
                "hlaLabel": "Optical Module (CMIS/SFF-8472/SFF-8436)",
                "inputAnalyzerId": i2c_id,
                "settings": {
                    "module_standard": {"stringValue": "Auto-Detect"}
                }
            })
            if ok:
                hla_id = ares.get("analyzerId")
                analyzers_added.append(hla_id)
                print(f"[HLA] Optical Transceiver Protocol Decoder Active! (ID: {hla_id})")
            else:
                print(f"[Warning] Failed to add Optical Transceiver HLA: {ares}")

    # Save .sal session
    if args.save:
        ok, sres = mcp_call("save_capture", {"captureId": cap_id, "filepath": args.save})
        if ok:
            print(f"[Capture] Saved session to: {args.save}")
        else:
            print(f"[Warning] Save failed: {sres}")

    # Export raw CSV
    exported_csv_path = None
    if args.export_csv:
        os.makedirs(args.export_csv, exist_ok=True)
        ok, eres = mcp_call("export_raw_data_csv", {
            "captureId": cap_id,
            "directory": args.export_csv,
            "analogDownsampleRatio": 1
        })
        if ok:
            exported_csv_path = os.path.join(args.export_csv, "digital.csv")
            print(f"[Capture] Raw digital CSV exported to: {exported_csv_path}")
            print_signal_summary(exported_csv_path)
        else:
            print(f"[Warning] Export CSV failed: {eres}")

    # Export decoded protocol data table
    if args.export_table:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_table)), exist_ok=True)
        ok, tres = mcp_call("export_data_table_csv", {
            "captureId": cap_id,
            "filepath": args.export_table
        })
        if ok:
            print(f"[Analyzer] Decoded protocol table exported to: {args.export_table}")
            print_table_summary(args.export_table)
        else:
            print(f"[Warning] Export data table failed: {tres}")

    if not args.keep_open:
        mcp_call("close_capture", {"captureId": cap_id})
        print("[Capture] Session closed and resources freed.")
    else:
        print(f"[Capture] Session {cap_id} kept open in Logic 2 GUI for live inspection.")

def main():
    parser = argparse.ArgumentParser(description="Saleae Logic 2 MCP Command-Line Utility")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # status
    subparsers.add_parser("status", help="Check Logic 2 MCP server health & devices")

    # launch
    p_launch = subparsers.add_parser("launch", help="Launch Logic 2 software with automation")
    p_launch.add_argument("--path", default=None, help="Custom path to Logic.exe")

    # devices
    subparsers.add_parser("devices", help="List connected Saleae devices")

    # capture
    p_cap = subparsers.add_parser("capture", help="Trigger signal capture and analysis")
    p_cap.add_argument("--channels", default="0,1", help="Comma-separated digital channels (default: '0,1')")
    p_cap.add_argument("--duration", type=float, default=2.0, help="Timed duration in seconds (default: 2.0)")
    p_cap.add_argument("--rate", type=int, default=10000000, help="Sample rate in Sa/s (default: 10 MSa/s)")
    p_cap.add_argument("--device", default=None, help="Device ID (optional)")
    p_cap.add_argument("--save", default=None, help="Save session to .sal file path")
    p_cap.add_argument("--export-csv", default=None, help="Export raw channel samples to CSV directory")
    p_cap.add_argument("--export-table", default=None, help="Export decoded analyzer packets to CSV file")
    p_cap.add_argument("--keep-open", action="store_true", help="Keep session open in Logic 2 GUI")

    # Hardware Trigger options
    p_cap.add_argument("--trigger-channel", type=int, default=None, help="Digital channel to trigger on")
    p_cap.add_argument("--trigger-edge", choices=["rising", "falling"], default="falling", help="Trigger edge")
    p_cap.add_argument("--after-trigger", type=float, default=1.0, help="Seconds to capture after trigger")

    # Protocol Analyzer options
    # I2C
    # NOTE: defaults follow the verified wiring used by tools/analyze_cmis_sal.py
    # (SDA -> CH1, SCL -> CH0) so the CLI and the Automation script agree.
    p_cap.add_argument("--i2c", action="store_true", help="Attach I2C protocol analyzer")
    p_cap.add_argument("--i2c-sda", type=int, default=1, help="I2C SDA channel (default: 1)")
    p_cap.add_argument("--i2c-scl", type=int, default=0, help="I2C SCL channel (default: 0)")

    # UART / Serial
    p_cap.add_argument("--uart", action="store_true", help="Attach UART/Async Serial analyzer")
    p_cap.add_argument("--uart-rx", type=int, default=0, help="UART RX channel (default: 0)")
    p_cap.add_argument("--baud", type=int, default=115200, help="UART baud rate (default: 115200)")

    # SPI
    p_cap.add_argument("--spi", action="store_true", help="Attach SPI protocol analyzer")
    p_cap.add_argument("--spi-clk", type=int, default=0, help="SPI Clock channel (default: 0)")
    p_cap.add_argument("--spi-mosi", type=int, default=1, help="SPI MOSI channel (default: 1)")
    p_cap.add_argument("--spi-miso", type=int, default=None, help="SPI MISO channel (optional)")
    p_cap.add_argument("--spi-cs", type=int, default=None, help="SPI Enable/CS channel (optional)")

    # CAN
    p_cap.add_argument("--can", action="store_true", help="Attach CAN protocol analyzer")
    p_cap.add_argument("--can-channel", type=int, default=0, help="CAN channel (default: 0)")
    p_cap.add_argument("--can-baud", type=int, default=500000, help="CAN baud rate (default: 500000)")

    # MDIO
    p_cap.add_argument("--mdio", action="store_true", help="Attach MDIO protocol analyzer")
    p_cap.add_argument("--mdio-pin", type=int, default=0, help="MDIO data pin channel (default: 0)")
    p_cap.add_argument("--mdc-pin", type=int, default=1, help="MDC clock pin channel (default: 1)")

    # Optical Transceiver HLA
    p_cap.add_argument("--optical", action="store_true", help="Attach Optical Transceiver Protocol Decoder (CMIS / SFF-8472 / SFF-8436)")
    p_cap.add_argument("--optical-sda", type=int, default=1, help="Optical I2C SDA channel (default: 1)")
    p_cap.add_argument("--optical-scl", type=int, default=0, help="Optical I2C SCL channel (default: 0)")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "launch":
        cmd_launch(args)
    elif args.command == "devices":
        cmd_devices(args)
    elif args.command == "capture":
        cmd_capture(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
