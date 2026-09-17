# Optical Transceiver HLA — 功能说明与路线图

> 适用版本：**v2.0.0** ｜ 最后更新：2026-09-10
>
> 本文件说明插件**已支持什么**、**哪些已经过真实验证**、**哪些还没做**。
> 安装与使用见 `extensions/optical_transceiver_hla/README.md`。

---

## 一、总览

一个 Saleae Logic 2 高级协议分析器（HLA），在 I2C 之上解码光模块管理协议。

| | |
| :--- | :--- |
| 支持协议 | **CMIS**（QSFP-DD / OSFP / SFP-DD / DSFP）、**SFF-8472**（SFP/SFP+）、SFF-8436/8636（仅识别） |
| 规范依据 | OIF-CMIS-05.4（逐条标注表号） |
| 代码规模 | 13 个模块，最大 502 行 |
| 字段覆盖 | 基线抓包上 **107 个字段名**、1753 行输出 |
| 测试 | 83 项单元检查 + 真实抓包逐行回归 |

### 架构（四层，单向依赖）

```
output 层    optical_hla.py      HLA 声明、显示过滤、接线
                ↓ 只调用，不含解码逻辑
协议层       cmis.py             CMIS 寄存器语义（按页分方法）
             cdb.py              CDB 命令通道（页 9Fh）
             sff8472.py          SFF-8472 A0h / A2h
                ↓ 只认 Access，不认识 I2C 帧
I2C 层       i2c_session.py      寻址、寄存器指针、页/银行、事务快照
                ↓ 只产出 Access，不认识寄存器含义
契约/数据    fields.py / regmap.py / decode_utils.py / saleae_compat.py
横切         compliance.py（校验）/ aggregate.py（摘要）/ user_config.py（配置）
```

**要加一个新页，只需要在 `cmis.py` 加一个 `_pageXX` 方法 + 在 `_PAGES` 注册一行**，其他文件都不用碰。

### 两条必须知道的约定

1. **协议解码器返回三种值**，语义必须严格区分：

   | 返回值 | 含义 |
   | :--- | :--- |
   | `Field(...)` | 解出一个字段 |
   | `CONSUMED` | 字节我认领了，但字段没凑齐（16 位值前半，已 stash） |
   | `None` | 不是我的寄存器，走通用寄存器回退 |

   把 `CONSUMED` 写成 `None` 会让 16 位值的前半字节被当裸寄存器打印、后半字节再解一次。

2. **帧不能重叠。** Logic 2 的数据表容不下一个横跨其他帧的帧 —— 分析会在抓包中途整个停住。
   详见 §5.1。

---

## 二、已支持的功能

### 2.1 协议与页覆盖

| 页 | 状态 | 内容 |
| :--- | :--- | :--- |
| **Lower Memory** | ✅ 完整 | 00h:0-127，页无关 |
| **Page 00h** | ✅ | 身份字符串（7 段）+ 介质类型 |
| **Page 01h** | ⚠️ **部分** | 只解了 2 个字段，见下 |
| **Page 02h** | ✅ 完整 | 36 组监督门限 |
| **Page 10h** | ✅ | DataPath 控制 |
| **Page 11h** | ✅ | DataPath 状态 + 监控量 + 标志 |
| **Page 9Fh** | ✅ | CDB 命令通道（**未经验证**，见 §3） |
| **SFF-8472 A0h** | ✅ | 厂商名 |
| **SFF-8472 A2h** | ✅ | DDM 五项监控 + 状态 |

**Page 01h 只解了两个字段**，因为只有它们被其他页引用：

- `01h:145` bits 2/1/0 = Aux1/2/3 监听量各是什么（激光器温度 / TEC 电流 / Vcc2 / 自定义）
- `01h:160` bits 4-3 = Tx 偏置电流倍率（x1 / x2 / x4）

> 其余 01h 内容（能力通告、支持的功能位图等）**未解码**。

