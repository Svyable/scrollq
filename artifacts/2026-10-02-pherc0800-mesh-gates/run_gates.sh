#!/bin/bash
# Run four pinned mesh tools over every PHerc0800 eligible mesh.
T=$TOOLS
OUT=gates800
mkdir -p $OUT
for M in elig/meshes/PHerc0800/*/; do
  m=$(basename $M)
  d=$OUT/$m; mkdir -p $d
  $T/flatcheck report $M --json $d/flatcheck.json > $d/flatcheck.log 2>&1; fe=$?
  $T/tifxyz-doctor audit $M --json $d/tifxyz-doctor.json > $d/tifxyz-doctor.log 2>&1; de=$?
  $T/tifxyz-repair validate --json $M > $d/tifxyz-repair.json 2> $d/tifxyz-repair.err; re=$?
  $T/windcheck check $M --out $d/windcheck > $d/windcheck.log 2>&1; we=$?
  echo "$m flatcheck=$fe doctor=$de repair=$re windcheck=$we"
done
echo DONE
