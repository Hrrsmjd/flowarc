#!/usr/bin/env bash
# Build FlowArc's FluidX3D binaries: fluidx3d-les (Smagorinsky) and fluidx3d-dns.
# Usage: build.sh <FluidX3D source dir> <output bin dir>
set -euo pipefail
src=$(realpath "$1"); out=$(mkdir -p "$2" && realpath "$2")
here=$(dirname "$(realpath "$0")")
for variant in les dns; do
  work=$(mktemp -d "$out/build-XXXX")
  cp -r "$src/src" "$src/makefile" "$src/make.sh" "$work/"
  cp "$here/setup.cpp" "$work/src/setup.cpp"
  d="$work/src/defines.hpp"
  sed -i 's|^#define BENCHMARK|//#define BENCHMARK|' "$d"
  for flag in FP16S FORCE_FIELD EQUILIBRIUM_BOUNDARIES MOVING_BOUNDARIES GRAPHICS; do
    sed -i "s|^//#define $flag |#define $flag |" "$d"
  done
  [ "$variant" = les ] && sed -i 's|^//#define SUBGRID |#define SUBGRID |' "$d"
  sed -i 's|^#define GRAPHICS_BACKGROUND_COLOR 0x000000|#define GRAPHICS_BACKGROUND_COLOR 0xF3EFE6|' "$d"
  (cd "$work" && make Linux -j"$(nproc)" >build.log 2>&1) || { tail -30 "$work/build.log"; exit 1; }
  cp "$work/bin/FluidX3D" "$out/fluidx3d-$variant"
  rm -rf "$work"
done
echo "built $out/fluidx3d-les $out/fluidx3d-dns"
