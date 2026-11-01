# Aura 复现用例（69d360068）

- `json_parse_fibers.aura`（aura#4788）：多 fiber 并发 `json-parse` → glibc double free。先 `python3 build.py` 编译内核，再生成一个合成 JSON：
  `build/pack --in examples/synthetic/order_10.txt --out repro/big.json`，然后
  `AURA_SANDBOX=off AURA_PIPELINE_STRICT=0 aura --load repro/json_parse_fibers.aura`。
- `set_cons_shadow.aura`（aura#4789）：局部变量与原语同名时 `(set! x (cons v x))` 得到 `(1 . <unknown>)`。期望输出 `h1=(1) h2=(1) h3=(1) h4=2`。
