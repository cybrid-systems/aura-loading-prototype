# 决策解释报告（Aura 协调器生成）

## order_01.txt
- 采用：**层式** Agent 方案
  - 构造思路：先铺满一层再往上，优先填满底面
- 层式：评分 1.113，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 人工经验：评分 1.115，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 块式：评分 1.133，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 否决 墙式：20GP cog-y=0.381 超出 [0.4,0.6]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=unbound，裁决后=out/bench/order_01.txt.agent1.json；层式:committed, 墙式:rolled-back, 块式:rolled-back, 人工经验:rolled-back

## order_02.txt
- 采用：**人工经验** Agent 方案
  - 构造思路：按下面的人工经验规则装：大箱打底、大箱先装(big=1.0)；同规格成墙：优先在同规格箱子上继续码(same=0.5)；重货在下(heavy=0.3)；选能把剩余高度/宽度拼满的箱规(waste=0.0)
- 人工经验：评分 1.107，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 墙式：评分 1.111，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 否决 块式：20GP cog-y=0.346 超出 [0.4,0.6]
- 否决 层式：20GP cog-y=0.339 超出 [0.4,0.6]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_01.txt.agent1.json，裁决后=out/bench/order_02.txt.agent3.json；层式:rolled-back, 块式:rolled-back, 墙式:rolled-back, 人工经验:committed

## order_03.txt
- 采用：**块式** Agent 方案
  - 构造思路：同尺寸箱子拼成最大的块，放进离柜角最近的空间
- 块式：评分 1.1，柜 3（3x40HQ），相对运费 4.8，体积利用率 72.018%
- 人工经验：评分 1.258，柜 4（2x20GP+1x40HQ+1x45HC），相对运费 5.45，体积利用率 72.109%
- 墙式：评分 1.259，柜 4（2x20GP+1x40HQ+1x45HC），相对运费 5.45，体积利用率 72.109%
- 否决 层式：45HC cog-x=0.705 超出 [0.3,0.7]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_02.txt.agent3.json，裁决后=out/bench/order_03.txt.agent2.json；墙式:rolled-back, 块式:committed, 层式:rolled-back, 人工经验:rolled-back

## order_04.txt
- 采用：**层式** Agent 方案
  - 构造思路：先铺满一层再往上，优先填满底面
- 层式：评分 1.174，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 块式：评分 1.182，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 墙式：评分 1.184，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 人工经验：评分 1.187，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_03.txt.agent2.json，裁决后=out/bench/order_04.txt.agent1.json；墙式:rolled-back, 层式:committed, 块式:rolled-back, 人工经验:rolled-back

## order_05.txt
- 采用：**块式** Agent 方案
  - 构造思路：同尺寸箱子拼成最大的块，放进离柜角最近的空间
- 块式：评分 1.099，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 层式：评分 1.111，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 人工经验：评分 1.115，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 否决 墙式：20GP cog-y=0.395 超出 [0.4,0.6]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_04.txt.agent1.json，裁决后=out/bench/order_05.txt.agent2.json；层式:rolled-back, 墙式:rolled-back, 块式:committed, 人工经验:rolled-back

## order_06.txt
- 采用：**块式** Agent 方案
  - 构造思路：同尺寸箱子拼成最大的块，放进离柜角最近的空间
- 块式：评分 1.073，柜 2（2x40HQ），相对运费 3.2，体积利用率 77.816%
- 人工经验：评分 1.074，柜 2（2x40HQ），相对运费 3.2，体积利用率 77.816%
- 层式：评分 1.077，柜 2（2x40HQ），相对运费 3.2，体积利用率 77.816%
- 墙式：评分 1.185，柜 2（1x40HQ+1x45HC），相对运费 3.45，体积利用率 73.181%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_05.txt.agent2.json，裁决后=out/bench/order_06.txt.agent2.json；墙式:rolled-back, 层式:rolled-back, 块式:committed, 人工经验:rolled-back

## order_07.txt
- 采用：**墙式** Agent 方案
  - 构造思路：从柜底往门一面墙一面墙地装，优先填满横截面
