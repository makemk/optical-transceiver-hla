# 光模块协议解析插件 (Optical Transceiver Protocol Decoder)
### Saleae Logic 2 高级协议分析器 (High-Level Analyzer, HLA)

本插件专为光通信研发、光模块软硬件工程师设计，可在 Saleae Logic 2 软件中直接将 I2C 底层波形解码为光模块标准协议字段。

---

## 核心特性

- **多标准兼容**：
  - **CMIS (QSFP-DD / OSFP / SFP-DD)**：完整支持 CMIS 3.0 / 4.0 / 5.0，解析模块状态机（Module State）、8通道 DataPath 控制（AppSel / DataPathID）、DataPath 状态机、分页选择（Page Select 0x00/0x02/0x10/0x11）、全局标志与告警（Global Flags / Alarms）、温度与工作电压。
  - **SFF-8472 (SFP / SFP+ / SFP28)**：解析 A2h 实时诊断监控（DDM/DOM），包含温度、工作电压 Vcc、TX偏置电流 Bias、TX发送光功率、RX接收光功率、控制状态（TxDisable / TxFault / RxLOS）。
  - **SFF-8436 (QSFP+ / QSFP28)**：解析模块标识符（Identifier）、厂商信息（Vendor Name）等。
- **智能分轨过滤 (Display Filter)**：
  - 支持 `Show All`（完整显示所有交互）；
  - 支持 `Control & State Only`（仅提取 DataPath 控制、模块状态、分页切换等核心控制帧）；
  - 支持 `Data & Registers Only`（仅显示大量寄存器 Read / Write 读写数据）。
- **双轨独立着色**：可同时挂载两个分析器实例，实现控制轨与数据轨在时间轴上拥有完全独立的背景底色。
- **纯文本无多余前缀**：输出格式简洁专业，兼容 CSV 表格导出与二次数据分析。

---

> 📋 **功能全景、验证状态、未实现清单**：见项目根目录的 [`FEATURES.md`](../../FEATURES.md)。
> 本 README 侧重安装与使用，`FEATURES.md` 侧重"支持什么 / 什么已验证 / 还差什么"。

## 源码结构（v2.0.0 起分层）

代码按**职责分层**，每层只依赖它下面的一层。要加新寄存器，通常只需要动协议层的一个文件。

```
output 层    optical_hla.py    HLA 声明、显示过滤、把各层接起来        209 行
                                        ↓ 只调用，不含解码逻辑
协议层       cmis.py           CMIS 寄存器语义（按页分方法）          186 行
             sff8472.py        SFF-8472 A0h/A2h                     97 行
                                        ↓ 只认 Access，不认识 I2C 帧
I2C 层       i2c_session.py    寻址、寄存器指针、页/银行选择         189 行
                                        ↓ 只产出 Access，不认识寄存器含义
契约         fields.py         Access / Field / 装配器 / CONSUMED     126 行
数据         regmap.py         地址常量与编码表（标注规范表号）       169 行
             decode_utils.py   定点换算、位域展开、ASCII            137 行
兼容         saleae_compat.py  Logic 2 API 导入 + 离线测试桩          69 行
```

**两条关键约定**（改代码前务必知道）：

1. **`i2c_session.py` 不知道任何寄存器含义**，协议层也不知道 I2C 帧长什么样。加一个新页 = 在 `cmis.py` 加一个 `_pageXX` 方法 + 在 `_PAGES` 里加一行，其他文件都不用碰。
2. **协议解码器返回三种值**，含义必须严格区分：

   | 返回值 | 含义 |
   | :--- | :--- |
   | `Field(...)` | 解出一个字段，渲染出来 |
   | `CONSUMED` | **这个字节我认领了，但字段还没凑齐**（16 位值的前半，已 stash） |
   | `None` | 不是我的寄存器，走通用寄存器回退显示 |

   把 `CONSUMED` 写成 `None` 会导致 16 位值的前半字节被当成裸寄存器打印、后半字节再解一次 —— 这个 bug 真实发生过，靠真实抓包回归才发现。

### 改代码后怎么验证

```bash
python tools/test_optical_simulation.py    # 契约测试，秒级
python tools/test_cmis_registers.py        # 寄存器语义测试（37 项，均标注规范表号）
python tools/regression_run.py --out new.csv --diff tools/baselines/stage2_layered.csv
```

