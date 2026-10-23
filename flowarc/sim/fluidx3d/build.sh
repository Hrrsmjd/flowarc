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
  # Runtime Q-criterion threshold (FLOWARC_Q), FlowArc colours: dark body, teal vortices with red at high speed.
  sed -i 's|to_string(GRAPHICS_Q_CRITERION)|to_string(getenv("FLOWARC_Q") ? (float)atof(getenv("FLOWARC_Q")) : GRAPHICS_Q_CRITERION)|' "$work/src/lbm.cpp"
  sed -i 's|#define COLOR_S (127<<16\|127<<8\|127)|#define COLOR_S ( 52<<16\| 56<<8\| 60)|' "$work/src/lbm.cpp"
  sed -i 's|^\t\tstd::atomic_int running_encoders = 0;|\tpublic:\n\t\tstd::atomic_int running_encoders = 0;\n\tprivate:|' "$work/src/lbm.hpp"
  k="$work/src/kernel.cpp"
  sed -i 's|^)+R(int shading(const int c|)+R(int colorscale_flowarc(float x) { return color_mix(0xE63946, 0x2A9D8F, clamp(6.0f*(x-0.75f), 0.0f, 1.0f)); }\n)+R(int shading(const int c|' "$k"
  sed -i 's|shading(colorscale_rainbow(def_scale_u\*length(v\([012]\)))|shading(colorscale_flowarc(def_scale_u*length(v\1))|' "$k"
  grep -q "colorscale_flowarc(def_scale_u" "$k" && grep -q "52<<16" "$work/src/lbm.cpp" || { echo "patch failed"; exit 1; }
  (cd "$work" && make Linux -j"$(nproc)" >build.log 2>&1) || { tail -30 "$work/build.log"; rm -rf "$work"; exit 1; }
  cp "$work/bin/FluidX3D" "$out/fluidx3d-$variant"
  rm -rf "$work"
done
echo "built $out/fluidx3d-les $out/fluidx3d-dns"
