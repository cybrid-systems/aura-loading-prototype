;; 一个客户一份。合成客户，限重 210kg 只为了让演示里的托盘（200kg）不能再和纸箱同柜。
;;   PC_RULES=rules/customers/acme.sexp ./run.sh rules
((hard  min-support   0.75  "货物底面至少 75% 有支撑")
 (hard  lifo          1     "先卸后装：先到站的货不能被后到站的货挡住")
 (hard  hazmat-sep    1000  "不同类别危险品纵向间距 ≥ 1000mm")
 (hard  max-kg        210   "合成示例：单柜毛重不超过 210kg")
 (check cog-x         0.30 0.70 "重心纵向位置（占柜长比例）")
 (check cog-y         0.40 0.60 "重心横向位置（占柜宽比例）")
 (check max-unplaced  0     "所有货物必须装下")
 (check end-load      18000 "单端（前端/门端）分担载荷 ≤ 18000kg（两点支撑近似）")
 (prefer cost         1.0   "运费（相对柜价）")
 (prefer vol-util     0.3   "体积利用率")
 (prefer cog-dev      0.2   "重心偏离中心"))
