# Test Optical Transceiver Simulation Script
# Simulates I2C transactions for SFF-8472 (SFP+), SFF-8436 (QSFP28), and CMIS (QSFP-DD)
# Feeds frames into OpticalTransceiverHla and verifies decoding output.

import os
import sys
import csv

# Add extension directory to path
ext_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'extensions', 'optical_transceiver_hla'))
sys.path.insert(0, ext_dir)

from optical_hla import OpticalTransceiverHla, AnalyzerFrame, LOG_FILE

def generate_i2c_write(addr, reg, data_bytes, start_t=0.0):
    frames = []
    t = start_t
    frames.append(AnalyzerFrame('start', t, t + 0.0001, {}))
    t += 0.0001
    frames.append(AnalyzerFrame('address', t, t + 0.0001, {'address': [addr], 'read': False, 'ack': True}))
    t += 0.0001
    frames.append(AnalyzerFrame('data', t, t + 0.0001, {'data': [reg], 'ack': True}))
    t += 0.0001
    for b in data_bytes:
        frames.append(AnalyzerFrame('data', t, t + 0.0001, {'data': [b], 'ack': True}))
        t += 0.0001
    frames.append(AnalyzerFrame('stop', t, t + 0.0001, {}))
    return frames, t + 0.0005

def generate_i2c_read(addr, reg, data_bytes, start_t=0.0):
    frames = []
    t = start_t
    # 1. Set register pointer (Write)
    frames.append(AnalyzerFrame('start', t, t + 0.0001, {}))
    t += 0.0001
    frames.append(AnalyzerFrame('address', t, t + 0.0001, {'address': [addr], 'read': False, 'ack': True}))
    t += 0.0001
    frames.append(AnalyzerFrame('data', t, t + 0.0001, {'data': [reg], 'ack': True}))
    t += 0.0001
    # 2. Restart & Read data bytes
    frames.append(AnalyzerFrame('start', t, t + 0.0001, {}))
    t += 0.0001
    frames.append(AnalyzerFrame('address', t, t + 0.0001, {'address': [addr], 'read': True, 'ack': True}))
    t += 0.0001
    for b in data_bytes:
        frames.append(AnalyzerFrame('data', t, t + 0.0001, {'data': [b], 'ack': True}))
        t += 0.0001
    frames.append(AnalyzerFrame('stop', t, t + 0.0001, {}))
    return frames, t + 0.0005

