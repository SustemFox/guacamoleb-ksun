#!/usr/bin/env python3
"""
Extract the embedded kernel configuration (IKCONFIG) from the kernel inside an
Android boot image.

The official LineageOS kernel ships its resolved .config in the kernel image,
bracketed by the markers:

    IKCFG_ST <gzip stream> IKCFG_ED

This gives us the *exact* configuration the shipped kernel was built with —
including compiler-specific options such as CONFIG_LTO_CLANG,
CONFIG_SHADOW_CALL_STACK and CONFIG_INIT_STACK_ALL_ZERO that a plain
defconfig + olddefconfig run can silently lose.

Usage:
    extract_config.py <boot.img> <out.config>
"""
import gzip
import struct
import sys

IKCFG_ST = b'IKCFG_ST'
IKCFG_ED = b'IKCFG_ED'
GZIP_MAGIC = b'\x1f\x8b\x08'


def extract_kernel(blob):
    if blob[:8] != b'ANDROID!':
        raise ValueError('not an Android boot image (bad magic)')
    page = struct.unpack('<I', blob[36:40])[0]
    ksize = struct.unpack('<I', blob[8:12])[0]
    return blob[page:page + ksize]


def extract_config(boot_path):
    kernel = extract_kernel(open(boot_path, 'rb').read())
    start = kernel.find(IKCFG_ST)
    if start < 0:
        raise ValueError('IKCFG_ST not found in kernel image')
    gz = kernel.find(GZIP_MAGIC, start)
    if gz < 0:
        raise ValueError('gzip stream not found after IKCFG_ST')
    end = kernel.find(IKCFG_ED, gz)
    if end < 0:
        raise ValueError('IKCFG_ED not found')
    return gzip.decompress(kernel[gz:end])


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    cfg = extract_config(sys.argv[1])
    with open(sys.argv[2], 'wb') as f:
        f.write(cfg)
    print('wrote %s (%d bytes)' % (sys.argv[2], len(cfg)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
