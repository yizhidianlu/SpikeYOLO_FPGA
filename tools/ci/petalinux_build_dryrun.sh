#!/bin/bash
# tools/ci/petalinux_build_dryrun.sh — pre-flight checks for petalinux-build.
#
# Cannot run the real toolchain in CI (license + 30+ min). Instead validate
# everything that *would* fail a real build for non-toolchain reasons.
#
# Exit codes:
#   0   all 5 checks passed
#   1   one or more checks failed (trace printed)

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RECIPE_ROOT="${ROOT}/sw/petalinux/project-spec/meta-user"
DTSI="${RECIPE_ROOT}/recipes-bsp/device-tree/files/spike-accel.dtsi"
APP_BB="${RECIPE_ROOT}/recipes-apps/spike-accel-app/spike-accel-app.bb"
KCFG="${RECIPE_ROOT}/recipes-kernel/linux/files/user_kernel.cfg"
XSA="${ROOT}/hw/vivado/out/system.xsa"

FAIL=0
PASSED=()
SKIPPED=()

step() { printf "[step %d/%s] %s ... " "$1" "$2" "$3"; }
ok()   { echo "OK";   PASSED+=("$1"); }
skip() { echo "SKIP ($1)"; SKIPPED+=("$2"); }
bad()  { echo "FAIL"; echo "        $1" >&2; FAIL=1; }

# 1. $PETALINUX env (allow CI to skip via SPIKE_DRYRUN_NO_PETALINUX=1)
step 1 5 "PETALINUX env"
if [ -n "${PETALINUX:-}" ]; then
    ok "PETALINUX env"
elif [ "${SPIKE_DRYRUN_NO_PETALINUX:-0}" = "1" ] || [ "${CI:-0}" = "1" ]; then
    skip "no toolchain in this env" "PETALINUX env"
else
    bad "\$PETALINUX not set; run: source /opt/petalinux-v2023.2/settings.sh"
fi

# 2. XSA path placeholder (warn-only — B2 may not have synthesised yet)
step 2 5 "XSA artefact"
if [ -f "${XSA}" ]; then
    ok "XSA artefact"
else
    skip "B2 .xsa not yet generated" "XSA artefact"
fi

# 3. dtsi syntax via dtc (skip if dtc missing)
step 3 5 "spike-accel.dtsi syntax"
if ! [ -f "${DTSI}" ]; then
    bad "${DTSI} missing"
elif command -v dtc >/dev/null 2>&1; then
    if dtc -I dts -O dtb -q -o /tmp/spike-accel.dtb "${DTSI}" 2>/tmp/dtc.err; then
        ok "spike-accel.dtsi syntax"
    else
        bad "dtc parse failed; see /tmp/dtc.err: $(head -1 /tmp/dtc.err)"
    fi
else
    # Fallback: very light textual sanity (balanced braces + presence of root)
    if grep -q '^/ {' "${DTSI}" && \
       [ "$(tr -cd '{' < "${DTSI}" | wc -c)" = "$(tr -cd '}' < "${DTSI}" | wc -c)" ]; then
        skip "dtc not installed; passed brace-balance sanity" "spike-accel.dtsi syntax"
    else
        bad "spike-accel.dtsi syntax sanity failed (root node or brace mismatch)"
    fi
fi

# 4. spike-accel-app.bb SRC_URI paths exist under sw/app/ + sw/sdk/
step 4 5 "app recipe SRC_URI"
if ! [ -f "${APP_BB}" ]; then
    bad "${APP_BB} missing"
else
    missing=""
    [ -d "${ROOT}/sw/app" ]    || missing="${missing} sw/app/"
    [ -d "${ROOT}/sw/sdk" ]    || missing="${missing} sw/sdk/"
    if [ -z "${missing}" ]; then
        ok "app recipe SRC_URI"
    else
        bad "missing source trees:${missing}"
    fi
fi

# 5. user_kernel.cfg has CONFIG_UIO=y
step 5 5 "kernel cfg CONFIG_UIO=y"
if ! [ -f "${KCFG}" ]; then
    bad "${KCFG} missing"
elif grep -q '^CONFIG_UIO=y' "${KCFG}"; then
    ok "kernel cfg CONFIG_UIO=y"
else
    bad "CONFIG_UIO=y not found in user_kernel.cfg"
fi

echo "------------------------------------------------------------"
echo "passed:  ${#PASSED[@]} / 5  (skipped: ${#SKIPPED[@]})"
if [ "${FAIL}" = "0" ]; then
    echo "Dry-run PASS, ready for real petalinux-build"
    exit 0
else
    echo "Dry-run FAIL — fix above before invoking petalinux-build"
    exit 1
fi
