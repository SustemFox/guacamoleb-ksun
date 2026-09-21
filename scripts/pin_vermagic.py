#!/usr/bin/env python3
"""
Pin the kernel's localversion so its vermagic matches the official
LineageOS kernel — required for the stock vendor WLAN module to load.

The stock module lives at /vendor/lib/modules/qca_cld3_wlan.ko and is part of
the ROM's vendor partition. Flashing only boot.img does not replace it, so the
newly built kernel must report the *same* release string, otherwise the module
refuses to load:

    qca_cld3_wlan: disagrees about version of symbol module_layout
    qca_cld3_wlan: no symbol version for module_layout

The kernel release string is assembled as:

    KERNELVERSION + CONFIG_LOCALVERSION + scm_version

`scm_version` (scripts/setlocalversion) normally appends `-g<git-sha>` of the
checked-out HEAD. Because we build on top of the upstream tree with a few extra
commits (the KSU patch series), that sha would differ from the official build.
The fix: drop a `.scmversion` file in the kernel tree — `scripts/setlocalversion`
returns its contents verbatim and skips all git probing.

This script derives the exact suffix from the official boot.img:

    official release : 4.14.357-openela-perf-g0521dc291cf1
    KERNELVERSION    : 4.14.357-openela        (make -s kernelversion)
    CONFIG_LOCALVERSION: -perf                 (.config)
    => .scmversion      : -g0521dc291cf1

Usage:
    pin_vermagic.py <kernel-dir> <official-boot.img> <out.config>
"""
import os
import re
import struct
import sys


RELEASE_RE = re.compile(rb'Linux version (\S+) ')


def extract_official_release(boot_path):
    """Return the release string of the kernel inside an Android boot image."""
    blob = open(boot_path, 'rb').read()
    if blob[:8] != b'ANDROID!':
        raise ValueError('not an Android boot image')

    page = struct.unpack('<I', blob[36:40])[0]
    ksize = struct.unpack('<I', blob[8:12])[0]
    kernel = blob[page:page + ksize]

    m = None
    for cand in RELEASE_RE.finditer(kernel):
        text = cand.group(1).decode(errors='replace')
        # skip format strings such as "Linux version %s "
        if '%' not in text:
            m = cand
            break
    if not m:
        # Kernel may be compressed; try gzip/lz4/zstd transparently.
        import gzip
        for opener, name in ((gzip.decompress, 'gzip'),):
            try:
                data = opener(kernel)
            except Exception:
                continue
            m = None
            for cand in RELEASE_RE.finditer(data):
                if '%' not in cand.group(1).decode(errors='replace'):
                    m = cand
                    break
            if m:
                break
        if not m:
            raise ValueError('kernel release string not found in boot image')
    return m.group(1).decode()


def kernelversion(kernel_dir):
    """Return VERSION.PATCHLEVEL.SUBLEVEL+EXTRAVERSION from the top Makefile.

    Parsed directly instead of running `make kernelversion`, so it works on an
    unconfigured tree (we run before the kernel is built).
    """
    values = {'EXTRAVERSION': ''}
    path = os.path.join(kernel_dir, 'Makefile')
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.rstrip('\n')
        for key in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL', 'EXTRAVERSION'):
            prefix = key + ' ='
            if line.startswith(prefix):
                values[key] = line[len(prefix):].strip()
    for key in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL'):
        if key not in values:
            raise ValueError('could not find %s in %s' % (key, path))
    base = '%s.%s.%s' % (values['VERSION'], values['PATCHLEVEL'],
                         values['SUBLEVEL'])
    return base + values['EXTRAVERSION']


def config_localversion(config_path):
    for line in open(config_path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line.startswith('CONFIG_LOCALVERSION='):
            v = line.split('=', 1)[1].strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            return v
    return ''


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--extract-boot':
        print(extract_official_release(sys.argv[2]))
        return 0
    if len(sys.argv) != 4:
        print(__doc__)
        return 1
    kernel_dir, boot_path, config_path = sys.argv[1:4]

    release = extract_official_release(boot_path)
    base = kernelversion(kernel_dir)
    cl = config_localversion(config_path)

    prefix = base + cl
    if not release.startswith(prefix):
        print('WARNING: official release %r does not start with %r'
              % (release, prefix), file=sys.stderr)

    scm = release[len(prefix):]
    if not scm:
        print('NOTE: official release has no scm suffix; nothing to pin')
        return 0
    if not scm.startswith('-g'):
        print('WARNING: unexpected scm suffix %r' % scm, file=sys.stderr)

    scmversion = os.path.join(kernel_dir, '.scmversion')
    with open(scmversion, 'w') as f:
        f.write(scm)
    print('official release : %s' % release)
    print('kernelversion    : %s' % base)
    print('localversion     : %s' % cl)
    print('wrote %s = %s' % (scmversion, scm))
    return 0


if __name__ == '__main__':
    sys.exit(main())