第三条会用 MCP 把真实抓包 `CMIS_IIC.sal` 跑一遍并和基线逐行 diff。**纯重构应该得到 `IDENTICAL`**；如果 diff 出东西，先判断是有意的行为变更还是 bug。

---

## 不确定性配置（`user_config.json`）

有些 CMIS 字段的含义**取决于另一个寄存器**，而那个寄存器不一定出现在你的抓包里。
这种情况下解码器不会硬猜，而是按三级优先取用：

> **你在 `user_config.json` 里的显式设定 ＞ 抓包本身读到的值 ＞ 内置默认值**

只有落到第三级时，输出才会带标记告诉你这是假设。

### 配置项

编辑扩展目录下的 `user_config.json`，改完在 Logic 2 里按 **Ctrl+R** 生效。

| 键 | 作用 | 默认 |
| :--- | :--- | :--- |
| `aux_monitor_functions` | Aux1/2/3 与 Custom 监听量各是什么，决定换算系数和单位 | `auto` |
| `tx_bias_scaling` | Tx 偏置电流倍率（x1/x2/x4），可填 `1`/`2`/`4` 强制 | `auto` |
| `lane_count` | 模块 lane 数（1-8），影响位图展开与监控量范围 | `auto` |
| `show_assumption_caveats` | 是否输出 `[assumed ...]`、`(x1 assumed)` 这类标记 | `true` |

`auto` = 从抓包推断；填具体值 = 强制指定并**去掉**假设标记。
删掉某个键 = 用内置默认值。文件写坏了会记日志并整体回退，不会让解码器崩。

### 输出标记怎么读

| 例子 | 含义 |
| :--- | :--- |
| `35.50 °C` | 函数和量纲都确定 |
| `35.50 °C [assumed laser_temperature]` | `01h:145` 没读过，按规范 `0b` 默认值当成了激光器温度 |
| `9088 (raw) [assumed custom]` | 不仅是假设，这个函数**根本没有已确立的换算系数**，所以只给原始值 |
| `6.54 mA (x1 assumed)` | `01h:160` 没读过，按 x1 算；**可能偏小 2 倍或 4 倍** |

### 为什么这样设计

`Aux1/2/3` 的单位取决于 `01h:145` 的 bits 2/1/0：

| 位 | Aux | `0b` | `1b` |
| :--- | :--- | :--- | :--- |
| bit2 | Aux3 | 激光器温度 | Vcc2 |
| bit1 | Aux2 | 激光器温度 | TEC 电流 |
| bit0 | Aux1 | 厂家自定义 | TEC 电流 |

其中只有**激光器温度**（1/256 °C）和**电源电压**（100 µV）有规范确立的换算系数。
TEC 电流和厂家自定义没有，所以解码器宁可给原始值也不标一个可能错的单位。

抓包里读过 `01h:145` 就自动填好，完全不用配。

---

## 输出模式（`Output Mode`）

分析器设置里多了一个下拉项：

| 模式 | 输出 | 同一份抓包的行数 |
| :--- | :--- | :--- |
| **`Per Byte`**（默认） | 每个寄存器字节一行，粒度最细 | 1740 |
| **`Transaction Summary`** | 每个完整 I2C 事务一行 | **88** |

摘要行形如：

```
RD 0x50 pg02 73B | TempMonHighAlarmThreshold: 75.00 °C | TempMonLowAlarmThreshold: -5.00 °C | ...
WR 0x50 pg10 2B  | Page Select -> Page 0x10
RD 0x50 pg10 33B | DP Deinit Lanes: 0x00 (initialize all lanes) | ApplyDPInit: no lanes selected | ...
```

头部是**方向 / 从机地址 / 页 / 字节数**；后面是解出的字段，**控制与状态类字段排在前面** ——
所以摘要因长度被截断时，丢的是大堆监控量读数，而不是状态。

### 为什么只有两个模式，没有「两者都要」

这是**实测出来的硬约束**，不是设计取舍。Logic 2 的数据表**无法容纳一个横跨其他帧的帧**：

| 实测（用一个临时探针扩展量的，已删除） | 结果 |
| :--- | :--- |
| 逐字节帧 + 横跨事务的聚合帧 | 1679 行，90 个聚合只剩 **1** |
| 逐字节帧 + 零宽聚合帧 | 2664 行，90 个聚合全在 |
| **只有横跨事务的聚合帧** | **90 行，90 个聚合全在** ✅ |

