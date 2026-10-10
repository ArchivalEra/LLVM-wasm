// M0 host main module — built WITH emcc (main module side of the ABI).
// Provides the callbacks the side module imports, then dlopens it and calls in.
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <dlfcn.h>
#include <emscripten.h>

// Host callback the side module calls (stands in for the host LAPACK).
extern "C" EMSCRIPTEN_KEEPALIVE int host_det2(int a, int b, int c, int d) {
  return a * d - b * c;
}

// Host thrower: the side module calls this and catches what it throws.
extern "C" EMSCRIPTEN_KEEPALIVE void host_error() {
  throw std::runtime_error("octave-error-from-oct");
}

static int failures = 0;

static void check(const char* what, long got, long want) {
  const bool ok = (got == want);
  if (!ok) failures++;
  printf("%s %s: got=%ld want=%ld\n", ok ? "PASS" : "FAIL", what, got, want);
}

static void check_str(const char* what, const char* got, const char* want) {
  const bool ok = got && want && strcmp(got, want) == 0;
  if (!ok) failures++;
  printf("%s %s: got=%s want=%s\n", ok ? "PASS" : "FAIL", what,
         got ? got : "(null)", want ? want : "(null)");
}

int main() {
  printf("== M0 host: dlopen side module ==\n");
  void* h = dlopen("minifn.so", RTLD_NOW);
  if (!h) {
    printf("FAIL dlopen: %s\n", dlerror());
    printf("=== %d FAIL ===\n", failures + 1);
    return 1;
  }
  printf("PASS dlopen\n");

  auto minifn = (int (*)(int))dlsym(h, "minifn");
  auto miniprobe = (int (*)(int, int, int, int))dlsym(h, "miniprobe");
  auto minithrow = (int (*)(int))dlsym(h, "minithrow");
  auto ministl = (const char* (*)(unsigned long))dlsym(h, "ministl");
  check("dlsym(minifn)", minifn != nullptr, 1);
  check("dlsym(miniprobe)", miniprobe != nullptr, 1);
  check("dlsym(minithrow)", minithrow != nullptr, 1);
  check("dlsym(ministl)", ministl != nullptr, 1);

  if (minifn) check("minifn(7)", minifn(7), 10);           // 7 + "abc".size()
  if (miniprobe) {
    check("miniprobe([2,3;1,4])", miniprobe(2, 3, 1, 4), 5);
    check("miniprobe([1,2;3,4])", miniprobe(1, 2, 3, 4), -2);
  }
  if (minithrow) {
    check("minithrow(0)", minithrow(0), 0);
    check("minithrow(1)", minithrow(1), 1);
    check("minithrow(2)", minithrow(2), 1);
  }
  if (ministl) check_str("ministl(42)", ministl(42), "42:2");

  printf("=== %s ===\n", failures == 0 ? "ALL PASS" : "FAILURES");
  return failures == 0 ? 0 : 1;
}
