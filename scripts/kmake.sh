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
set -euo pipefail

: "${CLANG_DIR:?CLANG_DIR not set}"
: "${GCC64_DIR:?GCC64_DIR not set}"
: "${GCC32_DIR:?GCC32_DIR not set}"

exec make "$@" \
  O=out ARCH=arm64 \
  CC="$CLANG_DIR/bin/clang" \
  CLANG_TRIPLE=aarch64-linux-gnu- \
  CROSS_COMPILE="$GCC64_DIR/bin/aarch64-linux-android-" \
  CROSS_COMPILE_ARM32="$GCC32_DIR/bin/arm-linux-androideabi-" \
  LD="$CLANG_DIR/bin/ld.lld" \
  AR="$CLANG_DIR/bin/llvm-ar" \
  NM="$CLANG_DIR/bin/llvm-nm" \
  OBJCOPY="$CLANG_DIR/bin/llvm-objcopy" \
  OBJDUMP="$CLANG_DIR/bin/llvm-objdump" \
  STRIP="$CLANG_DIR/bin/llvm-strip"