而且不是"丢几帧"那么简单：**分析会在抓包中途整个停住**。

这个坑在实现时立刻咬了一次 —— 我漏改了通用寄存器回退路径，它仍在逐字节输出，
结果分析在第 270 帧（抓包共约 2944 帧）就停了，只产出 6 个事务。修掉之后拿到完整的 88 个。

**所以摘要模式下不能有任何逐字节帧**，包括未解码寄存器的裸显示 —— 那些由头部的字节数代表。

---

## CDB 命令（Page 9Fh）

CDB（Command Data Block）是模块的命令通道，固件升级就走它。**9Fh:128-133 命令头 / 134-135 回复头 / 136-255 本地负载（LPL，120 字节）**。

关键在于 CDB 的交互形状决定了它不能按字节直译：

> 主机先写长度、校验和、负载，**最后才写 CMDID**。而**写 CMDID 这个动作本身才是"发送命令"**。

所以命令头字节到达时还不能报告 —— 等到 CMDID 过去时，描述它的那些字节已经在身后了。`cdb.py` 会把它们累积起来，
在命令发送的那一刻一次性报告：

```
CDB Command: CMD 0101h (Start Firmware Transfer) | LPL=2 EPL=0, check code OK
```

**校验和**按规范原文实现（p.320）：`CdbChkCode` = 9Fh:128 到 9Fh:(136+LPLLength-1) 的算术和的**反码**，
**排除** 9Fh:133-135 —— 回复头永远不在求和范围内，而 EPLLength 和 LPLLength 永远在。

校验不通过时，除了字段文本标出 `CHECK CODE MISMATCH`，还会作为 `CDB_CHECK_CODE` 事件（error 级）上报。

已命名的命令 ID 见 `regmap.py` 的 `CDB_COMMANDS`（`0000h` 查询状态 到 `010Eh` 取回固件标签）。

> ⚠️ **这份实现没有经过真实模块验证** —— 开发时手头的抓包从未选过 page 9Fh，只有单元测试覆盖。
> 偏移已对着规范逐条核对，但首次接入真实模块时请留意校验和判定。

---

## 一致性校验（`Consistency Checks`）

解码器只能说"这个寄存器里是什么"。它**说不了内容之间是否自相矛盾** —— 而模块出问题时，那往往才是关键。
这一层就是干这个的：把工具从**翻译器**变成**检查器**。

设置里的下拉项：`Warnings + Errors`（默认）/ `Errors Only` / `Off`。
发现的问题作为 `optical_compliance` 事件输出，**不改动也不抑制任何解码字段**。

| 规则 | 严重度 | 检查什么 |
| :--- | :--- | :--- |
| `THRESHOLD_UNINITIALIZED` | warning | 监督门限为 0，即未编程 —— 任何与它的比较都没有意义 |
| `THRESHOLD_ORDER` | warning | 报警与警告门限**颠倒**（如 HighWarning 高于 HighAlarm），模块要么永远不预警，要么报完警才预警 |
| `MONITOR_FLAG_MISMATCH` | warning | 监控量**超出自己的报警门限**，但对应标志位是清的 —— 两者必有一个在说谎。**这条能抓出标志寄存器映射错位** |
| `WRITE_TO_READ_ONLY` | warning | 向规范定义为整页只读的 Page 02h / Page 11h 写入 |
| `PAGE_STALE` | info | 从未选过页就读 upper memory，等于隐式按 page 00h 解释 |

### 运行方式

规则是**纯函数**：输入"本事务解出的字段 + 累积状态"，输出发现列表。
它们不碰 I2C 帧、不渲染任何东西、也不 import 任何解码器 —— 可以单独读懂、单独测试。

**触发与查表是分开的**：规则在本事务的字段上**触发**，但用**跨事务累积的状态**查表。
因为门限在 page 02h 的扫描里读，监控量在另一个事务里读 —— 不这样它们永远对不上。
这样也避免了「同一个矛盾在每个后续事务里重复上报」。

### 实测

本机那份抓包上有 **13 个真实发现**（都是 `THRESHOLD_UNINITIALIZED`）：

```
[THRESHOLD_UNINITIALIZED] TempMonLowWarningThreshold is 0 - threshold not programmed
```

