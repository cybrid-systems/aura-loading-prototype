# Aura v0.2.0 下游探针

用正式发布包的 `AURA_BIN` 跑，不下载 LLVM，也不编译 Aura。

```sh
export AURA_BIN=$HOME/.aura/current/bin/aura   # v0.2.0 launcher
python3 bench/v020/run_v020.py
```

结果在 `out/v020/report.json`（不入库）。`expect=ok` 的探针失败时进程退出码为 1。`orch-timeout` 预期在 8 秒内被杀掉：`std/orch` 的 `orch:parallel` 超时参数挡不住只 yield 的 worker。
