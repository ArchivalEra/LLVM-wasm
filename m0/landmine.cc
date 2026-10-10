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
