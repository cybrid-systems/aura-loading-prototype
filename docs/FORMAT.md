# 求解内核输入 / 输出格式

## 输入（行格式，`#` 开头为注释）

```
C <柜型> <内长L> <内宽W> <内高H> <限重kg> <相对运费> <可用数量,-1=不限>
I <箱号> <品类> <长> <宽> <高> <单箱kg> <数量> <摆放> <顶部最大承重kg> <易碎0/1> <卸货站序> <危险品类别或->
R <键> <值>
```

- 长度单位 mm。坐标系：x 沿柜长（x=0 为柜底/前端，x=L 为柜门），y 为柜宽，z 为高度。
- 摆放：0 = 6 个方向任意，1 = 只能直立（可绕竖轴转 90°），2 = 固定方向。
- 易碎：其上不允许压货（等价于顶部承重 0）。
- 卸货站序：1 = 最先卸。开启 `lifo=1` 时，站序小的货不能被站序大的货在门的方向挡住。
- 危险品：不同类别之间沿 x 方向至少间隔 `hazmat_sep` mm。

## 命令行参数（key=value）

| 参数 | 含义 | 默认 |
|---|---|---|
| `min_support` | 底面最小支撑比例 | 0.75 |
| `lifo` | 先卸后装约束 | 1 |
| `hazmat_sep` | 危险品间距 mm | 1000 |
| `rotate` | 0 = 仅按货物允许方向；也可强制关掉旋转 | 1 |
| `sort` | 0 体积 1 底面积 2 重量 3 高度 4 输入顺序 | 0 |
| `sort_stop` | 先按卸货站排序 | 1 |
| `w_x w_z w_y w_center` | 极点选择权重 | 见源码 |
| `cpolicy` | 0 每柜选"单位运费装得最多"的柜型；1 能装下剩余全部的最便宜柜型优先 | 0 |
| `only` | 只用某一柜型（如 `only=40HQ`） | — |
| `iters` / `time_ms` / `seed` | 局部搜索（随机扰动装载顺序）的迭代数、时间上限、随机种子 | |
| `cog_x_lo/hi cog_y_lo/hi` | 重心允许范围（占柜长/柜宽的比例） | 0.30–0.70 / 0.40–0.60 |
| `cog_shift` | 装完后把整体货物平移到柜中央（需要垫木/绑扎固定） | 1 |

## 输出 JSON

```
{ "containers": [ { "type", "L","W","H","max_kg","cost","kg","vol_util","wt_util",
                    "cog":[x,y,z], "cog_ok", "end_load_kg":{"front","door"},
                    "boxes":[{"id","sku","x","y","z","dx","dy","dz","kg","stop","fragile","hazmat","seq"}] } ],
  "unplaced": [...],
  "metrics": { "boxes","containers","mix","cost","vol_util","wt_util","unplaced",
               "cog_violations","worst_cog_x","worst_cog_y","lower_bound","iters","improved","ms" } }
```

stdout 另输出一行 `@@m key=value ...`；有货未装入时退出码为 3。`tools/verify.py` 独立检查越界、重叠、超重、支撑率、先卸后装与漏装。
