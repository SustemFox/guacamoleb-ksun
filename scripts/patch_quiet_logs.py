#!/usr/bin/env python3
"""
Reduce vendor log noise on the OnePlus 7 (sm8150) kernel.

The LineageOS sm8150 tree contains several Oplus/Qualcomm drivers that log
purely informational values through pr_err()/printk(KERN_ERR), so they are
re-emitted by logd at ERROR level on every touch, vibration or charging poll.
That floods the kernel ring buffer and /dev/kmsg, and costs CPU in the printk
path (and in logd) during interaction.

This script demotes or silences ONLY clear debug messages; it never touches a
message that reports an actual failure. Each rule is a plain string
replacement, applied idempotently, and any rule whose pattern is missing is
reported (the upstream source may have changed) without failing the build.

Rules (see the log evidence they target):

  qti-haptics.c
    "vmax_mv = %d" and "haptic val[0]=...": printed on every vibration via
    dev_err(), no diagnostic value. -> dev_dbg() (compiled out by default).

  oplus_charger.c
    " fastchg status[...] charger info[...]" + oplus_vooc_print_log(): the
    periodic fast-charge state dump in oplus_check_afi_update_condition().
    "[%s] will (not) call oplus_gauge_protect_check": per-poll printk(KERN_ERR).
    "batt_temp=...shell_temp=...chging_temp=...": per-poll charger_xlog_printk.
    oplus_chg_print_log(chip): full charger/gauge register dump every cycle.
    All are gated with `if (0)` (the call stays referenced, so no
    -Wunused-function warning).

  oplus_short.c
    "invalid parameters": logged whenever the short-C algorithm parameters are
    not yet valid, which is a normal transient at boot/plug-in.

  oplus_vooc.c
    oplus_vooc_print_log() body: same periodic VOOC state dump.

Usage:
    patch_quiet_logs.py <kernel-dir>
"""
import os
import sys

# (relative path, old, new)
RULES = [
    # --- haptics: per-vibration debug at KERN_ERR -------------------------
    (
        'drivers/input/misc/qti-haptics.c',
        'dev_err(chip->dev, "vmax_mv = %d", vmax_mv);',
        'dev_dbg(chip->dev, "vmax_mv = %d", vmax_mv);',
    ),
    (
        'drivers/input/misc/qti-haptics.c',
        'dev_err(chip->dev, "haptic val[0]=0x%x,val[1]=0x%x",val[0],val[1]);',
        'dev_dbg(chip->dev, "haptic val[0]=0x%x,val[1]=0x%x",val[0],val[1]);',
    ),

    # --- oplus charger: periodic state dumps ------------------------------
    # oplus_check_afi_update_condition(): VOOC dump + fastchg status line
    (
        'drivers/power/oplus/oplus_charger.c',
        '\toplus_vooc_print_log();\n\tchg_err(" fastchg status[%d %d %d %d %d] charger info[%d %d %d %d %d]\\n",',
        '\tif (0) oplus_vooc_print_log();\n\tif (0) chg_err(" fastchg status[%d %d %d %d %d] charger info[%d %d %d %d %d]\\n",',
    ),
    # oplus_chg_get_battery_data(): "will (not) call ..." at KERN_ERR
    (
        'drivers/power/oplus/oplus_charger.c',
        'printk(KERN_ERR "[%s] will',
        'if (0) printk(KERN_ERR "[%s] will',
    ),
    # oplus_chg_match_temp_for_chging(): per-poll temperature line
    (
        'drivers/power/oplus/oplus_charger.c',
        'charger_xlog_printk(CHG_LOG_CRTI, "batt_temp=%d,shell_temp=%d,chging_temp=%d\\n",',
        'if (0) charger_xlog_printk(CHG_LOG_CRTI, "batt_temp=%d,shell_temp=%d,chging_temp=%d\\n",',
    ),
    # oplus_chg_other_thing(): full charger/gauge register dump each cycle
    (
        'drivers/power/oplus/oplus_charger.c',
        '\toplus_chg_print_log(chip);\n',
        '\tif (0) oplus_chg_print_log(chip);\n',
    ),

    # --- oplus short-C: transient "invalid parameters" --------------------
    (
        'drivers/power/oplus/oplus_short.c',
        'chg_err("invalid parameters\\n");',
        'if (0) chg_err("invalid parameters\\n");',
    ),

    # --- oplus VOOC: periodic VOOC state dump -----------------------------
    (
        'drivers/power/oplus/oplus_vooc.c',
        'vooc_xlog_printk(CHG_LOG_CRTI, "VOOC[ %d / %d / %d / %d / %d / %d]\\n",',
        'if (0) vooc_xlog_printk(CHG_LOG_CRTI, "VOOC[ %d / %d / %d / %d / %d / %d]\\n",',
    ),

    # --- sched_clock: unconditional pr_info on EVERY suspend/resume -------
    # kernel/time/sched_clock.c prints two lines per system suspend even in
    # production, so any suspend/resume burst floods the ring buffer. These
    # are pure diagnostics (epoch ns/cycles), so demote them to pr_debug.
    (
        'kernel/time/sched_clock.c',
        'pr_info("suspend ns:%17llu',
        'pr_debug("suspend ns:%17llu',
    ),
    (
        'kernel/time/sched_clock.c',
        'pr_info("resume cycles:%17llu\\n"',
        'pr_debug("resume cycles:%17llu\\n"',
    ),
]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    root = sys.argv[1]
    if not os.path.isdir(os.path.join(root, 'drivers')):
        print('patch_quiet_logs: %s does not look like a kernel tree' % root,
              file=sys.stderr)
        return 1

    applied = 0
    missing = 0
    for rel, old, new in RULES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print('patch_quiet_logs: WARNING: %s not found, skipping' % rel,
                  file=sys.stderr)
            missing += 1
            continue
        src = open(path, encoding='utf-8', errors='replace').read()
        if new in src and old not in src:
            print('patch_quiet_logs: already quiet: %s :: %s'
                  % (rel, old.split('(')[0]))
            continue
        n = src.count(old)
        if n == 0:
            print('patch_quiet_logs: WARNING: pattern not found in %s: %r'
                  % (rel, old[:60]), file=sys.stderr)
            missing += 1
            continue
        src = src.replace(old, new)
        open(path, 'w', encoding='utf-8').write(src)
        print('patch_quiet_logs: silenced %d site(s) in %s' % (n, rel))
        applied += n

    print('patch_quiet_logs: done, %d site(s) silenced, %d rule(s) unmatched'
          % (applied, missing))
    # Do not fail the build: an unmatched rule only means we did not quiet one
    # message, never that the kernel is broken.
    return 0


if __name__ == '__main__':
    sys.exit(main())
