#pragma once
#include <stddef.h>
void *malloc(size_t); void *realloc(void *, size_t); void free(void *);
void qsort(void *, size_t, size_t, int (*)(const void *, const void *));
char *getenv(const char *);
void arc4random_buf(void *, size_t);
unsigned long strtoul(const char *, char **, int);
