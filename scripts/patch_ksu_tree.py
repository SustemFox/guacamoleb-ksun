#!/usr/bin/env python3
"""
Fix KernelSU-Next `legacy` build on Linux 4.14.

`kernel/sulog/event.c` guards the timestamp call with:

    #if KERNEL_VERSION(4, 19, 0) <= LINUX_VERSION_CODE
        ktime_get_boottime_ts64(&ts);
    #else
        get_monotonic_boottime(&ts);
    #endif

but on 4.14 `get_monotonic_boottime()` takes a `struct timespec *`, not
`struct timespec64 *`, so the build fails with:

    error: incompatible pointer types passing 'struct timespec64 *'
           to parameter of type 'struct timespec *'

Meanwhile `ktime_get_boottime_ts64()` already exists on 4.14
(include/linux/timekeeping.h), so the guard is simply wrong for this tree.

This script rewrites those blocks to always use the ts64 helper.

Usage:
    patch_ksu_tree.py <KernelSU-Next-dir>   (i.e. kernel/KernelSU-Next)
"""
import os
import sys

OLD = """#if KERNEL_VERSION(4, 19, 0) <= LINUX_VERSION_CODE
\tktime_get_boottime_ts64(&ts);
#else
\tget_monotonic_boottime(&ts);
#endif"""

NEW = """/*
 * 4.14 already provides ktime_get_boottime_ts64(); the old guard used
 * get_monotonic_boottime() which takes struct timespec (not timespec64)
 * on this kernel and does not compile.
 */
\tktime_get_boottime_ts64(&ts);"""


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    ksu_dir = sys.argv[1]
    path = os.path.join(ksu_dir, 'kernel/sulog/event.c')
    if not os.path.exists(path):
        # not present on older tags (e.g. v3.2.0-legacy) - nothing to do
        print('patch_ksu_tree: %s not present, skipping' % path)
        return 0

    src = open(path, encoding='utf-8').read()
    n = src.count(OLD)
    if n == 0:
        if 'ktime_get_boottime_ts64(&ts);' in src and 'get_monotonic_boottime(&ts);' not in src:
            print('patch_ksu_tree: already fixed')
            return 0
        print('patch_ksu_tree: WARNING: expected block not found in %s' % path,
              file=sys.stderr)
        return 1

    src = src.replace(OLD, NEW)
    open(path, 'w', encoding='utf-8').write(src)
    print('patch_ksu_tree: fixed %d timespec64 block(s) in %s' % (n, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
