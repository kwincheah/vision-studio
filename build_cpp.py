"""
Build helper for compiling the C++17 `_apex_core` extension via CMake + pybind11.

Usage:
    python build_cpp.py
    python build_cpp.py --clean
"""
import argparse
import os
import shutil
import subprocess
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(ROOT, "build_cpp")


def find_cmake() -> str:
    found = shutil.which("cmake")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
            r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
            r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
            r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
            r"C:\Program Files\CMake\bin\cmake.exe",
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        # Fallback: query vswhere if installed in another VS edition/path
        vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                               "Microsoft Visual Studio", "Installer", "vswhere.exe")
        if os.path.isfile(vswhere):
            res = subprocess.run(
                [vswhere, "-latest", "-products", "*", "-property", "installationPath"],
                capture_output=True, text=True, check=False
            )
            vs_path = res.stdout.strip()
            if vs_path:
                cand = os.path.join(vs_path, "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake", "bin", "cmake.exe")
                if os.path.isfile(cand):
                    return cand
    raise RuntimeError("CMake executable not found. Install CMake or Visual Studio C++ Build Tools.")


def build(clean: bool = False) -> int:
    if clean and os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR, exist_ok=True)

    cmake = find_cmake()
    py_exe = sys.executable

    import pybind11
    pybind_dir = pybind11.get_cmake_dir()

    cfg_cmd = [
        cmake,
        "-S", ROOT,
        "-B", BUILD_DIR,
        f"-DPython3_EXECUTABLE={py_exe}",
        f"-Dpybind11_DIR={pybind_dir}",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    if sys.platform == "win32":
        cfg_cmd.extend(["-A", "x64"])

    print("[build_cpp] Configuring:", " ".join(cfg_cmd))
    subprocess.check_call(cfg_cmd)

    build_cmd = [cmake, "--build", BUILD_DIR, "--config", "Release", "--parallel"]
    print("[build_cpp] Building:", " ".join(build_cmd))
    subprocess.check_call(build_cmd)

    # Verify import cleanly in a fresh check
    subprocess.check_call([
        py_exe, "-c",
        "import apex_vision._apex_core as c; print('[build_cpp] Loaded _apex_core:', c.build_info())"
    ], cwd=ROOT)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build _apex_core C++ extension")
    parser.add_argument("--clean", action="store_true", help="Remove build_cpp directory before building")
    args = parser.parse_args()
    sys.exit(build(clean=args.clean))