### 2.2 Lower Memory（00h:0-127）

| 字段 | 位置 | 说明 |
| :--- | :--- | :--- |
| `Module Identifier` | 00h:0 | SFF-8024 标识符，同时决定套用哪套解码 |
| `CMIS Revision` | 00h:1 | |
| `Module State` | 00h:3 | 含 `[FAULT_FLAG]` 标记 |
| `Flags Summary (bank N)` | 00h:4-7 | 每 bank 一字节，指示哪个上页有待处理标志 |
| `Module Flags` | 00h:8 | CDB 完成 ×2、固件异常、DataPath/模块固件错误、状态变化 |
| `Global Flags` | 00h:9 | 温度/Vcc 的告警与警告 |
| `Aux 1/2 Flags`、`Aux 3 / Custom Flags` | 00h:10-11 | |
| `Module Temperature` | 00h:14-15 | S16 ÷256 °C |
| `Supply Voltage Vcc` | 00h:16-17 | U16 ×100 µV |
| `Aux1/2/3MonValue`、`CustomMonValue` | 00h:18-25 | 单位取决于 01h:145 |
| `Module Control` | 00h:26 | 低功耗、软件复位、bank 广播等 |
| `FW Active Revision` | 00h:39-40 | 全 `0xFF` 标记为 invalid |
| `Module Fault Cause` | 00h:41 | TEC 失控 / 存储器损坏 / 收发故障 / 温度 |
| `Media Type` | 00h:85 | MMF / SMF / 无源铜缆 / 有源电缆 / BASE-T |

### 2.3 Page 00h — 身份信息

七段字符串，**整串组装**而非逐字符：

| 字段 | 位置 |
| :--- | :--- |
| `Vendor Name` | 129-144 |
| `Vendor OUI` | 145-147（按十六进制渲染，不是字符） |
| `Part Number` | 148-163 |
| `Vendor Rev` | 164-165 |
| `Vendor Serial` | 166-181 |
| `Date Code` | 182-189 |
| `CLEI Code` | 190-199 |

读取过程中逐字符显示（`Vendor Name[130]: 'F' (0x46)`），读到**该段最后一个字节**时用整串取代那个字符。
**只有从首字节开始连续读取才会组装** —— 宁可不出整串，也不把残缺读取显示成完整字段。

### 2.4 Page 02h — 监督门限（36 组）

9 组 × 4 个门限（HighAlarm / LowAlarm / HighWarning / LowWarning）：

| 组 | 位置 | 单位 |
| :--- | :--- | :--- |
| `TempMon*` | 128-135 | °C |
| `VccMon*` | 136-143 | V |
| `Aux1/2/3Mon*`、`CustomMon*` | 144-175 | 取决于 01h:145 |
| `OpticalPowerTx*` | 176-183 | dBm / µW |
| `LaserBias*` | 184-191 | mA（受 01h:160 倍率影响） |
| `OpticalPowerRx*` | 192-199 | dBm / µW |

字段名沿用规范原名，便于 CSV 透视。Page 02h 整页只读，向它写入会被标记。

### 2.5 Page 10h / 11h — DataPath

**Page 10h（暂存控制集）**

- `DP Deinit Lanes`（128）—— 按 lane 位图，`0b` 初始化 / `1b` 去初始化
- `ApplyDPInit`（143）/ `ApplyImmediate`（144）—— 只写触发器，值为 lane 位掩码
- `Lane N DataPath Ctrl`（145-152）—— `AppSel` / `DataPathID` / `ExplicitControl`

**Page 11h（状态与监控）**

