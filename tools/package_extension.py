# -*- coding: utf-8 -*-
"""Package the Optical Transceiver HLA into a distributable zip.

The README that ships in the zip is the one already sitting in the extension
directory (extensions/optical_transceiver_hla/README.md). That file is the
single source of truth -- edit it directly, never duplicate its text here.

Runtime artifacts (hla_debug.log) are simply not in FILES_TO_PACK, so they can
never end up in the archive; there is no need to delete anything from the
working tree.
"""

import json
import os
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXT_DIR = os.path.join(ROOT, 'extensions', 'optical_transceiver_hla')

# Everything the extension needs at runtime, discovered rather than listed: the
# decoder is split across several modules and user_config.json is editable, and
# a hand-maintained list silently goes stale. A missing file is an ImportError
# or a silently ignored config on the user's machine, not here.
#
# Discovered by extension, not by name, so adding a module or a data file needs
# no change to this script.
PACKED_SUFFIXES = ('.py', '.json')
EXCLUDED = {'extension.json'}          # already covered by PACKED_SUFFIXES


def files_to_pack():
    found = sorted(f for f in os.listdir(EXT_DIR)
                   if f.endswith(PACKED_SUFFIXES) and f not in EXCLUDED)
    return ['extension.json', 'README.md'] + found


def main():
    with open(os.path.join(EXT_DIR, 'extension.json'), encoding='utf-8') as f:
        version = json.load(f)['version']

    files = files_to_pack()

    missing = [n for n in files if not os.path.exists(os.path.join(EXT_DIR, n))]
    if missing:
        raise SystemExit(f'ERROR: missing from {EXT_DIR}: {", ".join(missing)}')

    # Build output goes to _local/ so the repository root stays source-only.
    out_dir = os.path.join(ROOT, '_local')
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f'Optical_Transceiver_HLA_v{version}.zip')

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in files:
            arcname = os.path.join('optical_transceiver_hla', fname)
            zf.write(os.path.join(EXT_DIR, fname), arcname)
            print(f'Packed: {arcname}')

    print(f'SUCCESS: Created {zip_path} ({os.path.getsize(zip_path)} bytes)')


if __name__ == '__main__':
    main()
