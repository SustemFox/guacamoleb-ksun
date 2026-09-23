# ROM-side logd fix

`0001-logd-skip-quoted-audit-paths.patch` is for the separate
`LineageOS/android_system_logging` checkout on branch `lineage-23.2`.
It makes `LogAudit::logDecodedPath()` skip already-quoted printable paths before
calling `HexToBytes()`. Without this guard, ordinary AVC entries such as
`path="/proc/keys"` generate `logd: HexToBytes: Invalid characters` errors.

Apply from the `android_system_logging` repository root:

```sh
git apply /path/to/0001-logd-skip-quoted-audit-paths.patch
```

This requires rebuilding/installing the ROM's `logd` component (or a ROM build
that includes it). A kernel/boot image cannot fix this userspace message. The
patch does not change SELinux policy or suppress valid AVC records.
