#!/usr/bin/env bash
# Wrapper around `make` for the sm8150 kernel.
#
# The kernel Makefile has a `check-clang-specific-options` rule that DISABLES
# clang-only options when cc-name != clang:
#
#     clang-specific-configs := LTO_CLANG CFI_CLANG SHADOW_CALL_STACK INIT_STACK_ALL_ZERO
#
# This rule fires on *every* make invocation (it is a prerequisite of
# include/config/auto.conf.cmd), so a single bare `make kernelrelease` — which
# defaults CC to $(CROSS_COMPILE)gcc — silently rewrites .config and drops LTO,
# THINLTO, the shadow call stack and stack auto-init. Always go through this
# wrapper so clang is used everywhere.
#
# The official guacamoleb device tree sets TARGET_KERNEL_NO_GCC := true, so the
# whole build is LLVM (LLVM=1 LLVM_IAS=1) and the CROSS_COMPILE prefixes are
# target identifiers only — no GCC binaries are on PATH. Mixing the GCC cross
# toolchain in produced a kernel that did not boot.
set -euo pipefail

: "${CLANG_DIR:?CLANG_DIR not set}"

exec make "$@" \
  O=out ARCH=arm64 LLVM=1 LLVM_IAS=1 \
  CC="$CLANG_DIR/bin/clang" \
  CLANG_TRIPLE=aarch64-linux-gnu- \
  CROSS_COMPILE=aarch64-linux-gnu- \
  CROSS_COMPILE_ARM32=arm-linux-gnueabi-