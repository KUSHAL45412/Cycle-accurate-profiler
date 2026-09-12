/* Multiply-accumulate kernel, used to measure the real speedup of the pg.mac
 * custom instruction against the model's prediction.
 *
 * benchmark_run() executes the accumulate loop N times. Build twice:
 *   -DUSE_PG_MAC=0  plain `mul` + `add`
 *   -DUSE_PG_MAC=1  single pg.mac offloaded over CV-X-IF
 *
 * pg.mac encoding (custom-0): funct7=0000000 funct3=000 opcode=0001011
 * Emitted with .insn so no toolchain patch is needed. rd is both a source
 * (accumulator) and the destination, which is why the core needs X_NUM_RS=3.
 */
#include <stdint.h>

#define N 1024

static int32_t va[N], vb[N];

void benchmark_init(void)
{
    for (int i = 0; i < N; i++) {
        va[i] = (i % 7) - 3;
        vb[i] = (i % 5) - 2;
    }
}

int benchmark_run(void)
{
    int32_t acc = 0;
    for (int i = 0; i < N; i++) {
        int32_t x = va[i];
        int32_t y = vb[i];
#if USE_PG_MAC
        register int32_t r_acc asm("a0") = acc;
        register int32_t r_x   asm("a1") = x;
        register int32_t r_y   asm("a2") = y;
        __asm__ volatile (
            ".word 0x50c5850b\n\t"
            : "+r"(r_acc)
            : "r"(r_x), "r"(r_y)
        );
        acc = r_acc;
#else
        acc += x * y;
#endif
    }
    return acc;
}
