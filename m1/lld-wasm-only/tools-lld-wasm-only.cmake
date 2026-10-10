# COS-1：追加一个「只含 wasm 驱动」的 lld（产物 bin/lld-wasm-only.{js,wasm}）。
#
# 做法：不动上游 lld.cpp，而是自己提供一个 main（m1/lld-wasm-only/lld_wasm_main.cpp）
# 并把 lldWasm 之外的四个驱动库（lldELF/lldCOFF/lldMachO/lldMinGW）从链接行里去掉。
# 链接行的其余部分与上游 lld 目标**逐字相同**（从 build-lld/build.ninja 抄来），
# 保证唯一变量就是「少了四个驱动」。
#
# 由 m1/patch-lld-wasm-only.sh 以 include() 挂到 lld/CMakeLists.txt 末尾。

# CMAKE_CURRENT_SOURCE_DIR 是 <repo>/toolchain/llvm-project/lld，
# 而本仓根在它上面三层；用 M1_LDWASM_SRC 传入绝对路径最稳（脚本负责传）。
if(NOT DEFINED M1_LDWASM_SRC)
  set(M1_LDWASM_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../m1/lld-wasm-only")
endif()

add_executable(lld-wasm-only EXCLUDE_FROM_ALL
  "${M1_LDWASM_SRC}/lld_wasm_main.cpp")

include_directories(BEFORE "${CMAKE_CURRENT_SOURCE_DIR}/include")

# 注意：这里必须写绝对路径。CMake 不会自动在 lib/ 下找 `${M1_LIBDIR}/libLLVMSupport.a`——
# 直接写名字会变成 `-llibLLVMSupport`，wasm-ld 找不到（实测报 unable to find library）。
# 上游 lld 目标用的是 llvm_config()/LINK_COMPONENTS 机制，我们绕过它，显式给 .a。
set(M1_LIBDIR "${CMAKE_BINARY_DIR}/lib")
target_link_libraries(lld-wasm-only PRIVATE
  ${M1_LIBDIR}/libLLVMSupport.a ${M1_LIBDIR}/libLLVMTargetParser.a
  ${M1_LIBDIR}/liblldCommon.a ${M1_LIBDIR}/liblldWasm.a
  ${M1_LIBDIR}/libLLVMDTLTO.a ${M1_LIBDIR}/libLLVMLibDriver.a ${M1_LIBDIR}/libLLVMWindowsDriver.a ${M1_LIBDIR}/libLLVMWindowsManifest.a
  ${M1_LIBDIR}/libLLVMWebAssemblyCodeGen.a ${M1_LIBDIR}/libLLVMWebAssemblyAsmParser.a ${M1_LIBDIR}/libLLVMWebAssemblyDisassembler.a
  ${M1_LIBDIR}/libLLVMMCDisassembler.a ${M1_LIBDIR}/libLLVMWebAssemblyUtils.a ${M1_LIBDIR}/libLLVMWebAssemblyDesc.a ${M1_LIBDIR}/libLLVMWebAssemblyInfo.a
  ${M1_LIBDIR}/libLLVMLTO.a ${M1_LIBDIR}/libLLVMExtensions.a ${M1_LIBDIR}/libLLVMPlugins.a ${M1_LIBDIR}/libLLVMPasses.a ${M1_LIBDIR}/libLLVMAsmPrinter.a
  ${M1_LIBDIR}/libLLVMGlobalISel.a ${M1_LIBDIR}/libLLVMSelectionDAG.a ${M1_LIBDIR}/libLLVMCodeGen.a ${M1_LIBDIR}/libLLVMCGData.a ${M1_LIBDIR}/libLLVMObjCARCOpts.a
  ${M1_LIBDIR}/libLLVMTarget.a ${M1_LIBDIR}/libLLVMCodeGenTypes.a ${M1_LIBDIR}/libLLVMCFGuard.a ${M1_LIBDIR}/libLLVMCoroutines.a ${M1_LIBDIR}/libLLVMipo.a
  ${M1_LIBDIR}/libLLVMBitWriter.a ${M1_LIBDIR}/libLLVMInstrumentation.a ${M1_LIBDIR}/libLLVMLinker.a ${M1_LIBDIR}/libLLVMFrontendOpenMP.a
  ${M1_LIBDIR}/libLLVMScalarOpts.a ${M1_LIBDIR}/libLLVMAggressiveInstCombine.a ${M1_LIBDIR}/libLLVMInstCombine.a ${M1_LIBDIR}/libLLVMFrontendOffloading.a
  ${M1_LIBDIR}/libLLVMObjectYAML.a ${M1_LIBDIR}/libLLVMFrontendAtomic.a ${M1_LIBDIR}/libLLVMFrontendDirective.a ${M1_LIBDIR}/libLLVMHipStdPar.a
  ${M1_LIBDIR}/libLLVMIRPrinter.a ${M1_LIBDIR}/libLLVMVectorize.a ${M1_LIBDIR}/libLLVMTransformUtils.a ${M1_LIBDIR}/libLLVMSandboxIR.a ${M1_LIBDIR}/libLLVMAnalysis.a
  ${M1_LIBDIR}/libLLVMFrontendHLSL.a ${M1_LIBDIR}/libLLVMProfileData.a ${M1_LIBDIR}/libLLVMSymbolize.a ${M1_LIBDIR}/libLLVMDebugInfoPDB.a
  ${M1_LIBDIR}/libLLVMDebugInfoCodeView.a ${M1_LIBDIR}/libLLVMDebugInfoMSF.a ${M1_LIBDIR}/libLLVMDebugInfoGSYM.a ${M1_LIBDIR}/libLLVMDebugInfoDWARF.a
  ${M1_LIBDIR}/libLLVMObject.a ${M1_LIBDIR}/libLLVMTextAPI.a ${M1_LIBDIR}/libLLVMMCParser.a ${M1_LIBDIR}/libLLVMMC.a ${M1_LIBDIR}/libLLVMOption.a
  ${M1_LIBDIR}/libLLVMDebugInfoDWARFLowLevel.a ${M1_LIBDIR}/libLLVMIRReader.a ${M1_LIBDIR}/libLLVMBitReader.a ${M1_LIBDIR}/libLLVMAsmParser.a
  ${M1_LIBDIR}/libLLVMCore.a ${M1_LIBDIR}/libLLVMRemarks.a ${M1_LIBDIR}/libLLVMBitstreamReader.a ${M1_LIBDIR}/libLLVMBinaryFormat.a
  ${M1_LIBDIR}/libLLVMDebugInfoBTF.a ${M1_LIBDIR}/libLLVMDemangle.a
  -lrt -lm)

# emscripten 侧链接旗标与 build-lld 完全一致（.js 胶水 + MODULARIZE 导出）
set(LLD_WASM_ONLY_LINK_FLAGS
  "-sWASM=1 -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=5242880 -sEXIT_RUNTIME=0 \
-sINITIAL_MEMORY=268435456 -sFORCE_FILESYSTEM=1 -sEXCEPTION_STACK_TRACES=0 \
-sMODULARIZE=1 -sEXPORT_NAME=createToolChain \
-sEXPORTED_RUNTIME_METHODS=FS,callMain,ccall,cwrap,getValue,setValue -fwasm-exceptions")
set_target_properties(lld-wasm-only PROPERTIES
  LINK_FLAGS "${LLD_WASM_ONLY_LINK_FLAGS}"
  OUTPUT_NAME "lld-wasm-only")
