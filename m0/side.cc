// M0 side module fixture — compiled OUTSIDE emcc, hand-linked with wasm-ld.
// Mirrors SPEC 4.4 anchors: miniprobe calls host LAPACK-like callback,
// minithrow exercises exceptions across the dlopen boundary,
// ministl exercises STL template instantiations the host may not have.
#include <string>
#include <map>
#include <sstream>
#include <stdexcept>
#include <cstdio>

// Host-provided callbacks (resolved across the dlopen boundary at call time).
extern "C" int host_det2(int a, int b, int c, int d);
extern "C" void host_error();

// SPEC 9.1: minimal source, one exported function + one std::string use.
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}

// SPEC 9.3: call a host symbol from inside the side module.
extern "C" __attribute__((visibility("default"))) int miniprobe(int a, int b, int c, int d) {
  return host_det2(a, b, c, d);
}

// SPEC 9.4: exception round-trips.
//   mode 0 -> no throw
//   mode 1 -> side throws, side catches
//   mode 2 -> host throws (via host_error), side catches
extern "C" __attribute__((visibility("default"))) int minithrow(int mode) {
  try {
    if (mode == 0) {
      printf("no-throw\n");
      return 0;
    }
    if (mode == 1) {
      throw std::runtime_error("thrown-from-oct");
    }
    if (mode == 2) {
      host_error();
    }
  } catch (const std::exception& e) {
    printf("caught:%s\n", e.what());
    return 1;
  }
  return 0;
}

// SPEC 9.6: STL instantiations the host may not have (template symbol gap).
// Reproduces the two gaps recorded in SPEC 5.2:
//   std::map<K,V>::__tree::__emplace_unique_key_args
//   std::basic_ostream<char>::operator<<(unsigned long)
extern "C" __attribute__((visibility("default"))) const char* ministl(unsigned long v) {
  static std::string out;
  std::map<std::string, double> m;
  m["a"] = 1.5;
  m["b"] = 2.5;
  std::ostringstream os;
  os << v;
  os << ":" << m.size();
  out = os.str();
  return out.c_str();
}
