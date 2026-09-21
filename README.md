# guacamoleb (OnePlus 7) — LineageOS 23.2 kernel with KernelSU-Next

Builds a flashable **boot.img** for `guacamoleb` from the **LineageOS 23.2**
kernel source, with **KernelSU-Next (legacy, non-GKI, manual hooks)** compiled in,
plus the matching rebuilt kernel modules.

---

## TL;DR — what you flash

| step | file | how |
|---|---|---|
| 1 | `boot-guacamoleb-*.img` | `fastboot flash boot <file>` (PC required, once) |
| 2 | `kernel-modules-ksu.zip` | KernelSU-Next Manager → Modules → Install (on device) |

**Both are required.** Without the module zip Wi-Fi will not come up (see below).

---

## Why manual hooks

The sm8150 kernel (`4.14.357-openela`) has:

```
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
# CONFIG_KPROBES is not set        <-- the blocker
```

KernelSU-Next's default hook mode (`KSU_KPROBES_HOOK`) needs
`KPROBES + KRETPROBES + HAVE_SYSCALL_TRACEPOINTS`. Since KPROBES is disabled,
the build uses the **manual (in-tree) hook** mode (`CONFIG_KSU_MANUAL_HOOK=y`).

The mainline KernelSU-Next line (>= v3.3.0) does **not** compile on 4.14:
`hook/syscall_hook.h` uses `syscall_fn_t`, which was introduced on arm64 only
in 4.19.

## Why the `legacy` branch and not `v3.2.0-legacy`

The pinned tag `v3.2.0-legacy` is from **2026-04-14**. The `legacy` branch has
17 commits on top of it, including:

* `f6a1570c` **2026-09-20** — *legacy: non-GKI update — **execveat (new
  bionic)**, hardening, syscall table hooking*. Android 16's bionic maps
  `execve`/`execv` to `execveat(AT_FDCWD, ...)`; the old tag does not handle
  that, which is consistent with a hang very early in boot.
* `13ad2b4c` — sucompat / `__init`/`__exit` fixes
* `53791c92` — ABBA deadlock fix with `packages.list` rename

### The one patch we must apply on top

`legacy` does **not** build on 4.14 as-is:

```
drivers/kernelsu/sulog/event.c:67: error: incompatible pointer types passing
  'struct timespec64 *' to parameter of type 'struct timespec *'
```

The guard is

```c
#if KERNEL_VERSION(4, 19, 0) <= LINUX_VERSION_CODE
    ktime_get_boottime_ts64(&ts);
#else
    get_monotonic_boottime(&ts);   /* takes struct timespec on 4.14 */
#endif
```

but 4.14 already provides `ktime_get_boottime_ts64()`
(`include/linux/timekeeping.h`). `scripts/patch_ksu_tree.py` rewrites the
block to always use the ts64 helper. It is idempotent and skips older tags
that do not contain the file.

## Why the kernel modules are shipped

The official kernel builds the WLAN driver as a module:

```
CONFIG_QCA_CLD_WLAN=m      ->  /vendor/lib/modules/qca_cld3_wlan.ko
CONFIG_USB_GSPCA=m         ->  /vendor/lib/modules/gspca_main.ko
CONFIG_MODVERSIONS=y       ->  symbol CRCs are tied to the exact build
```

These modules are built **from the kernel tree during the ROM build**. Because
`CONFIG_MODVERSIONS=y`, the copies in `/vendor` only load against the kernel
they were built with. A custom kernel alone therefore breaks Wi-Fi
(`disagrees about version of symbol module_layout`). The build rebuilds the
modules and ships them in a **KernelSU module zip** that magic-mounts them over
`/vendor/lib/modules`, so `/vendor` itself stays untouched (AVB-safe).

Note the rename: the driver builds as `wlan.ko` but init loads it as
`qca_cld3_wlan.ko` (`init.target.rc`). LineageOS does the same via
`TARGET_MODULE_ALIASES`.

## Why the config comes from the official boot.img

A `defconfig + olddefconfig` run does **not** reproduce the official
configuration: the kernel Makefile's `check-clang-specific-options` rule
**disables** compiler-specific options whenever `cc-name != clang`:

```
clang-specific-configs := LTO_CLANG CFI_CLANG SHADOW_CALL_STACK INIT_STACK_ALL_ZERO
```

A single bare `make` (which defaults `CC` to `$(CROSS_COMPILE)gcc`) therefore
silently drops `CONFIG_LTO`, `CONFIG_THINLTO`, `CONFIG_SHADOW_CALL_STACK` and
`CONFIG_INIT_STACK_ALL_ZERO`, producing a larger, weaker kernel.

The workflow instead:

1. extracts the **exact official `.config`** from the shipped `boot.img`
   (`IKCONFIG`, `scripts/extract_config.py`);
2. applies only the **KernelSU delta** (`scripts/apply_ksu_config.py`);
3. runs every `make` through `scripts/kmake.sh`, which always passes clang.

The resulting config differs from the official one **only** by the intended
KernelSU options (7 lines).

## Toolchain

The official kernel banner reports:

