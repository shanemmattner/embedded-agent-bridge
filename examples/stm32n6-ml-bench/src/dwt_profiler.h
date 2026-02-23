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
    DWT_CYCCNT = 0;
}

static inline uint32_t dwt_get_cycles(void) {
    return DWT_CYCCNT;
}

/* Convert cycles to microseconds given CPU freq in Hz */
static inline uint32_t dwt_cycles_to_us(uint32_t cycles, uint32_t cpu_freq_hz) {
    return (uint32_t)((uint64_t)cycles * 1000000ULL / cpu_freq_hz);
}

#endif
