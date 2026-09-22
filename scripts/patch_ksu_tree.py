#!/usr/bin/env python3
"""
Fix KernelSU-Next `legacy` build on Linux 4.14 and disable its unsafe
SELinux context-write hook.

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

Recent `legacy` also installs a hook on `/sys/fs/selinux/context` that rejects
all writes from app UIDs. Android itself writes this node while assigning a
zygote child's SELinux context, causing a userspace crash-loop on Android 16.
The patch leaves the remaining SELinux status-hide feature intact but does not
install that unsafe write hook.

Finally, current legacy stores app profiles as ABI v4 while the matching
v3.2.0 Manager sends ABI v3. The only v4 addition is `root_profile.flags` at
the end of the structure. The compatibility shim clears that new field and
migrates v3 to v4 before validation, preserving the established Manager ABI.

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

    selinux_path = os.path.join(ksu_dir, 'kernel/feature/selinux_hide.c')
    if not os.path.exists(selinux_path):
        print('patch_ksu_tree: selinux_hide not present, skipping')
        return 0

    selinux_src = open(selinux_path, encoding='utf-8').read()
    old_hook = '\thook_selinux_transaction_write();'
    new_hook = ('\t/* Android writes /sys/fs/selinux/context while setting a\n'
                '\t * zygote child context. Do not intercept this path. */\n'
                '\t/* hook_selinux_transaction_write(); */')
    if old_hook in selinux_src:
        selinux_src = selinux_src.replace(old_hook, new_hook, 1)
        open(selinux_path, 'w', encoding='utf-8').write(selinux_src)
        print('patch_ksu_tree: disabled unsafe SELinux context-write hook')
    elif new_hook in selinux_src:
        print('patch_ksu_tree: SELinux context-write hook already disabled')
    else:
        print('patch_ksu_tree: WARNING: SELinux hook call not found', file=sys.stderr)
        return 1
    profile_path = os.path.join(ksu_dir, 'kernel/policy/allowlist.c')
    profile_src = open(profile_path, encoding='utf-8').read()
    old_setter = """int ksu_set_app_profile(struct app_profile *profile)
{
    struct perm_data *p = NULL, *np;"""
    new_setter = """int ksu_set_app_profile(struct app_profile *profile)
{
    /* v3 Manager profiles predate root_profile.flags (v4). The field is at
     * the end of the root union member, so zero it before ABI migration. */
    if (profile && profile->version == 3) {
        profile->rp_config.profile.flags = 0;
        profile->version = KSU_APP_PROFILE_VER;
    }

    struct perm_data *p = NULL, *np;"""
    if old_setter in profile_src:
        profile_src = profile_src.replace(old_setter, new_setter, 1)
        open(profile_path, 'w', encoding='utf-8').write(profile_src)
        print('patch_ksu_tree: migrated Manager app profile ABI v3 to v4')
    elif new_setter in profile_src:
        print('patch_ksu_tree: Manager app profile ABI shim already applied')
    else:
        print('patch_ksu_tree: WARNING: app profile setter not found', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
