# 改规则

一份文件一个客户或一条线。复制 [rules/baseline.sexp](../rules/baseline.sexp)，改下面的键，保存后：

```sh
PC_RULES=rules/routes/sha-ams.sexp ./run.sh rules
```

`./run.sh rules` 默认就用 [rules/routes/sha-ams.sexp](../rules/routes/sha-ams.sexp)（这条合成线路禁纸箱和托盘混装）。客户限重的例子是 [rules/customers/acme.sexp](../rules/customers/acme.sexp)。

最后一项是说明，留着，并且要用双引号。品类是 sku 里第一个 `-` 前面的那段：`carton-a` 的品类是 `carton`。

| 键 | 写法 | 作用 |
|---|---|---|
| `no-mix` | `(hard no-mix carton pallet "纸箱与托盘不能同柜")` | 禁混装 |
| `only-type` | `(hard only-type 40HQ "只用 40HQ")` | 限一种柜型 |
| `allow-types` | `(hard allow-types 20GP 40HQ "不用 45HC")` | 允许多种柜型 |
| `max-kg` | `(hard max-kg 8000 "单柜毛重上限")` | 限重，单位 kg |
| `lifo` | `(hard lifo 1 "先卸后装")` | 站序。不能低于 1 |
| `min-support` | `(hard min-support 0.75 "支撑率")` | 不能低于 0.75 |
| `hazmat-sep` | `(hard hazmat-sep 1000 "危险品间距 mm")` | 不能低于 1000 |
| `cog-x` / `cog-y` | `(check cog-x 0.30 0.70 "重心纵向")` | 重心占柜长 / 柜宽的比例 |
| `end-load` | `(check end-load 18000 "单端载荷 kg")` | 前端或门端的分担 |

安全底线（`lifo`、`min-support`、`hazmat-sep`）只能收紧。写小了或删掉，热替换会拒绝，不会拿去重解。

改完会做两件事：用新规则重解当前这单（旧方案按新规则复核），再回放 `examples/rules-demo/hist/` 里的合成历史单。几何上仍由 `tools/verify.py` 独立校验。屏幕如果列出违例，就是这单在新规则下还没通过。

这些键变成内核参数 `no_mix`、`only`、`types`、`cap_kg`，已经编译好的 `build/pack` 直接读，不用再跑 g++。
