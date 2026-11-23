#pragma once

#include <string>
#include <utility>
#include <vector>

namespace apex_core {

/// Deterministic Kahn topological sort matching VisionPipeline._kahn semantics:
/// ties follow the order of `ids`, and any leftover cyclic nodes are appended
/// in their original relative order so no node is silently dropped.
std::vector<std::string> kahn_sort(
    const std::vector<std::string>& ids,
    const std::vector<std::pair<std::string, std::string>>& edges
);

/// Iterative 3-color DFS detecting nodes participating in or reachable within cycles.
std::vector<std::string> find_cycle_nodes(
    const std::vector<std::string>& ids,
    const std::vector<std::pair<std::string, std::string>>& edges
);

/// Group nodes in `order` into topological waves (levels) where nodes within
/// the same wave have no dependencies on each other and can execute concurrently.
std::vector<std::vector<std::string>> compute_execution_waves(
    const std::vector<std::string>& order,
    const std::vector<std::pair<std::string, std::string>>& edges
);

}  // namespace apex_core
