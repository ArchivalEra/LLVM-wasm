#!/usr/bin/env bash
# M0 side module for the STL template-gap counter-example (SPEC 5.2 / 9.6).
# Instantiates the two template combinations SPEC 5.2 recorded as the observed
# host-export gaps: std::map __tree emplace and ostream<<unsigned long.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cat > "$ROOT/landmine.cc" <<'EOF'
#include <map>
#include <string>
#include <sstream>
#include <tuple>
#include <utility>
#include <cstdio>
extern "C" __attribute__((visibility("default"))) int landmine(unsigned long v) {
  std::map<std::string, double> m;
  m.emplace(std::piecewise_construct,
            std::forward_as_tuple("k"),
            std::forward_as_tuple(1.0));
  std::ostringstream os;
  os << v << ":" << m.size() << ":" << m["k"];
  std::string s = os.str();
  printf("landmine->%s\n", s.c_str());
  return (int)s.size();
}
EOF
echo "wrote $ROOT/landmine.cc"
