//===- lld_wasm_main.cpp - wasm-ld only -----------------------------------===//
//
// M1 体积实验 COS-1：把 lld 裁成「只有 WebAssembly 驱动」。
//
// 为什么有用：上游 lld 是一个**多平台**驱动，按 argv[0] 分派（见
// lld/Common/DriverDispatcher.cpp: getFlavor/parseProgname）。为了让
// `wasm-ld` 这个名字能工作，`LLD_ALL_DRIVERS` 把 coff/elf/mingw/macho/wasm
// 五个驱动的入口地址全放进一张表里，链接器因此**必须**把 ELF/COFF/MachO/MinGW
// 四套完整的链接器实现都拉进二进制 —— 我们一个都用不到。
//
// 本文件只声明 wasm 驱动。配合把 lld/CMakeLists.txt 里
// add_subdirectory(COFF/ELF/MachO/MinGW) 去掉，四套实现根本不进链接。
//
// 与上游 lld/tools/lld/lld.cpp 的唯一语义差别：驱动表只有 wasm。
// 入口名字兼容 wasm-ld / ld-wasm / -flavor wasm（parseProgname 按 '-' 切分后
// 逐段匹配，所以 "wasm-ld" 命中 "wasm"）。
//
//===----------------------------------------------------------------------===//
#include "lld/Common/Driver.h"
#include "lld/Common/ErrorHandler.h"
#include "llvm/ADT/ArrayRef.h"
#include "llvm/Support/Process.h"
#include "llvm/Support/Driver.h"   // llvm::ToolContext
#include "llvm/Support/InitLLVM.h"
#include <cstdlib>

using namespace lld;
using namespace llvm;
using namespace llvm::sys;

namespace lld {
extern bool inTestOutputDisabled;

int unsafeLldMain(llvm::ArrayRef<const char *> args,
                  llvm::raw_ostream &stdoutOS, llvm::raw_ostream &stderrOS,
                  llvm::ArrayRef<DriverDef> drivers, bool exitEarly);
} // namespace lld

// 只要这一个驱动。
LLD_HAS_DRIVER(wasm)

static const DriverDef WasmOnlyDriver = {lld::Wasm, &lld::wasm::link};

int lld_main(int argc, char **argv, const llvm::ToolContext &) {
  sys::Process::UseANSIEscapeCodes(true);
  ArrayRef<const char *> args(argv, argv + argc);
  return lld::unsafeLldMain(args, llvm::outs(), llvm::errs(),
                            ArrayRef<DriverDef>(&WasmOnlyDriver, 1),
                            /*exitEarly=*/true);
}

int lld_main(int argc, char **argv, const llvm::ToolContext &);

// 必须有真正的 main()。没有它，链接产物是个 7.7 KB 的空壳：emcc 打完
// `--export-if-defined=main` 就静默产出 stub（exit 0、文件很小），我们实测踩到过。
// 这与上游 cmake/modules/llvm-driver-template.cpp.in 展开的内容一致。
int main(int argc, char **argv) {
  llvm::InitLLVM X(argc, argv);
  return lld_main(argc, argv, {argv[0], nullptr, false});
}
