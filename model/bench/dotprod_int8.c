// dotprod_int8.c
//
// Scalar baseline for a 4-element INT8 dot product, packed 4-per-word:
//     acc += A0*B0 + A1*B1 + A2*B2 + A3*B3
//
// This is the sequence pg.sdot4 is meant to replace. Two packed 32-bit words
// (4 signed INT8 lanes each) are unpacked with shifts+masks, multiplied, and
// accumulated -- the 16-20 instruction pattern described in the design doc.
//
// Matches harness.c's benchmark_init()/benchmark_run() convention: the
// harness itself brackets benchmark_run() with rdcycle() and calls report(),
// so this file must NOT define main() or call rdcycle() itself.
//
// Build (from model/bench/):
//   ./build.sh dotprod_int8
//
// Then:
//   cd ../.. && ./profile.sh dotprod_int8
//   ./model/find_candidates.py ~/Storage/riscv/demo/profiler/spike.txt \
//       --max-len 20 --num-rs 3 --allow-mem --core 40x

#include <stdint.h>

// Extract INT8 lane `i` (0..3) from a packed 32-bit word, sign-extended.
static inline int32_t unpack_lane(uint32_t w, int i) {
    return (int32_t)(int8_t)((w >> (8 * i)) & 0xFF);
}

// One 4-wide INT8 dot product accumulated into acc, done the scalar way:
// this is exactly the sequence pg.sdot4 is meant to fuse.
__attribute__((always_inline))
static inline int32_t dot4_scalar(uint32_t a_packed, uint32_t b_packed, int32_t acc) {
    int32_t a0 = unpack_lane(a_packed, 0);
    int32_t a1 = unpack_lane(a_packed, 1);
    int32_t a2 = unpack_lane(a_packed, 2);
    int32_t a3 = unpack_lane(a_packed, 3);

    int32_t b0 = unpack_lane(b_packed, 0);
    int32_t b1 = unpack_lane(b_packed, 1);
    int32_t b2 = unpack_lane(b_packed, 2);
    int32_t b3 = unpack_lane(b_packed, 3);

    acc += a0 * b0;
    acc += a1 * b1;
    acc += a2 * b2;
    acc += a3 * b3;

    return acc;
}

// Packed INT8 test vectors: a small quantized-kernel-like sequence.
#define N 64

static uint32_t A[N];
static uint32_t B[N];

// Fixed seed patterns, replicated across N so find_candidates.py sees a
// repeated dot4_scalar pattern with a real "execs" count.
static const uint32_t A_SEED[8] = {
    0x01020304, 0x7F010203, 0x80FF0102, 0x03040506,
    0x0A0B0C0D, 0x11121314, 0x21222324, 0x31323334,
};
static const uint32_t B_SEED[8] = {
    0x04030201, 0x0201017F, 0x020100FF, 0x06050403,
    0x0D0C0B0A, 0x14131211, 0x24232221, 0x34333231,
};

static int32_t acc;

void benchmark_init(void) {
    for (int i = 0; i < N; i++) {
        A[i] = A_SEED[i % 8];
        B[i] = B_SEED[i % 8];
    }
    acc = 0;
}

int benchmark_run(void) {
    for (int i = 0; i < N; i++) {
        acc = dot4_scalar(A[i], B[i], acc);
    }
    return acc;
}
