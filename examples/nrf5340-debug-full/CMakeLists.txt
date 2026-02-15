# nRF5340 Debug Full Example
cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrf5340-debug-full)

target_sources(app PRIVATE src/main.c)
