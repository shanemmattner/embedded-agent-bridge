cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(stm32n6_ml_bench)

target_sources(app PRIVATE
    src/main.c
    src/ml_bench.c
    src/dwt_profiler.c
)
target_include_directories(app PRIVATE src)
