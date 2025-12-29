cmake_minimum_required(VERSION 3.22)
project(worker_cuda LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CUDA_STANDARD 17)

add_executable(tile_gemm_bench
    src/main.cpp
    src/tiled_gemm.cu
)

target_include_directories(tile_gemm_bench PRIVATE src)