def run_simulation():
    print('=' * 85)
    print('       Optical Transceiver Protocol Decoder - Simulation & Verification')
    print('=' * 85)

    hla = OpticalTransceiverHla({'module_standard': 'Auto-Detect'})
    results = []
    curr_time = 0.01

    # --- Scenario 1: SFF-8472 SFP+ 10G Transceiver ---
    print('\n>>> [Scenario 1] Simulating SFF-8472 (SFP+ 10G) Transceiver...')
    # A0h: Identifier 0x03 (SFP/SFP+)
    f, curr_time = generate_i2c_read(0x50, 0, [0x03], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Vendor Name 'FINISAR CORP.  ' at reg 20..35
    vendor_sfp = [ord(c) for c in 'FINISAR CORP.  ']
    f, curr_time = generate_i2c_read(0x50, 20, vendor_sfp, curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A2h (0x51): SFP+ DDM Telemetry
    # Temp: 35.50 °C (0x2380)
    # Vcc: 3.325 V (33250 -> 0x81E2)
    # TxBias: 6.54 mA (3270 -> 0x0CC6)
    # TxPower: 550.0 uW / -2.60 dBm (5500 -> 0x157C)
    # RxPower: 420.0 uW / -3.77 dBm (4200 -> 0x1068)
    # Status: 0x00
    ddm_bytes = [
        0x23, 0x80, # Temp (96-97)
        0x81, 0xE2, # Vcc (98-99)
        0x0C, 0xC6, # TxBias (100-101)
        0x15, 0x7C, # TxPower (102-103)
        0x10, 0x68, # RxPower (104-105)
        0x00, 0x00, 0x00, 0x00, # 106-109
        0x00        # Status (110)
    ]
    f, curr_time = generate_i2c_read(0x51, 96, ddm_bytes, curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # --- Scenario 2: SFF-8436 QSFP28 100G Module ---
    print('>>> [Scenario 2] Simulating SFF-8436 (QSFP28 100G) Module...')
    # A0h: Identifier 0x0D (QSFP28)
    f, curr_time = generate_i2c_read(0x50, 0, [0x0D], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Write Page Select 0x00 (Reg 127)
    f, curr_time = generate_i2c_write(0x50, 127, [0x00], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Upper Page 00h Vendor Name 'INNOLIGHT       ' at reg 129..144
    vendor_qsfp = [ord(c) for c in 'INNOLIGHT       ']
    f, curr_time = generate_i2c_read(0x50, 129, vendor_qsfp, curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # --- Scenario 3: CMIS 4.0 / 5.0 QSFP-DD 400G Module ---
    print('>>> [Scenario 3] Simulating CMIS (QSFP-DD 400G) Module & DataPath...')
    # A0h: Identifier 0x18 (QSFP-DD)
    f, curr_time = generate_i2c_read(0x50, 0, [0x18], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Module State (Byte 3, state 3 = Ready -> (3 << 1) = 6)
    f, curr_time = generate_i2c_read(0x50, 3, [0x06], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Bank Select = 0 (Reg 126)
    f, curr_time = generate_i2c_write(0x50, 126, [0x00], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Page Select = 0x10 (Reg 127 -> Page 10h DataPath Control)
    f, curr_time = generate_i2c_write(0x50, 127, [0x10], curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # A0h: Page 10h Lane 1..4 DataPath Control: AppSel=1, DataPathID=1 (0x11)
    lane_ctrl = [0x11, 0x11, 0x11, 0x11]
    f, curr_time = generate_i2c_read(0x50, 145, lane_ctrl, curr_time)
    for frame in f:
        res = hla.decode(frame)
        if res: results.append(res)

    # --- Output Summary ---
    print('\n' + '=' * 85)
    print(f' SUCCESS: Decoded {len(results)} HLA Analyzer Frames!')
    p_hdr, t_hdr, f_hdr, v_hdr = "Protocol", "Frame Type", "Field / Summary", "Decoded Value"
    print(f'{p_hdr:<10} | {t_hdr:<15} | {f_hdr:<30} | {v_hdr}')
    print('-' * 85)

    export_rows = []
    for r in results:
        data = r.data
        proto = data.get('protocol', '')
        if r.type == 'optical_field':
            field = data.get('field', '')
            val = data.get('value', '')
            print(f'{proto:<10} | {r.type:<15} | {field:<30} | {val}')
            export_rows.append({'protocol': proto, 'type': r.type, 'field_or_summary': field, 'value': val})
        elif r.type == 'optical_event':
            summary = data.get('summary', '')
            # Filter generic register read/write to keep summary table clean, or show key events
            if 'Set Reg' in summary or 'Page Select' in summary or 'Bank Select' in summary:
                print(f'{proto:<10} | {r.type:<15} | {summary:<30} | -')
            export_rows.append({'protocol': proto, 'type': r.type, 'field_or_summary': summary, 'value': ''})
        elif r.type == 'optical_alarm':
            alarm = data.get('alarm', '')
            print(f'{proto:<10} | *** ALARM ***  | {alarm:<30} | -')
            export_rows.append({'protocol': proto, 'type': r.type, 'field_or_summary': alarm, 'value': ''})

    # Export to CSV
    csv_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'optical_simulation_decoded.csv'))
    with open(csv_file, 'w', newline='', encoding='utf-8') as cf:
        writer = csv.DictWriter(cf, fieldnames=['protocol', 'type', 'field_or_summary', 'value'])
        writer.writeheader()
        writer.writerows(export_rows)

    print('-' * 85)
    print(f'[Export] Full decoded results saved to: {csv_file}')
    print(f'[Log]    Debug logs recorded in: {LOG_FILE}')

if __name__ == '__main__':
    run_simulation()
