#pragma once
#include <stddef.h>
typedef struct NgrFile FILE;
extern FILE *stderr;
int fprintf(FILE *, const char *, ...);