```
Android (14054515, +pgo, +bolt, +lto, +mlgo, ...) clang version 21.0.0
```

`14054515` is **`clang-r563880c`**, not `clang-r563880` (which is `13783749`).
With LTO + Shadow Call Stack a different clang can change early-boot code, so
the build pins `r563880c` and **fails** if the produced kernel was not built
with build id `14054515` (`scripts/artifact_info.py`).

> When changing `CLANG_TARBALL`, bump the toolchain cache key in the workflow —
> otherwise a stale toolchain is restored from cache.

## AVB: the boot image is re-signed

The embedded `vbmeta` struct sits immediately after the kernel/ramdisk/DTB
body, and the AVB footer at the end of the image points at it. Since the custom
kernel changes the body length, that struct moves. Copying the old AVB area
leaves the footer pointing at garbage:

```
avbtool info_image --image boot.img
-> "Given image does not look like a vbmeta image"
```

The workflow re-signs the image with `avbtool add_hash_footer`, reusing the
salt / algorithm / properties of the original, and then **verifies** it. It
also fails the build if verification does not pass.

(`ro.boot.verifiedbootstate=orange` on these devices means verification is not
enforced, so a stale footer is not necessarily fatal — but a valid image is
free to produce and removes a whole class of failure.)

## Patches

| file | what |
|---|---|
| `patches/0001-defconfig-ksu.patch` | adds `CONFIG_KSU`, `CONFIG_KSU_MANUAL_HOOK` and overlayfs options |
| `patches/0002-manual-hooks.patch` | inserts `ksu_handle_*` calls into 6 kernel files behind `#ifdef CONFIG_KSU` |

Hook points (verified against `lineage-23.2`):

| file | function | hook |
|---|---|---|
| `fs/exec.c` | `__do_execve_file` | `ksu_handle_execveat_ksud`, `ksu_handle_execveat_sucompat` |
| `fs/open.c` | `SYSCALL_DEFINE3(faccessat)` | `ksu_handle_faccessat` |
| `fs/stat.c` | `vfs_statx` | `ksu_handle_stat` |
| `fs/read_write.c` | `vfs_read` | `ksu_handle_vfs_read` |
| `drivers/input/input.c` | `input_handle_event` | `ksu_handle_input_handle_event` |
| `kernel/reboot.c` | `SYSCALL_DEFINE4(reboot)` | `ksu_handle_sys_reboot` |

`kernel/reboot.c` also serves as the marker KernelSU-Next's `Kbuild` greps for
(`HAVE_KSU_HOOK`). `drivers/Makefile`, `drivers/Kconfig` and the
`drivers/kernelsu` symlink are created by `KernelSU-Next/kernel/setup.sh`.

## Scripts

| script | purpose |
|---|---|
| `extract_config.py` | pull the embedded `.config` out of a boot image's kernel |
| `apply_ksu_config.py` | apply the KernelSU delta on top of it |
| `kmake.sh` | `make` wrapper that always passes clang (see above) |
| `pin_vermagic.py` | pin `.scmversion` so the release string matches the official one |
| `patch_ksu_tree.py` | fix the 4.14 `timespec64` build break in KSU `legacy` |
| `fetch_boot.py` | download the official `boot.img` for the matching build |
| `repack_boot.py` | reassemble the boot image and re-sign AVB |
| `artifact_info.py` | read clang build id / release string from an image (CI gate) |

## Build

Push to `main`, or run the workflow manually on this branch:

* `ksu_tag` — default `legacy` (recommended). Any `*-legacy` / `1.x` tag also
  works but will be older.
* `build_ksu` — `false` builds a stock (non-root) kernel with the same
  pipeline; useful to isolate whether a problem is KSU-related.

Artifacts:

* `boot-guacamoleb-<ksu>.img` — flashable boot image
* `kernel-modules-ksu.zip` — KernelSU module with rebuilt `qca_cld3_wlan.ko` /
  `gspca_main.ko`
* `Image` — raw kernel
* `.config` + full build log

## Install

```bash
# 1. boot image (A/B device, active slot)
fastboot flash boot boot-guacamoleb-*.img

# 2. after first boot, install the modules
#    KernelSU-Next Manager -> Modules -> Install from storage -> kernel-modules-ksu.zip
#    then reboot
```

## Notes

* **KernelSU-Next Manager v3.x** is required.
* **Re-flash after every OTA.** LineageOS OTA writes the inactive slot; after
  rebooting you are on the other slot and the custom kernel is gone.
* **SELinux** stays enforcing.
* For a boot hang, `fastboot boot boot.img` boots without flashing — a crash
  there leaves no trace on the device, so it is the safe way to test.

## Verified in CI

* boot.img: 100663296 bytes, ramdisk + DTB byte-identical to the official image
* release string: `4.14.357-openela-perf-g0521dc291cf1` (identical to official)
* clang build id: `14054515` (identical to official)
* `.config` diff vs official: only the KernelSU delta
* AVB: footer + vbmeta verify successfully
* module vermagic:
  `4.14.357-openela-perf-g0521dc291cf1 SMP preempt mod_unload modversions aarch64`