- `Lane N-M DP State`（128-131）—— 低 nibble 是低编号 lane
- `OutputStatusRx` / `OutputStatusTx`（132/133）—— 每 lane 1 bit，1 = 信号有效
- **20 个 per-lane 标志寄存器**（134-153）：DP 状态变化、Tx 故障/LOS/CDRLOL/自适应均衡、Tx 光功率与偏置的高低告警警告、Rx LOS/LOL/光功率
- **24 个 lane 监控量**：`OpticalPowerTx1-8`（154-169）、`LaserBiasTx1-8`（170-185）、`OpticalPowerRx1-8`（186-201）
- `ConfigStatus Lane N-M`（202-205）—— 配置命令执行结果（Table 8-101 全表）

lane 数默认 8，可由抓包中的应用描述符（00h:86-117）自动推断，或由配置强制。

### 2.6 Page 9Fh — CDB 命令通道

CDB 的交互形状决定了它不能按字节直译：**主机先写长度、校验和、负载，最后才写 CMDID；而写 CMDID 这个动作才是"发送命令"**。
所以命令头字节到达时还不能报告 —— 必须累积，在发送那一刻一次性输出：

```
CDB Command: CMD 0101h (Start Firmware Transfer) | LPL=2 EPL=0, check code OK
```

- 命令头 `CMDID` / `EPLLength` / `LPLLength` / `CdbChkCode`
- 回复头 `RPLLength` / `RPLChkCode`
- **校验和按规范原文实现**（p.320）：9Fh:128 到 9Fh:(136+LPLLength-1) 的算术和的**反码**，排除 133-135
- 校验失败 → 字段标 `CHECK CODE MISMATCH`，并作为 `CDB_CHECK_CODE`（error 级）合规事件上报

已命名的命令：`0000h` 查询状态、`0001h` 输入密码、`0100h` 取固件信息 …… `010Ah` 提交固件、`010Eh` 取回固件标签（共 20 条，见 `regmap.py`）。

⚠️ **本页未经真实模块验证**，见 §3。

### 2.7 输出模式

| 模式 | 输出 | 基线抓包行数 |
| :--- | :--- | :--- |
| **`Per Byte`**（默认） | 每寄存器字节一行，粒度最细 | 1753 |
| **`Transaction Summary`** | 每个完整 I2C 事务一行 | 88 |

摘要头部是**方向 / 从机地址 / 页 / 字节数**，后面跟解出的字段，**控制与状态类字段排在前面** ——
所以摘要被长度截断时，丢的是大堆监控量读数，而不是状态。

```
RD 0x50 pg02 73B | TempMonHighAlarmThreshold: 75.00 °C | TempMonLowAlarmThreshold: -5.00 °C | ...
WR 0x50 pg10 2B  | Page Select -> Page 0x10
```

### 2.8 一致性校验

把工具从**翻译器**变成**检查器**。7 条检查、6 种发现（`monitor_flag_mismatch` 与
`lane_monitor_flag_mismatch` 共用同一个发现 ID），设置里可关闭：

| 发现 | 严重度 | 检查什么 |
| :--- | :--- | :--- |
| `THRESHOLD_UNINITIALIZED` | warning | 门限未编程（寄存器原值为 `0x0000` 或全 1）。**按编码原值判定**，不是按换算后的物理量 —— 否则 `0 °C` 这种合法门限会被误报 |
| `THRESHOLD_ORDER` | warning | 报警与警告门限颠倒 |
| `MONITOR_FLAG_MISMATCH` | warning | 监控量超门限但标志位是清的 —— **能抓标志寄存器映射错位**。覆盖两级：模块级（00h:9 标志字节，温度/Vcc）与 per-lane 级（Page 11h 标志字节对应 Page 02h 门限） |
| `WRITE_TO_READ_ONLY` | warning | 写整页只读的 Page 02h / 11h |
| `PAGE_STALE` | info | 没选过页就读 upper memory |
| `CDB_CHECK_CODE` | error | CDB 校验和不匹配（由解码器上报） |

规则是**纯函数**：输入"本事务字段 + 累积状态"，输出发现列表。不碰 I2C 帧、不 import 任何解码器。

