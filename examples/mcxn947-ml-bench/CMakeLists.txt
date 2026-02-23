cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(mcxn947_ml_bench)

set(NO_THREADSAFE_STATICS $<TARGET_PROPERTY:compiler-cpp,no_threadsafe_statics>)
zephyr_compile_options($<$<COMPILE_LANGUAGE:CXX>:${NO_THREADSAFE_STATICS}>)

target_sources(app PRIVATE
    src/main.cpp
    src/ml_bench.cpp
    src/dwt_profiler.c
    src/models/sine_model.cpp
)
target_include_directories(app PRIVATE src src/models)
