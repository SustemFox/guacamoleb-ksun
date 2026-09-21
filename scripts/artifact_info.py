#!/usr/bin/env python3
"""
Inspect a kernel image or Android boot image and print metadata.

Used by CI as a gate: the custom kernel must have been produced by the same
clang the official LineageOS kernel was built with, otherwise LTO +
Shadow Call Stack codegen can differ and the device may hang early in boot.

Usage:
    artifact_info.py --clang-build-id <image>
    artifact_info.py --release        <image>
    artifact_info.py --info           <image>
"""
import re
import struct
import sys

CLANG_ID_RE = re.compile(rb'Android \((\d+),')
RELEASE_RE = re.compile(rb'Linux version (\S+) ')


def read_kernel(path):
    """Return the kernel blob from an Android boot image or a raw Image."""
    blob = open(path, 'rb').read()
    if blob[:8] == b'ANDROID!':
        # boot image: kernel starts after the header page
        page = struct.unpack('<I', blob[36:40])[0]
        ksize = struct.unpack('<I', blob[8:12])[0]
        return blob[page:page + ksize]
    return blob


def clang_build_id(kernel):
    m = CLANG_ID_RE.search(kernel)
    return m.group(1).decode() if m else ''


def release_string(kernel):
    for m in RELEASE_RE.finditer(kernel):
        text = m.group(1).decode(errors='replace')
        if '%' not in text:
            return text
    return ''


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    mode, path = sys.argv[1], sys.argv[2]
    kernel = read_kernel(path)

    if mode == '--clang-build-id':
        print(clang_build_id(kernel))
    elif mode == '--release':
        print(release_string(kernel))
    elif mode == '--info':
        print('clang_build_id : %s' % clang_build_id(kernel))
        print('release        : %s' % release_string(kernel))
        print('kernel_size    : %d' % len(kernel))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
