"""Regenerate the catalogue and recipes in vm_clone/flowgen/reference/flow_generation_reference.md."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vm_clone.flowgen.reference_gen import write  # noqa: E402

if __name__ == "__main__":
    print("wrote", write())
