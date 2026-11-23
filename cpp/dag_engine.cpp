#include "dag_engine.hpp"

#include <algorithm>
#include <deque>
#include <unordered_map>
#include <unordered_set>

namespace apex_core {

std::vector<std::string> kahn_sort(
    const std::vector<std::string>& ids,
    const std::vector<std::pair<std::string, std::string>>& edges
) {
    const size_t n = ids.size();
    std::vector<std::string> order;
    order.reserve(n);
    if (n == 0) {
        return order;
    }

    std::unordered_map<std::string, size_t> index_of;
    index_of.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
        index_of.emplace(ids[i], i);
    }

    std::vector<std::vector<size_t>> adj(n);
    std::vector<size_t> indeg(n, 0);

    for (const auto& edge : edges) {
        auto it_a = index_of.find(edge.first);
        auto it_b = index_of.find(edge.second);
        if (it_a != index_of.end() && it_b != index_of.end() && it_a->second != it_b->second) {
            adj[it_a->second].push_back(it_b->second);
            indeg[it_b->second] += 1;
        }
    }

    std::deque<size_t> queue;
    std::vector<bool> visited(n, false);
    for (size_t i = 0; i < n; ++i) {
        if (indeg[i] == 0) {
            queue.push_back(i);
        }
    }

    while (!queue.empty()) {
        size_t cur = queue.front();
        queue.pop_front();
        visited[cur] = true;
        order.push_back(ids[cur]);
        for (size_t nxt : adj[cur]) {
            if (indeg[nxt] > 0) {
                indeg[nxt] -= 1;
                if (indeg[nxt] == 0) {
                    queue.push_back(nxt);
                }
            }
        }
    }

    // Preserve cyclic nodes in original order (exact match with VisionPipeline._kahn)
    for (size_t i = 0; i < n; ++i) {
        if (!visited[i]) {
            order.push_back(ids[i]);
        }
    }
    return order;
}

std::vector<std::string> find_cycle_nodes(
    const std::vector<std::string>& ids,
    const std::vector<std::pair<std::string, std::string>>& edges
) {
    const size_t n = ids.size();
    std::vector<std::string> cycle_nodes;
    if (n == 0) {
        return cycle_nodes;
    }

    std::unordered_map<std::string, size_t> index_of;
    index_of.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
        index_of.emplace(ids[i], i);
    }

    std::vector<std::vector<size_t>> adj(n);
    for (const auto& edge : edges) {
        auto it_a = index_of.find(edge.first);
        auto it_b = index_of.find(edge.second);
        if (it_a != index_of.end() && it_b != index_of.end()) {
            adj[it_a->second].push_back(it_b->second);
        }
    }

    // 0 = unvisited, 1 = visiting (on stack), 2 = done
    std::vector<uint8_t> state(n, 0);
    std::vector<bool> in_cycle(n, false);
    struct Frame {
        size_t node;
        size_t edge_idx;
    };
    std::vector<Frame> stack;
    stack.reserve(n);

    for (size_t start = 0; start < n; ++start) {
        if (state[start] != 0) {
            continue;
        }
        state[start] = 1;
        stack.push_back({start, 0});

        while (!stack.empty()) {
            auto& top = stack.back();
            size_t u = top.node;
            if (top.edge_idx < adj[u].size()) {
                size_t v = adj[u][top.edge_idx++];
                if (state[v] == 1) {
                    in_cycle[v] = true;
                    in_cycle[u] = true;
                } else if (state[v] == 0) {
                    state[v] = 1;
                    stack.push_back({v, 0});
                }
            } else {
                state[u] = 2;
                stack.pop_back();
            }
        }
    }

    for (size_t i = 0; i < n; ++i) {
        if (in_cycle[i]) {
            cycle_nodes.push_back(ids[i]);
        }
    }
    return cycle_nodes;
}

std::vector<std::vector<std::string>> compute_execution_waves(
    const std::vector<std::string>& order,
    const std::vector<std::pair<std::string, std::string>>& edges
) {
    const size_t n = order.size();
    std::vector<std::vector<std::string>> waves;
    if (n == 0) {
        return waves;
    }

    std::unordered_map<std::string, size_t> pos_of;
    pos_of.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
        pos_of.emplace(order[i], i);
    }

    std::vector<std::vector<size_t>> parents(n);
    for (const auto& edge : edges) {
        auto it_a = pos_of.find(edge.first);
        auto it_b = pos_of.find(edge.second);
        if (it_a != pos_of.end() && it_b != pos_of.end() && it_a->second < it_b->second) {
            parents[it_b->second].push_back(it_a->second);
        }
    }

    std::vector<size_t> level(n, 0);
    size_t max_level = 0;
    for (size_t i = 0; i < n; ++i) {
        size_t lvl = 0;
        for (size_t p : parents[i]) {
            lvl = std::max(lvl, level[p] + 1);
        }
        level[i] = lvl;
        max_level = std::max(max_level, lvl);
    }

    waves.resize(max_level + 1);
    for (size_t i = 0; i < n; ++i) {
        waves[level[i]].push_back(order[i]);
    }
    return waves;
}

}  // namespace apex_core
