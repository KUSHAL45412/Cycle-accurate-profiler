// 4-element packed INT8 dot-product benchmark for CV32E40X.
#include <stdint.h>

static inline int32_t unpack_lane(uint32_t w, int i) {
    return (int32_t)(int8_t)((w >> (8 * i)) & 0xFF);
}

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

#define N 64

static uint32_t A[N];
static uint32_t B[N];

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
        uint32_t x = A[i];
        uint32_t y = B[i];
#if USE_PG_SDOT4
        register int32_t r_acc asm("a0") = acc;
        register uint32_t r_x  asm("a1") = x;
        register uint32_t r_y  asm("a2") = y;
        __asm__ volatile (
            ".word 0x52c5850b\n\t"
            : "+r"(r_acc)
            : "r"(r_x), "r"(r_y)
        );
        acc = r_acc;
#else
        acc = dot4_scalar(x, y, acc);
#endif
    }
    return acc;
}