- 墙式：评分 1.116，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 块式：评分 1.12，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 人工经验：评分 1.121，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 层式：评分 1.123，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_06.txt.agent2.json，裁决后=out/bench/order_07.txt.agent0.json；墙式:committed, 层式:rolled-back, 块式:rolled-back, 人工经验:rolled-back

## order_08.txt
- 采用：**墙式** Agent 方案
  - 构造思路：从柜底往门一面墙一面墙地装，优先填满横截面
- 墙式：评分 1.169，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 人工经验：评分 1.169，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 块式：评分 1.169，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 层式：评分 1.174，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_07.txt.agent0.json，裁决后=out/bench/order_08.txt.agent0.json；人工经验:rolled-back, 层式:rolled-back, 块式:rolled-back, 墙式:committed

## order_09.txt
- 采用：**墙式** Agent 方案
  - 构造思路：从柜底往门一面墙一面墙地装，优先填满横截面
- 墙式：评分 1.153，柜 3（1x20GP+1x40HQ+1x45HC），相对运费 4.45，体积利用率 57.198%
- 层式：评分 1.168，柜 3（1x20GP+1x40HQ+1x45HC），相对运费 4.45，体积利用率 57.198%
- 人工经验：评分 1.24，柜 3（3x40HQ），相对运费 4.8，体积利用率 48.836%
- 否决 块式：45HC cog-y=0.688 超出 [0.4,0.6]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_08.txt.agent0.json，裁决后=out/bench/order_09.txt.agent0.json；墙式:committed, 人工经验:rolled-back, 层式:rolled-back, 块式:rolled-back

## order_10.txt
- 采用：**人工经验** Agent 方案
  - 构造思路：按下面的人工经验规则装：大箱打底、大箱先装(big=1.0)；同规格成墙：优先在同规格箱子上继续码(same=0.5)；重货在下(heavy=0.3)；选能把剩余高度/宽度拼满的箱规(waste=0.0)
- 人工经验：评分 1.05，柜 3（1x20GP+1x40HQ+1x45HC），相对运费 4.45，体积利用率 86.133%
- 墙式：评分 1.057，柜 3（1x20GP+1x40HQ+1x45HC），相对运费 4.45，体积利用率 86.133%
- 层式：评分 1.246，柜 4（2x20GP+2x40HQ），相对运费 5.2，体积利用率 76.885%
- 块式：评分 1.246，柜 4（2x20GP+2x40HQ），相对运费 5.2，体积利用率 76.885%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_09.txt.agent0.json，裁决后=out/bench/order_10.txt.agent3.json；墙式:rolled-back, 块式:rolled-back, 人工经验:committed, 层式:rolled-back

## order_11.txt
- 采用：**块式** Agent 方案
  - 构造思路：同尺寸箱子拼成最大的块，放进离柜角最近的空间
- 块式：评分 1.23，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 人工经验：评分 1.238，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 墙式：评分 1.241，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 层式：评分 1.257，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_10.txt.agent3.json，裁决后=out/bench/order_11.txt.agent2.json；墙式:rolled-back, 层式:rolled-back, 块式:committed, 人工经验:rolled-back

## order_12.txt
- 采用：**人工经验** Agent 方案
  - 构造思路：按下面的人工经验规则装：大箱打底、大箱先装(big=1.0)；同规格成墙：优先在同规格箱子上继续码(same=0.5)；重货在下(heavy=0.3)；选能把剩余高度/宽度拼满的箱规(waste=0.0)
- 人工经验：评分 1.114，柜 3（2x40HQ+1x45HC），相对运费 5.05，体积利用率 67.37%
- 墙式：评分 1.118，柜 4（2x20GP+2x40HQ），相对运费 5.2，体积利用率 73.406%
- 层式：评分 1.129，柜 4（2x20GP+2x40HQ），相对运费 5.2，体积利用率 73.406%
- 块式：评分 1.17，柜 3（1x40HQ+2x45HC），相对运费 5.3，体积利用率 64.747%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_11.txt.agent2.json，裁决后=out/bench/order_12.txt.agent3.json；层式:rolled-back, 墙式:rolled-back, 块式:rolled-back, 人工经验:committed
