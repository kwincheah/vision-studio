"""VisionMaster guide, chapter "Logic Tools": Group.

A Group holds modules that run together: one pass, or a loop of passes (with the loop number available to the modules on the Group's
``Cycle`` output). Which modules are inside is set on each module (right-click it, "Add to group"); the flow runs the Group's modules where
the Group sits in the running order, and the Group reports the worst result among them.
"""
from apex_vision.core.param_schema import enum, num
from apex_vision.tools._spec import define, ok, port, val

OPS = ["==", "!=", ">", ">=", "<", "<="]


@define("Group", "Logic Tools",
        "Keeps modules together so a busy flow stays readable, and repeats them in a loop when asked. Put modules inside with right-click, Add to "
        "group. With the loop on they run once for every number from the start value up to (not including) the end value; the loop number is on "
        "the Cycle output. A break condition stops the loop early when Base compares to Target as chosen.",
        inputs=[port("Base", "any", "Value to test for the break condition (instead of the typed one)"), port("Target", "any", "Value to test it against")],
        outputs=[val("Cycle", "The loop number of the current (or last) pass"), val("Loops", "How many passes have run"), val("Broke", "1 when the break condition ended the loop")],
        params={"loop_enable": False, "loop_start": 0, "loop_end": 3, "interval_ms": 0, "break_enable": False, "compare_type": "Int", "break_when": "==",
                "base_value": "0", "target_value": "0"},
        schema={"loop_enable": {"kind": "bool"}, "loop_start": num(-1_000_000, 1_000_000), "loop_end": num(-1_000_000, 1_000_000), "interval_ms": num(0, 3_600_000, unit="ms"),
                "break_enable": {"kind": "bool"}, "compare_type": enum("Int", "Float", "String"), "break_when": enum(*OPS),
                "base_value": {"kind": "text", "hint": "typed Base value, used when nothing is connected"}, "target_value": {"kind": "text", "hint": "typed Target value"}})
def group(t, ctx):
    return ok("a group runs its modules when the flow runs; add modules to it with right-click, Add to group", Cycle=0, Loops=0, Broke=0)
