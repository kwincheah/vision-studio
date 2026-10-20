"""Text formatting of flow results shared by the front ends."""
from typing import Any, Dict


def format_flow_outputs(pipeline, results: Dict[str, Any]) -> str:
    """One line per module: its verdict plus every scalar / text output it produced."""
    def fmt(v) -> str:
        if isinstance(v, bool):
            return str(int(v))
        if isinstance(v, float):
            return f"{v:.3f}".rstrip("0").rstrip(".") if v == v else "nan"
        return str(v)

    lines = []
    for nid in pipeline.execution_order:
        res, node = results.get(nid), pipeline.nodes.get(nid)
        if res is None or node is None:
            continue
        fields = [f"{k}={fmt(v)}" for k, v in res.outputs.items()
                  if isinstance(v, (bool, int, float, str)) and len(str(v)) <= 60]
        lines.append(f"{node.name},{res.status.value.upper()}" + ("," + ",".join(fields) if fields else ""))
    return "\n".join(lines)
