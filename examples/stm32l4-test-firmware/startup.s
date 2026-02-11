/* Minimal startup for STM32L4 (Cortex-M4) */
.syntax unified
.cpu cortex-m4
.thumb

.section .isr_vector, "a"
.global _vectors
_vectors:
    .word _estack          /* Initial stack pointer */
    .word Reset_Handler    /* Reset */
    .word 0                /* NMI */
    .word HardFault_Handler
    .fill 12, 4, 0        /* MemManage..SVCall */
    .word 0                /* Debug */
    .word 0                /* Reserved */
    .word 0                /* PendSV */
    .word 0                /* SysTick */

.section .text
.global Reset_Handler
.type Reset_Handler, %function
Reset_Handler:
    /* Zero BSS */
    ldr r0, =_sbss
    ldr r1, =_ebss
    movs r2, #0
1:  cmp r0, r1
    bge 2f
    str r2, [r0], #4
    b 1b
2:
    bl main
    b .

.global HardFault_Handler
.type HardFault_Handler, %function
HardFault_Handler:
    b .