**触发与查表分离**：在本事务的字段上触发，用跨事务累积的状态查表 ——
因为门限在 02h 的扫描里读、监控量在另一个事务里读，不这样它们永远对不上。

**已判为未编程的门限不参与比较**：拿一个未编程的门限去和监控量比，只会产出一串连锁误报。

### 2.9 不确定性配置（`user_config.json`）

三级优先：**显式配置 ＞ 抓包读到的值 ＞ 内置默认值**，只有落到第三级才输出假设标记。

| 键 | 作用 |
| :--- | :--- |
| `aux_monitor_functions` | Aux1/2/3 与 Custom 监听量各是什么 |
| `tx_bias_scaling` | 偏置电流倍率（`auto` 或 `1`/`2`/`4`） |
| `lane_count` | lane 数（`auto` 或 1-8） |
| `show_assumption_caveats` | 是否输出 `[assumed ...]`、`(x1 assumed)` 标记 |

输出标记的语义：

| 例子 | 含义 |
| :--- | :--- |
| `35.50 °C` | 函数和量纲都确定 |
| `35.50 °C [assumed laser_temperature]` | 函数是猜的 |
| `9088 (raw) [assumed custom]` | **双重不确定** —— 函数是猜的，且该函数无已确立的换算系数 |
| `6.54 mA (x1 assumed)` | 倍率未读到，可能偏小 2/4 倍 |

### 2.10 显示过滤

沿用 Logic 2 的三档：`Show All` / `Control & State Only` / `Data & Registers Only`。
摘要模式下按内容归类 —— 含状态变更的事务归 `control`，纯寄存器流量归 `data`。

---

## 三、验证状态（重要）

不同部分的验证强度**差别很大**，用之前请对照这张表：

| 部分 | 验证方式 | 置信度 |
| :--- | :--- | :--- |
| Lower Memory 全字段 | 真实抓包 + 原始字节独立复算 | **高** |
| Page 02h 门限 | 真实抓包，且每组内部排序自洽（HighAlarm>HighWarn>LowWarn>LowAlarm） | **高** |
| Page 11h 状态/监控量/标志 | 真实抓包 | **高** |
| Page 10h DataPath | 真实抓包 | 中（该抓包只读部分寄存器） |
| Page 00h 身份字符串 | 仅单元测试 | 中 |
| SFF-8472 A2h DDM | 原作者的仿真脚本 | 中 |
| SFF-8472 A0h 厂商名 | 仿真脚本 + 单元测试 | 中 |
| **Page 9Fh CDB** | **仅单元测试，抓包从未选过此页** | **低 —— 首次接真实模块请重点核对校验和** |
| 一致性校验规则 | 单元测试 + 真实抓包（13 个真实发现） | 中高 |
| 事务摘要模式 | 真实抓包，88/88 事务 | 高 |

> **CDB 特别提示**：如果接入真实模块后**每个命令都报 `CHECK CODE MISMATCH`**，
> 那大概率是"反码"的理解与模块实现不一致（规范写的是 one's complement，与 two's complement 差 1）。
> 改 `cdb.py` 的 `_check_verdict` 一处即可。

---

## 四、尚未实现 / 待未来

### 4.1 固件升级流程状态机（优先级最高）

CDB 的消息块已解（§2.6），但**升级流程本身没有跟踪**。目前你能看到每条命令，
但看不到"这次下载进行到哪一步了"。

要做的是跟踪状态迁移并汇总：

```
Start Firmware Transfer → Write Firmware Block ×N → Complete → Copy → Run → Commit
```

**为什么没做**：这需要真实的 CDB 抓包才能验证状态迁移的正确性。
在没有任何真实数据的情况下写一个状态机，只会产出一大坨无法验证的代码 ——
这正是本项目一路在避免的。

**需要什么**：一次真实的固件升级抓包（`.sal`），读过的页包含 `0Dh` 和 `9Fh`。

