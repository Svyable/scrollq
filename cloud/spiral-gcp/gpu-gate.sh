#!/bin/bash
# Role 2 (L4 VM, short): prove the GPU path works before any large data is staged.
# shellcheck source=common.sh disable=SC2034
source "$(dirname "$0")/common.sh"
init_role
require_state stage-env
arm_watchdog "$(mf watchdog.gpu_gate_window_minutes)" /run/scroliq-never   # this role never fits

gate driver_ready
for _ in $(seq 60); do nvidia-smi >/dev/null 2>&1 && break; sleep 10; done
nvidia-smi | tee "$EV/nvidia-smi.txt"

gate gpu_gate
BUNDLE_FILES=("$EV/gpu-gate.json")
"$CLOUD" gpu-gate --python "$VILLA_PY" --villa-root "$VILLA" --manifest "$SCROLIQ_MANIFEST" \
  --out "$EV/gpu-gate.json" >/dev/null
villa_clean

gate record
python3 -c 'import hashlib,json,sys; json.dump({"gpu_gate_sha256": hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()}, open(sys.argv[2],"w"))' \
  "$EV/gpu-gate.json" "$EV/state-extra.json"
write_state "$EV/state-extra.json"
status pass
halt_vm
