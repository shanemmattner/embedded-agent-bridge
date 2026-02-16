# C2000 Stress Test Makefile
# Build firmware using TI C2000 compiler directly

# Compiler paths
CC := /Applications/ti/ccs2041/ccs/tools/compiler/ti-cgt-c2000_22.6.3.LTS/bin/cl2000
AR := /Applications/ti/ccs2041/ccs/tools/compiler/ti-cgt-c2000_22.6.3.LTS/bin/ar2000
GMAKE := /Applications/ti/ccs2041/ccs/utils/bin/gmake

# C2000Ware paths
C2000WARE_ROOT := /tmp/c2000ware-core-sdk
DRIVERLIB_ROOT := $(C2000WARE_ROOT)/driverlib/f28003x/driverlib
DEVICE_SUPPORT := $(C2000WARE_ROOT)/device_support/f28003x

# Project settings
PROJECT := launchxl_ex1_f280039c_demo
BUILD_DIR := Debug
OUTPUT := $(BUILD_DIR)/$(PROJECT).out

# Source files (local sources only - device files compiled separately)
LOCAL_SRCS := main.c launchxl_ex1_sci_io_driverlib.c
DEVICE_SRCS := $(DEVICE_SUPPORT)/common/source/device.c
ASM_SRCS := $(DEVICE_SUPPORT)/common/source/f28003x_codestartbranch.asm

# Include paths
COMPILER_INCLUDE := /Applications/ti/ccs2041/ccs/tools/compiler/ti-cgt-c2000_22.6.3.LTS/include
INCLUDES := -I. \
            -I$(DEVICE_SUPPORT)/common/include \
            -I$(C2000WARE_ROOT)/driverlib/f28003x/driverlib \
            -I$(COMPILER_INCLUDE)

# Compiler flags (from projectspec)
CFLAGS := --opt_level=off \
          -v28 \
          -ml \
          -mt \
          --elf \
          --float_support=fpu32 \
          --define=DEBUG \
          --define=_FLASH \
          --define=_LAUNCHXL_F280039C \
          --diag_warning=225 \
          --diag_suppress=10063 \
          --diag_wrap=off \
          --display_error_number \
          --gen_func_subsections=on

# Linker flags (prefix with -z for TI linker)
LDFLAGS := -z --stack_size=0x200 \
           -z --heap_size=0x100 \
           -z --warn_sections \
           -z --rom_model \
           -z --reread_libs \
           -z --diag_wrap=off \
           -z --display_error_number

# Linker command file
LDCMD := $(DEVICE_SUPPORT)/common/cmd/28003x_launchxl_demo_flash_lnk.cmd

# Runtime library
LIBS := $(DRIVERLIB_ROOT)/ccs/Debug/driverlib.lib \
        /Applications/ti/ccs2041/ccs/tools/compiler/ti-cgt-c2000_22.6.3.LTS/lib/libc.a

# Object files (use notdir to strip paths)
LOCAL_OBJS := $(addprefix $(BUILD_DIR)/, $(notdir $(LOCAL_SRCS:.c=.obj)))
DEVICE_OBJS := $(BUILD_DIR)/device.obj
ASM_OBJS := $(BUILD_DIR)/f28003x_codestartbranch.obj
ALL_OBJS := $(LOCAL_OBJS) $(DEVICE_OBJS) $(ASM_OBJS)

.PHONY: all clean

all: $(OUTPUT)

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

# Local source files
$(BUILD_DIR)/%.obj: %.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(INCLUDES) --output_file=$@ $<

# Device source files
$(BUILD_DIR)/device.obj: $(DEVICE_SUPPORT)/common/source/device.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(INCLUDES) --output_file=$@ $<

# Assembly files
$(BUILD_DIR)/f28003x_codestartbranch.obj: $(DEVICE_SUPPORT)/common/source/f28003x_codestartbranch.asm | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(INCLUDES) --output_file=$@ $<

$(OUTPUT): $(ALL_OBJS)
	$(CC) $(LDFLAGS) -o $@ $(ALL_OBJS) $(LDCMD) $(LIBS)

clean:
	rm -rf $(BUILD_DIR)

# Show configuration
info:
	@echo "Project: $(PROJECT)"
	@echo "Compiler: $(CC)"
	@echo "Output: $(OUTPUT)"
	@echo "Local Sources: $(LOCAL_SRCS)"
	@echo "Device Sources: $(DEVICE_SRCS)"
	@echo "ASM Sources: $(ASM_SRCS)"
	@echo "Objects: $(ALL_OBJS)"