模块的温度低警告门限确实是未编程的（同一份抓包里解出来就是 `0.00 °C`）。

`MONITOR_FLAG_MISMATCH` 在这份抓包上**没有触发，这是正确的** —— 实测 Vcc 3.591 V 超出 3.465 V 门限时，
`VccHighWarn` 标志确实是置位的，两者一致。

### 两条刻意的克制

- **Aux / Custom 门限不做「未编程」判定。** 它们的量纲取决于 `01h:145`，在不知道量纲时就无法区分
  "0 = 未编程" 和 "0 = 该监听量不支持"。**误报比漏报更有害** —— 它训练人忽略输出。
- **没见过标志字节就不判定 `MONITOR_FLAG_MISMATCH`。** 没有标志字节就没有依据说"标志是清的"，
  此时保持沉默而不是假设。

### 已知限制

发现是**逐次触发**的：宿主每读一次、就报一次。所以同一条问题会出现多次（那份抓包里是 13 次）。
这在时间轴视图上是对的（你确实能看到每次读取都复现），但用 CSV 分析时需要自行去重。

---

## 插件安装步骤

### 方式一：通过 Logic 2 界面加载（推荐，最简单）

1. **解压插件包**：
   将压缩包解压到您常用的工作目录（建议路径不要包含特殊符号）。文件夹内包含：
   - `extension.json`（插件配置文件）
   - `optical_hla.py`（解码核心源码）
   - `README.md`（使用说明文档）

2. **在 Logic 2 中加载**：
   - 打开 **Saleae Logic 2** 软件；
   - 点击左侧垂直边栏的 **Extensions**（扩展图标，类似三个拼图/积木的图标）；
   - 点击 Extensions 面板右上角的 **`...`（三个点）**；
   - 在弹出的下拉菜单中点击 **Load Existing Extension...**；
   - 在弹出的文件选择框中，选中解压出来的 **`optical_transceiver_hla` 文件夹**，点击“选择文件夹”。

3. **加载成功**：
   在 Installed 列表中会立即看到 **`Optical Transceiver Decoder`**，表明插件已成功安装！

---

## 如何使用与配置

### 步骤 1：添加基础 I2C 分析器

光模块 HLA 是建立在 I2C 基础分析器之上的，必须先配置好 I2C：

1. 打开录制好的波形文件（`.sal`）或准备实时抓包；
2. 在右侧 **Analyzers** 面板中点击 **`+`** 号，选择 **`I2C`**；
3. **正确配置硬件引脚**（切记勿反接）：
   - **SCL (时钟线)**：选择规整方波对应的通道；
   - **SDA (数据线)**：选择随数据高低跳变对应的通道；
4. 点击 **Save** 保存。

### 步骤 2：挂载光模块协议分析器

1. 再次在右侧 **Analyzers** 面板中点击 **`+`** 号；
2. 在列表中找到并点击 **`Optical Transceiver Decoder`**；
3. **配置参数**：
   - **Input Analyzer**：选择刚刚添加的 `I2C`；
   - **Module Standard**：
     - `Auto-Detect`（自动识别，推荐）
     - 或强制指定 `CMIS (QSFP-DD/OSFP)` / `SFF-8472`；
   - **Display Filter**：
     - `Show All`：显示全部解码字段；
     - `Control & State Only`：仅显示控制与状态；
     - `Data & Registers Only`：仅显示寄存器读写。
4. 点击 **Save**，波形时间轴上就会立即渲染出光模块协议字段！

---

## 进阶玩法：双轨独立着色技巧

如果您希望 **DataPath 控制 / 状态机** 与 **普通的 Read / Write 读写** 在时间轴上显示为**完全不同的背景颜色**：

1. 添加第一个 Optical Transceiver 分析器：
   - Label 命名为：`CMIS Control`
   - Display Filter 选择：`Control & State Only`
   - 在右侧 Analyzers 面板中点击色块，选为 **亮黄色** 或 **紫色**。
2. 添加第二个 Optical Transceiver 分析器（挂在同一个 I2C 下）：
   - Label 命名为：`CMIS Data`
   - Display Filter 选择：`Data & Registers Only`
   - 点击色块选为 **浅绿色** 或 **青蓝色**。
3. **效果**：时间轴上会呈现出上下两条独立音轨般的波形气泡，一轨专门盯控制状态，另一轨专门显示寄存器数据，底色分明！

