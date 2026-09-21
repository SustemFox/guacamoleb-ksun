#!/usr/bin/env python3
"""
Apply the KernelSU options on top of the OFFICIAL kernel .config.

Why not a plain defconfig + olddefconfig run?

The official LineageOS kernel is built with a set of compiler-specific options
that a `vendor/sm8150-perf_defconfig` + `olddefconfig` run does NOT reliably
reproduce:

    CONFIG_LTO=y / CONFIG_LTO_CLANG=y / CONFIG_THINLTO=y
    CONFIG_SHADOW_CALL_STACK=y
    CONFIG_INIT_STACK_ALL_ZERO=y

Losing them yields a functionally different kernel (larger, weaker hardening)
than the one the ROM ships.  Starting from the configuration embedded in the
official kernel and changing ONLY the KernelSU delta keeps the build as close
to upstream as possible.

Usage:
    apply_ksu_config.py <in.config> <out.config>
"""
import sys

ENABLE = [
    'CONFIG_KSU',
    'CONFIG_KSU_MANUAL_HOOK',
    'CONFIG_TMPFS_XATTR',
    'CONFIG_OVERLAY_FS_REDIRECT_DIR',
    'CONFIG_OVERLAY_FS_XINO_AUTO',
]
DISABLE = [
    'CONFIG_KSU_DEBUG',
    'CONFIG_KSU_KPROBES_HOOK',
]


def parse(text):
    """Return (ordered lines, dict name -> 'y'|'m'|value|None)."""
    lines = []
    values = {}
    for raw in text.splitlines():
        line = raw.rstrip('\n')
        lines.append(line)
        s = line.strip()
        if s.startswith('CONFIG_') and '=' in s:
            k, v = s.split('=', 1)
            values[k] = v
        elif s.startswith('# CONFIG_') and s.endswith(' is not set'):
            values[s[2:-11]] = None
    return lines, values


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src, encoding='utf-8', errors='replace').read()
    lines, values = parse(text)

    touched = {}
    for name in ENABLE:
        touched[name] = 'y'
    for name in DISABLE:
        touched[name] = None

    out = []
    for line in lines:
        s = line.strip()
        key = None
        if s.startswith('CONFIG_') and '=' in s:
            key = s.split('=', 1)[0]
        elif s.startswith('# CONFIG_') and s.endswith(' is not set'):
            key = s[2:-11]
        if key in touched:
            continue
        out.append(line)

    out.append('')
    out.append('# ==== KernelSU delta (added by CI) ====')
    for name in ENABLE:
        out.append('%s=y' % name)
    for name in DISABLE:
        out.append('# %s is not set' % name)

    with open(dst, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')

    print('applied KSU delta: %d enabled, %d disabled'
          % (len(ENABLE), len(DISABLE)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
