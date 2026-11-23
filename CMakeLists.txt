cmake_minimum_required(VERSION 3.18)
project(apex_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Locate pybind11 from the active Python environment automatically if not passed explicitly
if(NOT DEFINED pybind11_DIR)
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
        OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE PYBIND11_STATUS
    )
    if(PYBIND11_STATUS EQUAL 0 AND EXISTS "${PYBIND11_CMAKE_DIR}")
        set(pybind11_DIR "${PYBIND11_CMAKE_DIR}")
    endif()
else()
    find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
endif()

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_apex_core
    cpp/module.cpp
    cpp/dag_engine.cpp
    cpp/ring_buffer.cpp
    cpp/vision_ops.cpp
)

if(MSVC)
    target_compile_options(_apex_core PRIVATE /O2 /W4 /EHsc /permissive- /Zc:__cplusplus)
else()
    target_compile_options(_apex_core PRIVATE -O3 -Wall -Wextra -fvisibility=hidden)
endif()

# Place compiled extension directly inside apex_vision/ so both `python main.py`
# and PyInstaller resolve `apex_vision._apex_core` seamlessly.
set_target_properties(_apex_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
    LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_SOURCE_DIR}/apex_vision"
)
