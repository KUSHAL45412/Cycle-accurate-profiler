/* Minimal freestanding libc subset: the Embench kernels use a handful of
   string.h routines, and we build with -nostdlib. */
#include <stddef.h>

void *memset(void *d, int c, size_t n)
{ unsigned char *p = d; while (n--) *p++ = (unsigned char)c; return d; }

void *memcpy(void *d, const void *s, size_t n)
{ unsigned char *p = d; const unsigned char *q = s; while (n--) *p++ = *q++; return d; }

void *memmove(void *d, const void *s, size_t n)
{
    unsigned char *p = (unsigned char *)d;
    const unsigned char *q = (const unsigned char *)s;
    if (p < q) {
        while (n--) *p++ = *q++;
    } else if (p > q) {
        p += n;
        q += n;
        while (n--) *--p = *--q;
    }
    return d;
}

int memcmp(const void *a, const void *b, size_t n)
{ const unsigned char *x = a, *y = b; while (n--) { if (*x != *y) return *x - *y; x++; y++; } return 0; }

size_t strlen(const char *s) { const char *p = s; while (*p) p++; return (size_t)(p - s); }

char *strchr(const char *s, int c)
{
    while (*s != (char)c) {
        if (!*s++) return NULL;
    }
    return (char *)s;
}

void abort(void) { while (1) {} }
void exit(int status) { (void)status; while (1) {} }

double sqrt(double x) {
    if (x <= 0.0) return 0.0;
    double guess = x / 2.0;
    for (int i = 0; i < 20; i++) {
        guess = 0.5 * (guess + x / guess);
    }
    return guess;
}

