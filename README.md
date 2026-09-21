# guacamoleb (OnePlus 7) — LineageOS 23.2 kernel with KernelSU-Next

Builds a flashable **boot.img** for `guacamoleb` from the **LineageOS 23.2**
kernel source, with **KernelSU-Next (legacy, non-GKI, manual hooks)** compiled in,
plus the matching rebuilt kernel modules.

Status: **build verified** — kernel release string, configuration and module
vermagic all match the official LineageOS build.

---

## Why manual hooks

The sm8150 kernel (4.14.357-openela) has:

```
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
# CONFIG_KPROBES is not set        <-- the blocker
```

KernelSU-Next's default hook mode (`KSU_KPROBES_HOOK`) needs
`KPROBES + KRETPROBES + HAVE_SYSCALL_TRACEPOINTS`. Since KPROBES is disabled,
we use the **manual (in-tree) hook** mode (`KSU_MANUAL_HOOK=y`).

Also, the mainline KernelSU-Next line (>= v3.3.0) does **not** compile on 4.14:
`hook/syscall_hook.h` uses `syscall_fn_t`, which was introduced on arm64 only
in 4.19. This build pins **`v3.2.0-legacy`**.

## Why the kernel modules are shipped too

The official kernel builds the WLAN driver as a module:

```
CONFIG_QCA_CLD_WLAN=m      ->  /vendor/lib/modules/qca_cld3_wlan.ko
CONFIG_USB_GSPCA=m         ->  /vendor/lib/modules/gspca_main.ko
CONFIG_MODVERSIONS=y       ->  symbol CRCs are tied to the exact build
```

These modules are built **from the kernel tree during the ROM build**. Because
`CONFIG_MODVERSIONS=y`, the copies in `/vendor` only load against the kernel
they were built with. A custom kernel alone therefore breaks Wi-Fi
(`disagrees about version of symbol module_layout` / no WLAN) — this is the
failure described by other KernelSU builds for this SoC.

This project rebuilds the modules and ships them in a **KernelSU module zip**
that magic-mounts them over `/vendor/lib/modules`, so `/vendor` itself stays
untouched (AVB-safe).

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

Result — the built config differs from the official one *only* by the intended
KernelSU options:

```
CONFIG_KSU=y
CONFIG_KSU_MANUAL_HOOK=y
CONFIG_OVERLAY_FS_REDIRECT_DIR=y
# CONFIG_KSU_DEBUG is not set
# CONFIG_KSU_KPROBES_HOOK is not set
```

## Patches

| patch | what |
|---|---|
| `0001-defconfig-ksu.patch` | adds `CONFIG_KSU`, `CONFIG_KSU_MANUAL_HOOK` and overlayfs options |
| `0002-manual-hooks.patch` | inserts `ksu_handle_*` calls into 6 kernel files behind `#ifdef CONFIG_KSU` |

Hook points (verified against `lineage-23.2`):

| file | function | hook |
|---|---|---|
| `fs/exec.c` | `__do_execve_file` | `ksu_handle_execveat_ksud`, `ksu_handle_execveat_sucompat` |
| `fs/open.c` | `SYSCALL_DEFINE3(faccessat)` | `ksu_handle_faccessat` |
| `fs/stat.c` | `vfs_statx` | `ksu_handle_stat` |
| `fs/read_write.c` | `vfs_read` | `ksu_handle_vfs_read` |
| `drivers/input/input.c` | `input_handle_event` | `ksu_handle_input_handle_event` |
| `kernel/reboot.c` | `SYSCALL_DEFINE4(reboot)` | `ksu_handle_sys_reboot` |

`kernel/reboot.c` doubles as the marker KernelSU-Next's `Kbuild` greps for
(`HAVE_KSU_HOOK`).

`drivers/Makefile`, `drivers/Kconfig` and the `drivers/kernelsu` symlink are
created by `KernelSU-Next/kernel/setup.sh` in CI.

## Build

Push to `main` or run the workflow manually. Inputs:

* `ksu_tag` — KernelSU-Next tag. **Must be a `*-legacy` or `1.x` tag.**
  Default: `v3.2.0-legacy`.
* `build_ksu` — `false` builds a stock (non-root) kernel for comparison.

Artifacts:

* `boot-guacamoleb-<ksu>.img` — flashable boot image
* `kernel-modules-ksu.zip` — KernelSU module with the rebuilt `qca_cld3_wlan.ko`
  and `gspca_main.ko` (installed over `/vendor/lib/modules`)
* `Image` — raw kernel
* `.config` (`out.config`) and full build log

## Install

```bash
# 1. boot image (A/B device, current slot)
fastboot flash boot boot-guacamoleb-v3.2.0-legacy.img

# 2. after the first boot, install the module zip through KernelSU-Next Manager
#    (Modules -> Install from storage -> kernel-modules-ksu.zip), then reboot.
```

The module zip is **mandatory**: without the matching `qca_cld3_wlan.ko`,
Wi-Fi will not come up.

## Important notes

* **Vermagic is pinned.** `LOCALVERSION_AUTO` would append `-g<git-sha>` of the
  patched HEAD; the workflow pins the official suffix (`-g0521dc291cf1`) via
  `.scmversion` and fails the build if the release string ever diverges.
* **KernelSU Manager v3.x** is required (kernel side is `v3.2.0-legacy`).
* **Re-flash after every OTA.** LineageOS OTA updates the inactive slot; after
  rebooting you are on the other slot and the custom kernel is gone.
* **SELinux** stays enforcing.

## Verified

* boot.img: 100663296 bytes, ramdisk + DTB byte-identical to the official image,
  AVB footer preserved.
* kernel release: `4.14.357-openela-perf-g0521dc291cf1` (identical to official).
* modules vermagic:
  `4.14.357-openela-perf-g0521dc291cf1 SMP preempt mod_unload modversions aarch64`.
* `.config` diff vs official: only the KernelSU delta (7 entries).
