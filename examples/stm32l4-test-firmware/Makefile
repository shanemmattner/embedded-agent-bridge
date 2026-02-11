CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
CFLAGS  = -mcpu=cortex-m4 -mthumb -Os -Wall -ffreestanding -nostdlib
LDFLAGS = -T stm32l4.ld -nostdlib -Wl,--gc-sections

TARGET  = eab-test-firmware

all: $(TARGET).elf $(TARGET).bin

$(TARGET).elf: main.c startup.s stm32l4.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ main.c startup.s

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f $(TARGET).elf $(TARGET).bin

.PHONY: all clean
