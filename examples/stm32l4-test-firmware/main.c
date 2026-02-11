/* Minimal STM32L4 test firmware for EAB regression testing.
 * Blinks PA5 (Nucleo-L476RG user LED) and outputs UART2 heartbeats.
 * UART2: PA2 (TX), PA3 (RX) — ST-Link VCP on Nucleo boards.
 */

#include <stdint.h>

/* Register addresses */
#define RCC_BASE      0x40021000
#define RCC_AHB2ENR   (*(volatile uint32_t *)(RCC_BASE + 0x4C))
#define RCC_APB1ENR1  (*(volatile uint32_t *)(RCC_BASE + 0x58))

#define GPIOA_BASE    0x48000000
#define GPIOA_MODER   (*(volatile uint32_t *)(GPIOA_BASE + 0x00))
#define GPIOA_ODR     (*(volatile uint32_t *)(GPIOA_BASE + 0x14))
#define GPIOA_AFRL    (*(volatile uint32_t *)(GPIOA_BASE + 0x20))

#define USART2_BASE   0x40004400
#define USART2_CR1    (*(volatile uint32_t *)(USART2_BASE + 0x00))
#define USART2_BRR    (*(volatile uint32_t *)(USART2_BASE + 0x0C))
#define USART2_ISR    (*(volatile uint32_t *)(USART2_BASE + 0x1C))
#define USART2_TDR    (*(volatile uint32_t *)(USART2_BASE + 0x28))

static void uart_putc(char c) {
    while (!(USART2_ISR & (1 << 7)))  /* TXE */
        ;
    USART2_TDR = (uint8_t)c;
}

static void uart_puts(const char *s) {
    while (*s)
        uart_putc(*s++);
}

static void delay(volatile uint32_t n) {
    while (n--)
        ;
}

void main(void) {
    /* Enable GPIOA + USART2 clocks */
    RCC_AHB2ENR  |= (1 << 0);   /* GPIOAEN */
    RCC_APB1ENR1 |= (1 << 17);  /* USART2EN */

    /* PA5 = output (LED) */
    GPIOA_MODER &= ~(3 << 10);
    GPIOA_MODER |=  (1 << 10);

    /* PA2 = AF7 (USART2_TX), PA3 = AF7 (USART2_RX) */
    GPIOA_MODER &= ~((3 << 4) | (3 << 6));
    GPIOA_MODER |=  ((2 << 4) | (2 << 6));
    GPIOA_AFRL  &= ~((0xF << 8) | (0xF << 12));
    GPIOA_AFRL  |=  ((7 << 8) | (7 << 12));

    /* USART2: 115200 baud @ 4 MHz MSI default clock */
    USART2_BRR = 35;  /* 4000000 / 115200 ≈ 35 */
    USART2_CR1 = (1 << 0) | (1 << 3);  /* UE + TE */

    uart_puts("[EAB-TEST] STM32L4 firmware booted\r\n");

    uint32_t count = 0;
    for (;;) {
        GPIOA_ODR ^= (1 << 5);  /* Toggle LED */
        count++;

        /* Print heartbeat every toggle */
        uart_puts("[EAB-TEST] heartbeat ");

        /* Simple decimal print */
        char buf[12];
        int i = 0;
        uint32_t n = count;
        if (n == 0) buf[i++] = '0';
        else {
            char tmp[12];
            int j = 0;
            while (n > 0) { tmp[j++] = '0' + (n % 10); n /= 10; }
            while (j > 0) buf[i++] = tmp[--j];
        }
        buf[i] = '\0';
        uart_puts(buf);
        uart_puts("\r\n");

        delay(400000);
    }
}
