#ifndef DWT_PROFILER_H
#define DWT_PROFILER_H

#include <stdint.h>

/* ARM DWT registers */
#define DWT_CTRL   (*(volatile uint32_t *)0xE0001000)
#define DWT_CYCCNT (*(volatile uint32_t *)0xE0001004)
#define DEM_CR     (*(volatile uint32_t *)0xE000EDFC)

/* Enable DWT cycle counter */
static inline void dwt_init(void) {
    DEM_CR |= (1 << 24);      /* TRCENA bit in DEMCR */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1;            /* CYCCNTENA */
}

static inline void dwt_reset(void) {
    DWT_CTRL &= ~1;           /* Disable counter */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1;            /* Re-enable counter */
    __asm volatile("dsb" ::: "memory");
    __asm volatile("isb" ::: "memory");
}

static inline uint32_t dwt_get_cycles(void) {
    __asm volatile("dsb" ::: "memory");
    return DWT_CYCCNT;
}

/* Delta-based timing — avoids reset issues on some implementations */
static inline uint32_t dwt_start(void) {
    __asm volatile("dsb" ::: "memory");
    __asm volatile("isb" ::: "memory");
    return DWT_CYCCNT;
}

static inline uint32_t dwt_stop(uint32_t start) {
    __asm volatile("dsb" ::: "memory");
    return DWT_CYCCNT - start;  /* unsigned wrap handles overflow */
}

/* Convert cycles to microseconds given CPU freq in Hz */
static inline uint32_t dwt_cycles_to_us(uint32_t cycles, uint32_t cpu_freq_hz) {
    return (uint32_t)((uint64_t)cycles * 1000000ULL / cpu_freq_hz);
}

#endif
