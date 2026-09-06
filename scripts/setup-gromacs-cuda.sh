#!/usr/bin/env bash
# Build GROMACS with CUDA and native SIMD, inside WSL.
#
# Ubuntu's packaged gromacs is built with GPU support disabled and SIMD pinned
# to SSE4.1 for portability. On an Ampere laptop card that is roughly an order
# of magnitude off what the hardware can do — no GPU offload at all, and half
# the CPU throughput. Fine for building and minimising a system, not for
# production trajectories. So we build our own.
#
#   bash scripts/setup-gromacs-cuda.sh
#
# Installs to $PREFIX (default ~/opt/gromacs). Source it afterwards:
#   source ~/opt/gromacs/bin/GMXRC

set -euo pipefail

GROMACS_VERSION="${GROMACS_VERSION:-2025.2}"
PREFIX="${PREFIX:-$HOME/opt/gromacs}"
BUILD_DIR="${BUILD_DIR:-$HOME/.cache/vervain/gromacs-build}"
JOBS="${JOBS:-$(nproc)}"

# Ampere. sm_86 is the RTX 3060; keep the list short so nvcc does not spend
# twenty minutes generating code for architectures this machine cannot run.
CUDA_ARCH="${CUDA_ARCH:-86}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "prerequisites"
sudo -n apt-get update -qq
sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  build-essential cmake ninja-build wget nvidia-cuda-toolkit


# nvcc refuses host compilers newer than it knows about, and distributions ship
# a gcc well ahead of the CUDA toolkit. CUDA 12.4 caps at gcc 13; Ubuntu 26.04
# defaults to gcc 15. Pin the whole build rather than only the device code --
# mixing compilers across the CUDA boundary is an ABI problem waiting to happen,
# and the failure surfaces at run time, not at link time.
if [[ -z "${HOST_CC:-}" ]]; then
  for v in 13 12 11; do
    if command -v "gcc-$v" >/dev/null && command -v "g++-$v" >/dev/null; then
      HOST_CC="$(command -v "gcc-$v")"
      HOST_CXX="$(command -v "g++-$v")"
      break
    fi
  done
fi
if [[ -z "${HOST_CC:-}" ]]; then
  echo "No CUDA-compatible gcc found. Install one:" >&2
  echo "    sudo apt-get install -y gcc-13 g++-13" >&2
  exit 1
fi

say "toolchain"
cmake --version | head -1
nvcc --version | tail -2
echo "host compiler: $HOST_CXX ($("$HOST_CXX" -dumpversion))"

say "fetching gromacs ${GROMACS_VERSION}"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
tarball="gromacs-${GROMACS_VERSION}.tar.gz"
if [[ ! -f "$tarball" ]]; then
  wget -q --show-progress "https://ftp.gromacs.org/gromacs/${tarball}"
fi
if [[ ! -d "gromacs-${GROMACS_VERSION}" ]]; then
  tar xf "$tarball"
fi

say "configuring"
cd "gromacs-${GROMACS_VERSION}"
mkdir -p build
cd build
cmake .. -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$HOST_CC" \
  -DCMAKE_CXX_COMPILER="$HOST_CXX" \
  -DCMAKE_CUDA_HOST_COMPILER="$HOST_CXX" \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DGMX_GPU=CUDA \
  -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
  -DGMX_SIMD=AVX2_256 \
  -DGMX_BUILD_OWN_FFTW=ON \
  -DGMX_MPI=OFF \
  -DGMX_OPENMP=ON \
  -DGMX_DOUBLE=OFF \
  -DBUILD_TESTING=OFF

say "building with ${JOBS} jobs (this is the long part)"
ninja -j "$JOBS"

say "installing to ${PREFIX}"
ninja install

say "done"
"$PREFIX/bin/gmx" --version | grep -iE 'GROMACS version|GPU support|SIMD instructions|CUDA'
cat <<EOF

Add this to your shell profile:

    source ${PREFIX}/bin/GMXRC

The packaged /usr/bin/gmx stays where it is; GMXRC puts this build ahead of it
on PATH for the current shell.
EOF
