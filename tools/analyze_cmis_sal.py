import os
import sys
from saleae import automation

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sal_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'samples', 'CMIS_IIC.sal'))
    ext_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'extensions', 'optical_transceiver_hla'))
    csv_out = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'cmis_real_decoded.csv'))

    print(f'[1/4] Connecting to Saleae Logic 2 Automation (port 10430)...')
    manager = automation.Manager.connect(port=10430)

    print(f'[2/4] Loading capture file: {sal_file}...')
    capture = manager.load_capture(sal_file)
    print(f'      Capture loaded successfully!')

    print(f'[3/4] Adding I2C Analyzer (SDA=CH1, SCL=CH0)...')
    i2c = capture.add_analyzer('I2C', label='I2C (SDA: CH1, SCL: CH0)', settings={'SDA': 1, 'SCL': 0})
    print(f'      I2C Analyzer added! ID: {i2c}')

    print(f'[4/5] Attaching Dual-Track Optical Transceiver HLAs...')
    hla_ctrl = capture.add_high_level_analyzer(
        extension_directory=ext_dir,
        name='Optical Transceiver Decoder',
        input_analyzer=i2c,
        label='CMIS Control (DataPath/State)',
        settings={'module_standard': 'CMIS (QSFP-DD/OSFP)', 'filter_mode': 'Control & State Only'}
    )
    print(f'      Control Track HLA attached! ID: {hla_ctrl}')

    hla_data = capture.add_high_level_analyzer(
        extension_directory=ext_dir,
        name='Optical Transceiver Decoder',
        input_analyzer=i2c,
        label='CMIS Data (Read/Write)',
        settings={'module_standard': 'CMIS (QSFP-DD/OSFP)', 'filter_mode': 'Data & Registers Only'}
    )
    print(f'      Data Track HLA attached! ID: {hla_data}')

    print(f'[5/5] Exporting decoded HLA table to {csv_out}...')
    try:
        capture.export_data_table(filepath=csv_out, analyzers=[hla_ctrl, hla_data])
        print(f'      Export completed successfully!')
    except Exception as e:
        print(f'      Export error: {e}')

    # Print summary
    import csv
    with open(csv_out, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    print(f'\n=== CMIS Protocol Decoding Summary ({len(rows)} events) ===')
    fields = [r for r in rows if r.get('type') == 'optical_field']
    print(f'Total Decoded Optical Fields: {len(fields)}')
    for f in fields[:25]:
        try:
            print(f"  [{f.get('start_time')[:8]}s] {f.get('field')}: {f.get('value')}")
        except UnicodeEncodeError:
            print(f"  [{f.get('start_time')[:8]}s] {ascii(f.get('field'))}: {ascii(f.get('value'))}")
    if len(fields) > 25:
        print(f'  ... and {len(fields) - 25} more decoded fields in CSV!')

    print(f'Done! Capture session is left open in Logic 2 GUI for visual inspection.')

if __name__ == '__main__':
    main()