---

## 解码字段速查表

> **v2.0.0 重要更正**：下方带 ⚠️ 的条目在 v1.0.0 中解错了寄存器，输出的是别的字节。
> 这些偏移现已按 OIF-CMIS-05.4 逐条核对并修正。历史 CSV 中这几项不可信，请重新抓取。

| 字段类别 | 解析内容示例 | 规范对应 |
| :--- | :--- | :--- |
| **模块状态** | `Module State: PwrUp (Powering Up)` / `Ready` | CMIS 00h:3 bits[3:1] |
| ⚠️ **模拟量监控** | `Module Temperature: 39.64 °C` / `Supply Voltage Vcc: 3.591 V` | CMIS **00h:14-15 / 16-17**（v1.0.0 误读 85-88） |
| ⚠️ **全局标志** | `Global Flags: VccHighWarn` / `OK (Normal)` | CMIS **00h:9**（v1.0.0 误读字节 4） |
| **分页标志汇总** | `Flags Summary (bank 0): Page11h` / `OK (Normal)` | CMIS 00h:4-7（每 bank 一字节） |
| **模块级标志** | `Module Flags: ModuleFirmwareError, ModuleStateChanged` | CMIS 00h:8（CDB 完成、固件异常、状态变化） |
| **Aux 标志** | `Aux 1/2 Flags: Aux2LowWarn` / `Aux 3 / Custom Flags: ...` | CMIS 00h:10 / 00h:11 |
| **模块控制** | `Module Control: LowPwrAllowRequestHW` | CMIS 00h:26（Table 8-11） |
| **Aux 监控量** | `Aux1MonValue: 35.50`（**不带单位**，见下方说明） | CMIS 00h:18-25（Table 8-10） |
| **固件版本** | `FW Active Revision: 1.2` / `invalid (0xFF.0xFF)` | CMIS 00h:39-40（Table 8-15） |
| **故障原因** | `Module Fault Cause: TEC runaway` | CMIS 00h:41（Table 8-16） |
| **介质类型** | `Media Type: SMF (0x02)` | CMIS 00h:85（Table 8-20） |
| **身份字符串** | `Vendor Name: 'FINISAR CORP.'` / `Part Number: 'TR-F401-XXX'` | CMIS 00h:129-199（Table 8-26，共 7 段） |
| **厂商 OUI** | `Vendor OUI: 00-90-65`（按十六进制，不按字符） | CMIS 00h:145-147 |
| **DataPath 控制** | `Lane 1 DataPath Ctrl: AppSel=1, DataPathID=0, ExplicitControl=0` | CMIS 10h:145-152（bit3-1 是 DPIDX） |
| ⚠️ **DataPath 状态** | `Lane 1-2 DP State: Lane 1: DPActivated...` | CMIS **11h:128-131**（v1.0.0 误读 134-137） |
| **DP 去初始化** | `DP Deinit Lanes: 0x05 (deinit lane 1, 3)` | CMIS 10h:128（按 lane 位图） |
| **Apply 触发** | `ApplyDPInit: lane 1, 2` / `ApplyImmediate: no lanes selected` | CMIS 10h:143 / 10h:144 |
| **Tx/Rx 标志** | `Tx Fault Flags: 0x05 (1, 3)` / `Rx LOS Flags: 0x00 (none)` | CMIS 11h:134-153（展开到 lane） |
| **监督门限** | `TempMonHighAlarmThreshold: 75.00 °C` / `VccMonLowAlarmThreshold: 2.970 V` | CMIS Page 02h 128-199（36 组，全部解出） |
| **Lane 监控量** | `OpticalPowerTx1: -2.60 dBm (550.0 uW)` / `LaserBiasTx1: 6.54 mA` | CMIS 11h:154-201（每 lane 2 字节） |
| **配置结果** | `ConfigStatus Lane 1-2: Lane 1: ConfigSuccess, ...` | CMIS **11h:202-205**（每 lane 4 bit，Table 8-101） |
| **输出有效指示** | `OutputStatusRx: 0x03 (1, 2)` | CMIS 11h:132/133（每 lane 1 bit） |
| **偏置电流倍率** | `TxBiasCurrentScalingFactor: x2` | CMIS 01h:160 bits4-3 |
| **分页切换** | `Page Select -> Page 0x10` | Write to Reg 127 |
| **寄存器定位** | `Set Reg Address -> 0x80 (128)` | I2C Write First Byte |
| **只读操作** | `Read Reg[0x05] = 0x00` | I2C Read Data |
| **写入操作** | `Write Reg[0x80] = 0x01` | I2C Write Data |
| **SFF-8472 DDM** | `Module Temperature: 35.50 °C` / `RX Optical Power: -3.77 dBm (420.0 uW)` | SFF-8472 A2h 96-110（未受影响） |

