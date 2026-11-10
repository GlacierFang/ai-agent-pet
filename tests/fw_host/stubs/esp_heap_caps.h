#pragma once
#include <stddef.h>
#include <stdint.h>
#define MALLOC_CAP_SPIRAM (1<<11)
#define MALLOC_CAP_8BIT (1<<2)
void *heap_caps_malloc(size_t n, uint32_t caps);
void *heap_caps_aligned_alloc(size_t align, size_t n, uint32_t caps);