### 4.2 未解码的页

| 页 | 内容 | 备注 |
| :--- | :--- | :--- |
| **04h** | 激光器能力（波长栅格、微调范围、可编程功率范围） | 寄存器表有定义 |
| **12h** | 数据处理 / 主机性能监控 | 寄存器表有定义；`Flags Summary` 的 bit1 |
| **13h** | 同上 | 寄存器表有定义 |
| **14h** | 按 bank 的标志 | `Flags Summary` 的 bit2 |
| **0Dh** | **固件管理寄存器** | CDB 的寄存器级对应物，与 §4.1 一起做 |
| **2Ch** | —— | `Flags Summary` 的 bit3 |
| **A0h-AFh** | CDB 扩展负载页（EPL） | 大于 120 字节的固件块走这里 |
| **03h / 05h** | —— | 未出现在手头寄存器表中，需查规范确认是否存在 |

### 4.3 其他未实现

| 项 | 说明 |
| :--- | :--- |
| **Page 01h 完整解码** | 目前只解了 2 个被引用的字段；能力通告、功能位图未解 |
| **TEC 电流量纲** | `01h:145` 能告知 Aux 监听 TEC 电流，但规范未给出其换算系数，故只输出原始值 |
| **10h:213-232 lane 掩码** | 标志位的掩码寄存器未解码 |
| **11h:235-239 Data Path Conditions** | CMIS 5.4 重构过，位图待确认 |
| **SFF-8636 专用分支** | 目前只识别标识符，无专用寄存器解码 |
| **SFF-8472 A2h 门限（页 1）** | 只解了实时值，未解告警/警告门限 |
| **ACK/NACK 感知** | 未利用 I2C 的 ACK 位；NACK 通常意味着模块不存在 |
| **10 位 I2C 寻址** | 未支持 |
| **重复地址/异常事务检测** | 未做 |

### 4.4 校验规则可扩展

`compliance.py` 加一条规则 = 写一个函数 + 一个 `@rule` 装饰器。候选：

- DataPath 已激活但 `AppSel=0`
- DP 状态机非法跳转（需 Table 6-18 转移表）
- 模块处于 `Fault` 态但 `ModuleFaultCause` 为 0
- 固件版本为 `0xFF.0xFF`（无效加载）却报告 `Ready`
- 门限与监控量长期矛盾（需跨多个事务统计）
- ~~per-lane 监控量与 Page 11h 标志位的交叉检查~~ —— 已实现（见 §2.8）

---

## 五、已知限制

### 5.1 帧不能重叠（平台硬约束）

Logic 2 的数据表**容不下一个横跨其他帧的帧**。实测（真实抓包）：

| 场景 | 结果 |
| :--- | :--- |
| 逐字节帧 + 横跨事务的聚合帧 | 1679 行，90 个聚合只剩 **1** |
| 逐字节帧 + 零宽聚合帧 | 2664 行，90 个聚合全在 |
| **只有横跨事务的聚合帧** | **90 行，90 个聚合全在** ✅ |

不是"丢几帧"，是**分析在抓包中途整个停住**。

**影响**：`Per Byte` 和 `Transaction Summary` 必须互斥，没有"两者都要"。
摘要模式下也不能有任何逐字节帧，包括未解码寄存器的裸显示。

### 5.2 一致性发现是逐次触发的

宿主每读一次、就报一次。同一条问题会出现多次（基线抓包中 `TempMonLowWarningThreshold is 0` 出现 13 次）。
这在时间轴视图上是对的（你确实能看到每次读取都复现），但用 CSV 分析时需自行去重。

### 5.3 校验规则有意保持克制

- **Aux / Custom 门限不做"未编程"判定** —— 不知道量纲就无法区分"0 = 未编程"和"0 = 不支持该监听量"
- **没见过标志字节就不判定标志不匹配** —— 没有依据就沉默，不假设

