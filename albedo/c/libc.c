// Мала libc для SQLite у модулі (Альбедо): лише чисті обчислення. malloc — у src/lib.rs; memcpy й математика — із compiler_builtins.
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

int strcmp(const char *a, const char *b) { while (*a && *a == *b) a++, b++; return *(unsigned char *)a - *(unsigned char *)b; }
int strncmp(const char *a, const char *b, size_t n) {
  for (; n; n--, a++, b++) { if (*a != *b) return *(unsigned char *)a - *(unsigned char *)b; if (!*a) return 0; }
  return 0;
}
char *strchr(const char *s, int c) { for (;; s++) { if (*s == (char)c) return (char *)s; if (!*s) return 0; } }
char *strrchr(const char *s, int c) { const char *r = 0; for (;; s++) { if (*s == (char)c) r = s; if (!*s) return (char *)r; } }
size_t strcspn(const char *s, const char *rej) { size_t n = 0; while (s[n] && !strchr(rej, s[n])) n++; return n; }
size_t strspn(const char *s, const char *acc) { size_t n = 0; while (s[n] && strchr(acc, s[n])) n++; return n; }
void *memchr(const void *p, int c, size_t n) { const unsigned char *s = p; for (; n; n--, s++) if (*s == (unsigned char)c) return (void *)s; return 0; }

// expat: ентропію для хешів дає господар; змінних середовища в модулі немає, налагоджувальний друк нікуди не йде
#include <stdio.h>
__attribute__((import_module("ngr"), import_name("random"))) extern void ngr_random(void *p, int n);
void arc4random_buf(void *p, size_t n) { ngr_random(p, (int)n); }
char *getenv(const char *n) { return 0; }
int errno;
unsigned long strtoul(const char *s, char **e, int b) { if (e) *e = (char *)s; return 0; }  // лише для змінних середовища, яких немає
FILE *stderr;
int fprintf(FILE *f, const char *s, ...) { return 0; }
int fputs(const char *s, FILE *f) { return 0; }                  // на них clang сам перетворює прості fprintf
int fputc(int c, FILE *f) { return c; }
size_t fwrite(const void *p, size_t s, size_t n, FILE *f) { return n; }

// купа: сталий час без рекурсії й без памʼяті
static void sw(char *a, char *b, size_t w) { while (w--) { char t = *a; *a++ = *b; *b++ = t; } }
void qsort(void *base, size_t n, size_t w, int (*cmp)(const void *, const void *)) {
  char *b = base;
  for (size_t start = n / 2, end = n; end > 1;) {
    if (start > 0) start--; else { end--; sw(b, b + end * w, w); }
    for (size_t r = start;;) {
      size_t c = 2 * r + 1;
      if (c >= end) break;
      if (c + 1 < end && cmp(b + c * w, b + (c + 1) * w) < 0) c++;
      if (cmp(b + r * w, b + c * w) >= 0) break;
      sw(b + r * w, b + c * w, w); r = c;
    }
  }
}

// математика SQLite, якої немає в compiler_builtins (atanh — ніколи; acosh, asinh — з Rust 1.9x для wasm32 теж: модуль
// просив їх у господаря, ПК 2026-11-07); алгоритми — як у musl, тож модуль не залежить від версії Rust
double log1p(double); double log(double); double sqrt(double);
double acosh(double x) {
  union { double f; unsigned long long i; } u = { x };
  unsigned e = u.i >> 52 & 0x7ff;
  if (e < 0x3ff + 1) return log1p(x - 1 + sqrt((x - 1) * (x - 1) + 2 * (x - 1)));   // |x| < 2
  if (e < 0x3ff + 26) return log(2 * x - 1 / (x + sqrt(x * x - 1)));                 // |x| < 2^26
  return log(x) + 0.693147180559945309417232121458176568;                           // |x| >= 2^26, nan
}
double asinh(double x) {
  union { double f; unsigned long long i; } u = { x };
  unsigned e = u.i >> 52 & 0x7ff, neg = u.i >> 63;
  u.i &= ~0ULL >> 1;
  double y = u.f;
  if (e >= 0x3ff + 26) y = log(y) + 0.693147180559945309417232121458176568;          // |x| >= 2^26, inf, nan
  else if (e >= 0x3ff + 1) y = log(2 * y + 1 / (sqrt(y * y + 1) + y));               // |x| >= 2
  else if (e >= 0x3ff - 26) y = log1p(y + y * y / (sqrt(y * y + 1) + 1));            // |x| >= 2^-26
  return neg ? -y : y;
}
double atanh(double x) {
  union { double f; unsigned long long i; } u = { x };
  unsigned e = u.i >> 52 & 0x7ff, neg = u.i >> 63;
  u.i &= ~0ULL >> 1;
  double y = u.f;
  if (e < 0x3ff - 1) { if (e >= 0x3ff - 32) y = 0.5 * log1p(2 * y + 2 * y * y / (1 - y)); }
  else y = 0.5 * log1p(2 * (y / (1 - y)));
  return neg ? -y : y;
}
