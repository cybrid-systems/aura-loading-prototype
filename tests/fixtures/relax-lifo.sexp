;; 测试夹具：故意把先卸后装关掉。热替换必须拒绝，不能拿去重解。
((hard  min-support   0.75  "货物底面至少 75% 有支撑")
 (hard  lifo          0     "关闭先卸后装")
 (hard  hazmat-sep    1000  "不同类别危险品纵向间距 ≥ 1000mm")
 (check cog-x         0.30 0.70 "重心纵向位置（占柜长比例）")
 (check cog-y         0.40 0.60 "重心横向位置（占柜宽比例）")
 (check max-unplaced  0     "所有货物必须装下")
 (check end-load      18000 "单端载荷")
 (prefer cost         1.0   "运费"))
