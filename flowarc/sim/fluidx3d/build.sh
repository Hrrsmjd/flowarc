#!/usr/bin/env bash
# Build FlowArc's FluidX3D binaries: fluidx3d-les (Smagorinsky) and fluidx3d-dns.
# Usage: build.sh <FluidX3D source dir> <output bin dir>
set -euo pipefail
src=$(realpath "$1"); out=$(mkdir -p "$2" && realpath "$2")
here=$(dirname "$(realpath "$0")")
# The patches below are written against FluidX3D commit dbf0bb5. Set FLOWARC_FX3D_ANY=1 to try another version.
want="12ee951dc8f19420 e22a42c13c48091e 66fd44a63bfccd6d 8a2e1641e0280eca "
have=$(cd "$src" && sha256sum src/lbm.cpp src/lbm.hpp src/kernel.cpp src/defines.hpp | cut -c1-16 | tr '\n' ' ')
[ "$have" = "$want" ] || [ "${FLOWARC_FX3D_ANY:-0}" = 1 ] || { echo "FluidX3D source is not commit dbf0bb5"; exit 1; }
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
  sed -i 's|^#define GRAPHICS_BACKGROUND_COLOR 0x000000|#define GRAPHICS_BACKGROUND_COLOR 0x22497C|' "$d"
  # Runtime Q-criterion threshold (FLOWARC_Q). FlowArc colours: navy background, grey body, teal vortices, red where the flow is fast.
  sed -i 's|to_string(GRAPHICS_Q_CRITERION)|to_string(getenv("FLOWARC_Q") ? (float)atof(getenv("FLOWARC_Q")) : GRAPHICS_Q_CRITERION)|' "$work/src/lbm.cpp"
  sed -i 's|#define COLOR_S (127<<16\|127<<8\|127)|#define COLOR_S ( 52<<16\| 56<<8\| 60)|' "$work/src/lbm.cpp"
  sed -i 's|^\t\tstd::atomic_int running_encoders = 0;|\tpublic:\n\t\tstd::atomic_int running_encoders = 0;\n\tprivate:|' "$work/src/lbm.hpp"
  k="$work/src/kernel.cpp"
  sed -i 's|^)+R(int shading(const int c|)+R(int colorscale_flowarc(float x) { return color_mix(0xE63946, 0x2A9D8F, clamp(6.0f*(x-0.75f), 0.0f, 1.0f)); }\n)+R(int shading(const int c|' "$k"
  sed -i 's|int c0=0xDFDFDF, c1=0xDFDFDF, c2=0xDFDFDF;|int c0=0x8E98A4, c1=0x8E98A4, c2=0x8E98A4;|' "$k"
  sed -i '/c[012] = colorscale_twocolor(0.5f+def_scale_F\*dot(trilinear3(p[012], Fj), normal));/d' "$k"
  sed -i 's|shading(colorscale_rainbow(def_scale_u\*length(v\([012]\)))|shading(colorscale_flowarc(def_scale_u*length(v\1))|' "$k"
  # No vortex surfaces in the two cell layers at z=0: on the moving ground they show as stripes.
  perl -0pi -e 's|(grid cell is not visible\n)(\tfloat3 uj\[ 8\];)|$1\tif(xyz.z<2u) return; // FlowArc: skip z=0 layers\n$2|' "$k"
  [ "$(grep -c "FlowArc: skip z=0 layers" "$k")" = 1 ] || { echo "ground patch failed"; exit 1; }
  # No floor plane in the picture: skip the cube layer at z=0 when drawing solid surfaces (the moving ground stays in the sim).
  sed -i 's|\(// don.t execute graphics_flags_mc() on marching-cubes halo\)$|\1\n\tif(xyz.z==0u) return; // FlowArc: no floor|' "$k"
  [ "$(grep -c "FlowArc: no floor" "$k")" = 2 ] || { echo "floor patch failed"; exit 1; }
  grep -q "colorscale_flowarc(def_scale_u" "$k" && ! grep -q "def_scale_F\*dot(trilinear3" "$k" && grep -q "52<<16" "$work/src/lbm.cpp" && grep -qPz 'public:\n\t\tstd::atomic_int running_encoders' "$work/src/lbm.hpp" || { echo "patch failed"; exit 1; }
  (cd "$work" && make Linux -j"$(nproc)" >build.log 2>&1) || { tail -30 "$work/build.log"; rm -rf "$work"; exit 1; }
  cp "$work/bin/FluidX3D" "$out/fluidx3d-$variant"
  rm -rf "$work"
done
echo "built $out/fluidx3d-les $out/fluidx3d-dns"
