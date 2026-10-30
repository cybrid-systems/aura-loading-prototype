# 决策解释报告（Aura 协调器生成）

## order_01.txt
- 采用：**成本** Agent 方案
- 成本：评分 1.112，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 空间优化：评分 1.115，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 卸货顺序：评分 1.118，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.766%
- 稳定/重量：评分 1.226，柜 2（1x20GP+1x45HC），相对运费 2.85，体积利用率 60.431%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=unbound，裁决后=out/bench/order_01.txt.agent3.json；卸货顺序:rolled-back, 空间优化:rolled-back, 成本:committed, 稳定/重量:rolled-back

## order_02.txt
- 采用：**成本** Agent 方案
- 成本：评分 1.113，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 空间优化：评分 1.113，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 卸货顺序：评分 1.114，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 稳定/重量：评分 1.119，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 65.474%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_01.txt.agent3.json，裁决后=out/bench/order_02.txt.agent3.json；成本:committed, 卸货顺序:rolled-back, 空间优化:rolled-back, 稳定/重量:rolled-back

## order_03.txt
- 采用：**卸货顺序** Agent 方案
- 卸货顺序：评分 1.117，柜 3（2x40HQ+1x45HC），相对运费 5.05，体积利用率 69.101%
- 成本：评分 1.286，柜 4（1x20GP+3x40HQ），相对运费 5.8，体积利用率 62.902%
- 空间优化：评分 1.293，柜 4（1x20GP+3x40HQ），相对运费 5.8，体积利用率 62.902%
- 否决 稳定/重量：45HC cog-x=0.715 超出 [0.3,0.7]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_02.txt.agent3.json，裁决后=out/bench/order_03.txt.agent2.json；空间优化:rolled-back, 稳定/重量:rolled-back, 成本:rolled-back, 卸货顺序:committed

## order_04.txt
- 采用：**成本** Agent 方案
- 成本：评分 1.176，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 空间优化：评分 1.178，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 卸货顺序：评分 1.178，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 稳定/重量：评分 1.19，柜 1（1x40HQ），相对运费 1.6，体积利用率 42.66%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_03.txt.agent2.json，裁决后=out/bench/order_04.txt.agent3.json；空间优化:rolled-back, 稳定/重量:rolled-back, 成本:committed, 卸货顺序:rolled-back

## order_05.txt
- 采用：**空间优化** Agent 方案
- 空间优化：评分 1.106，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 卸货顺序：评分 1.106，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 稳定/重量：评分 1.11，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 成本：评分 1.11，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.473%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_04.txt.agent3.json，裁决后=out/bench/order_05.txt.agent0.json；空间优化:committed, 稳定/重量:rolled-back, 成本:rolled-back, 卸货顺序:rolled-back

## order_06.txt
- 采用：**空间优化** Agent 方案
- 空间优化：评分 1.121，柜 3（1x20GP+2x40HQ），相对运费 4.2，体积利用率 63.92%
- 成本：评分 1.123，柜 3（1x20GP+2x40HQ），相对运费 4.2，体积利用率 63.92%
- 卸货顺序：评分 1.124，柜 3（1x20GP+2x40HQ），相对运费 4.2，体积利用率 63.92%
- 稳定/重量：评分 1.128，柜 3（1x20GP+2x40HQ），相对运费 4.2，体积利用率 63.92%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_05.txt.agent0.json，裁决后=out/bench/order_06.txt.agent0.json；稳定/重量:rolled-back, 成本:rolled-back, 卸货顺序:rolled-back, 空间优化:committed

## order_07.txt
- 采用：**空间优化** Agent 方案
- 空间优化：评分 1.119，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 卸货顺序：评分 1.121，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 稳定/重量：评分 1.123，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 成本：评分 1.127，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 67.939%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_06.txt.agent0.json，裁决后=out/bench/order_07.txt.agent0.json；成本:rolled-back, 空间优化:committed, 稳定/重量:rolled-back, 卸货顺序:rolled-back

## order_08.txt
- 采用：**卸货顺序** Agent 方案
- 卸货顺序：评分 1.171，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 空间优化：评分 1.172，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 稳定/重量：评分 1.172，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 成本：评分 1.174，柜 1（1x40HQ），相对运费 1.6，体积利用率 43.749%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_07.txt.agent0.json，裁决后=out/bench/order_08.txt.agent2.json；稳定/重量:rolled-back, 成本:rolled-back, 空间优化:rolled-back, 卸货顺序:committed

## order_09.txt
- 采用：**空间优化** Agent 方案
- 空间优化：评分 1.168，柜 3（3x40HQ），相对运费 4.8，体积利用率 48.836%
- 卸货顺序：评分 1.168，柜 3（3x40HQ），相对运费 4.8，体积利用率 48.836%
- 成本：评分 1.17，柜 3（3x40HQ），相对运费 4.8，体积利用率 48.836%
- 否决 稳定/重量：40HQ cog-x=0.742 超出 [0.3,0.7]
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_08.txt.agent2.json，裁决后=out/bench/order_09.txt.agent0.json；空间优化:committed, 稳定/重量:rolled-back, 成本:rolled-back, 卸货顺序:rolled-back

## order_10.txt
- 采用：**空间优化** Agent 方案
- 空间优化：评分 1.088，柜 3（3x40HQ），相对运费 4.8，体积利用率 73.542%
- 成本：评分 1.155，柜 3（2x40HQ+1x45HC），相对运费 5.05，体积利用率 70.563%
- 卸货顺序：评分 1.156，柜 3（2x40HQ+1x45HC），相对运费 5.05，体积利用率 70.563%
- 稳定/重量：评分 1.337，柜 4（1x20GP+3x40HQ），相对运费 5.8，体积利用率 64.233%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_09.txt.agent0.json，裁决后=out/bench/order_10.txt.agent0.json；空间优化:committed, 稳定/重量:rolled-back, 成本:rolled-back, 卸货顺序:rolled-back

## order_11.txt
- 采用：**卸货顺序** Agent 方案
- 卸货顺序：评分 1.226，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 稳定/重量：评分 1.227，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 空间优化：评分 1.24，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 成本：评分 1.244，柜 2（1x20GP+1x40HQ），相对运费 2.6，体积利用率 26.173%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_10.txt.agent0.json，裁决后=out/bench/order_11.txt.agent2.json；空间优化:rolled-back, 稳定/重量:rolled-back, 卸货顺序:committed, 成本:rolled-back

## order_12.txt
- 采用：**卸货顺序** Agent 方案
- 卸货顺序：评分 1.111，柜 3（2x40HQ+1x45HC），相对运费 5.05，体积利用率 67.37%
- 空间优化：评分 1.162，柜 3（1x40HQ+2x45HC），相对运费 5.3，体积利用率 64.747%
- 成本：评分 1.276，柜 4（1x20GP+3x40HQ），相对运费 5.8，体积利用率 61.327%
- 稳定/重量：评分 1.331，柜 4（1x20GP+2x40HQ+1x45HC），相对运费 6.05，体积利用率 59.146%
- 生效的硬约束：货物底面至少 75% 有支撑；先卸后装：先到站的货不能被后到站的货挡住；不同类别危险品纵向间距 ≥ 1000mm
- overlay：提案期间全局 chosen-plan=out/bench/order_11.txt.agent2.json，裁决后=out/bench/order_12.txt.agent2.json；卸货顺序:committed, 空间优化:rolled-back, 稳定/重量:rolled-back, 成本:rolled-back
