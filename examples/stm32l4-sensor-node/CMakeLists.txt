cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(eab_stm32l4_sensor_node)

target_sources(app PRIVATE src/main.c)