**误报比漏报更有害**：它训练人忽略输出。

### 5.4 日志文件竞争

`hla_debug.log` 写在扩展目录。若同时运行 Logic 2 和测试脚本，Windows 下 1 MB 轮转会失败并打印回溯
（logging 自己会兜住，不影响解码）。

### 5.5 热重载

改任何模块后在 Logic 2 里按 `Ctrl + R` 即可，无需重启。
`optical_hla.py` 顶部会主动丢弃子模块缓存 —— 否则改了 `regmap.py` 之类的文件热重载会**静默继续跑旧代码**。

---

## 六、开发与验证

```bash
cd logic2

# 契约测试（秒级，必须始终通过，且一行不改）
python tools/test_optical_simulation.py

# 寄存器语义 + 配置 + 输出模式 + 合规规则（83 项，均标注规范表号）
python tools/test_cmis_registers.py

# 真实抓包回归：跑一遍样例抓包并与基线逐行 diff
python tools/regression_run.py --out new.csv --diff samples/cmis_iic_baseline.csv
```

**纯重构必须得到 `IDENTICAL`。** 如果 diff 出东西，先判断是有意的行为变更还是 bug ——
这条判据在本项目中已经拦下 4 个真实 bug：

| bug | 表现 |
| :--- | :--- |
| 寄存器指针不再递增 | 后续字节被反复当成标识符重新分类，页上下文错乱 |
| `CONSUMED` 语义丢失 | 16 位值前半被当裸寄存器打印，凭空多出 494 行 |
| 摘要模式漏改通用回退 | 分析在第 270 帧（共约 2944 帧）整个停住 |
| 写只读页误报 | 选页写操作被当成写 page 02h，39 个发现全是假的 |

### 样例数据与基线

| 文件 | 说明 |
| :--- | :--- |
| `samples/CMIS_IIC.sal` | 真实 QSFP-DD 模块抓包，**随仓库分发**，供他人快速验证 |
| `samples/cmis_iic_baseline.csv` | 该抓包的期望解码输出，**当前正确基线** |

各阶段的开发快照（`stage0_baseline` … `stage5`）留在 `_local/baselines/`，**不进版本库** ——
它们是过程中的中间态，对使用者没有价值。需要时可在本地重新生成。

> `stage0_baseline.csv` 记录的是 v1.0.0 的原始行为（**含 8 处寄存器误读**），
> 保留它只是为了对照"改了什么"，**不要拿它当正确性依据**。

### 回归驱动说明

`tools/regression_run.py` 通过 Logic 2 的 MCP 接口驱动，有几个**必须遵守**的点：

1. `add_high_level_analyzer` **必须显式传全部 settings**，否则直接被拒
2. 导出时**必须显式指定分析器**（`analyzers: [{"analyzerId": N}]`），否则 HLA 输出不会被导出
3. `extensionDirectory` 传参会让 Logic 2 **把该目录持久化注册** —— 别拿它指向临时探针目录

---

## 七、规范参考

| 规范 | 位置 |
| :--- | :--- |
| **OIF-CMIS-05.4**（权威） | `Documents/协议书/OIF-CMIS-05.4.pdf` |
| SFF-8472 | `Documents/协议书/SFF-8472.pdf` |
| SFF-8436 | `Documents/协议书/sff-8436.pdf` |
| 寄存器表（第三方，CMIS 5.3） | `Downloads/cmis-module-manager/cmis_registers.py` |

> 第三方寄存器表**并非总是准确**：ConfigStatus 编码它缺了 `8h`、把 `0xC` 归在负结果里；
> 早期还差点因它误判 DP 状态编码。**以规范原文为准，表只作交叉参考。**

PDF 页 = 规范页 + 1。命令行查规范：

```bash
pdftotext -layout -f <PDF页> -l <PDF页> "路径/OIF-CMIS-05.4.pdf" - | grep -A20 "Table 8-xx"
```