**v1.0.0 的三个已证实的误读**（详见交付说明）：

1. `Module Temperature` / `Supply Voltage Vcc` 读的是 00h:85-88 —— 那是 **Media Type 和应用描述符**，不是监控量。抓包实测该处应为 39.64 °C / 3.591 V。
2. `Global Flags` 读的是字节 4（**Flags Summary**），导致告警方向可能反转：实测应为 `VccHighWarn`（3.591 V 超过 3.465 V 门限），而 v1.0.0 报 `VccLowWarn`。
3. `DataPath State` 读的是 11h:134-137 —— 那是 **DPStateChangedFlag 和 Tx 故障/LOS 标志寄存器**。真正的 DP 状态在 11h:128-131。若抓包未读取 128-131，修正后不会出现 DP State 字段（这是正确的，v1.0.0 是在编造）。

**身份字符串（厂商名 / 型号 / 序列号 / 日期码 / CLEI）** 现在会**整串输出**：
读取过程中仍逐字符显示（`Vendor Name[130]: 'F' (0x46)`），读到该段**最后一个字节**时，
用组装好的整串取代那一个字符（`Vendor Name: 'FINISAR CORP.'`）—— 整串已包含那个字符，所以信息不丢。

**只有从该段首字节开始连续读取才会组装。** 如果宿主从中间开始读、或读到一半就跳走，
则只显示逐字符结果 —— 宁可不出整串，也不把一个残缺的读取显示成完整字段。

**v2.0.0 新增**：Page 02h 的 36 组监督门限全部解出（v1.0.0 在该页只输出没有字段名的裸寄存器事件）。
字段名沿用规范原名便于 CSV 透视，例如 `TempMonHighAlarmThreshold`、`OpticalPowerTxLowWarningThreshold`。
`Aux1/2/3Mon*` 与 `CustomMon*` 的物理单位取决于 01h:145 选择的监听功能（激光器温度 vs 附加电源轨），该寄存器尚未解码，
因此这几项只输出按 1/256 换算的数值、**不带单位后缀** —— 是刻意的，避免标错单位。

**关于偏置电流的 `(x1 assumed)` 后缀**：LaserBias 监控量和门限都要乘 `01h:160` 的 TxBiasCurrentScalingFactor（x1/x2/x4）。
如果抓包里没有读过 page 01h，这个倍率就无从得知，此时输出会带 `(x1 assumed)` 后缀提醒你 ——
数值**可能偏小 2 倍或 4 倍**。想让倍率自动生效，抓包时确保读取过 `01h:160`。

---

## 常见问题 (FAQ)

1. **为什么添加了解析器，波形上一个气泡都没有？**
   - 请检查基础 I2C 分析器的 SDA 和 SCL 引脚是否接反了。如果方波时钟线被误设成了 SDA，I2C 无法触发任何有效帧。
2. **修改了脚本后如何即时生效？**
   - 在 Logic 2 左侧 Extensions 面板 -> Installed 列表中，找到 `Optical Transceiver Decoder`，点击右侧的刷新图标（Reload）或按快捷键 `Ctrl + R` 即可热重载。
   - 从 v2.0.0 起解码器拆成了多个模块（`optical_hla.py` / `cmis` 相关逻辑 / `regmap.py` / `decode_utils.py` / `saleae_compat.py`）。`optical_hla.py` 顶部有一段代码会在重载时主动丢弃这些子模块缓存，否则改了 `regmap.py` 之类的文件按 `Ctrl + R` 会**静默继续跑旧代码**。修改任何模块后热重载均生效，无需重启 Logic 2。
3. **如何导出解码表格？**
   - 点击 Logic 2 右上角菜单 -> `Export Data...`，勾选 Optical Transceiver Decoder 即可导出为包含时间戳、字段名、取值的标准 `.csv` 文件。
