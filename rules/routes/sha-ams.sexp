;; 一条线路一份。这是合成线路 SHA–AMS，不是真实客户。
;; 调度员改完保存，然后：
;;   ./run.sh rules
;; 换成别的文件：
;;   PC_RULES=rules/customers/acme.sexp ./run.sh rules
;;
;; 常用键（最后一项是说明，留着）：
;;   (hard no-mix carton pallet "纸箱与托盘不能同柜")   品类 = sku 里第一个 '-' 前面
;;   (hard only-type 40HQ "本线只用 40HQ")
;;   (hard allow-types 20GP 40HQ "本线不用 45HC")
;;   (hard max-kg 8000 "单柜毛重上限 kg")
;;   (hard lifo 1 "先卸后装，不能低于 1")
;;   (hard min-support 0.75 "支撑率，不能低于 0.75")
;;   (hard hazmat-sep 1000 "危险品间距 mm，不能低于 1000")
;;   (check cog-x 0.30 0.70 "重心纵向")
;;   (check end-load 18000 "单端载荷 kg")
;; 演示改动只有下一行 no-mix。取消注释即可试限柜型 / 限重。
((hard  min-support   0.75  "货物底面至少 75% 有支撑")
 (hard  lifo          1     "先卸后装：先到站的货不能被后到站的货挡住")
 (hard  hazmat-sep    1000  "不同类别危险品纵向间距 ≥ 1000mm")
 (hard  no-mix carton pallet "纸箱与托盘不能同柜")
 (check cog-x         0.30 0.70 "重心纵向位置（占柜长比例）")
 (check cog-y         0.40 0.60 "重心横向位置（占柜宽比例）")
 (check max-unplaced  0     "所有货物必须装下")
 (check end-load      18000 "单端（前端/门端）分担载荷 ≤ 18000kg（两点支撑近似）")
 (prefer cost         1.0   "运费（相对柜价）")
 (prefer vol-util     0.3   "体积利用率")
 (prefer cog-dev      0.2   "重心偏离中心"))
