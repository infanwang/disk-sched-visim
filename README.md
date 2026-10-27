# 磁盘调度仿真 · Disk Scheduling Lab

六种磁盘调度算法的可视化仿真器：**Web 界面 + 命令行**双入口，同一套算法内核，
支持算法选择、访问序列生成、初始状态设置、指标对比与自动生成分析报告。

两种仿真模式：

- **静态批处理**：所有请求同时到达，比较总寻道与平均寻道（教材口径）。
- **动态到达**：请求带到达时刻，磁头只从「已到达未服务」队列里挑选，
  能真实复现 SSTF 的饥饿、SCAN 的等待上界。

零第三方依赖，`Python 3.9+` 直接跑。

![深海夜航主题](预览_深海夜航.png)

```
FCFS  先来先服务
SSTF  最短寻道时间优先
SCAN  扫描算法（电梯）
C-SCAN 循环扫描
LOOK  扫到最后一个请求就反向
C-LOOK 扫到最后一个请求就空返
```

## 一键部署

三种入口，选一个就行。

**1. Windows 双击**

双击 `一键启动.bat`。它会自动找 Python（py 启动器或 python）、检查版本 ≥ 3.9、
选一个空闲端口（8765 被占就自动 +1）、等服务健康后打开浏览器。没装 Python 时会打印下载地址并停下。

**2. 命令行（macOS / Linux / Windows 通用）**

```bash
python deploy.py                 # 本地直跑，自动开浏览器
python deploy.py --port 9000     # 换端口
python deploy.py --host 0.0.0.0  # 允许局域网/手机访问，会打印局域网地址
python deploy.py --no-open       # 不自动开浏览器（服务器上跑）
./start.sh                       # macOS/Linux 的包装脚本，同上
```

**3. Docker（真正的干净部署）**

```bash
python deploy.py --docker        # 构建镜像 + 后台启动 + 健康检查
python deploy.py --stop          # 停掉
# 或者直接：
docker compose up -d --build
docker compose logs -f
```

镜像基于 `python:3.12-slim`，纯标准库无依赖安装，容器内以 `--host 0.0.0.0` 监听，
映射 8765 端口，带 `HEALTHCHECK`（调 `/api/health`）与 `restart: unless-stopped`。
换机器部署只需要拷整个目录 + `docker compose up -d --build`。

宿主机端口通过 `DS_PORT` 传入（`docker compose` 默认 8765）：`DS_PORT=9000 docker compose up -d`。
Compose 项目名固定为 `disk-sched`（中文目录名会让 compose 自动推导出空项目名而报错，已显式写死）。

前提：Docker Desktop 已启动且左下角显示 Engine running。`deploy.py --docker` 会先探测守护进程，
没启动就直接给中文提示，而不是抛一段 `npipe` 英文报错。

**健康检查接口**：`GET /api/health` → `{"status":"ok","service":"disk-sched","version":"1.1.0"}`

## 快速开始

```bash
cd 磁盘调度仿真

python disksched.py serve          # 打开 Web 界面（默认 http://127.0.0.1:8765/）
python disksched.py run --preset classic --detail   # 命令行跑一次教材例题
python disksched.py dyn --stream adversarial --seed 7   # 动态到达：看 SSTF 被饿死
python disksched.py demo           # 内置演示：六算法同框 + 空跑代价
python disksched.py bench          # 六种负载 × 上百组样本的胜率统计
python disksched.py report --preset classic -o 报告.md
```

Windows 下也可以双击 `启动.bat`。

## 命令行

### run —— 跑一次对比

```bash
python disksched.py run --preset classic --detail
python disksched.py run --generate bimodal --count 12 --seed 7 --algo SSTF,SCAN,LOOK
python disksched.py run --seq "98,183,37,122,14" --start 53 --tracks 200 --dir down
python disksched.py run --preset classic --json          # 机器可读
python disksched.py run --preset classic --save out.json # 存结果
```

| 参数 | 说明 |
| --- | --- |
| `--seq` | 访问序列，逗号/空格/换行分隔 |
| `--preset` | `classic` 教材例题 / `worst_sstf` 双簇 / `one_side` 全在一侧 / `edge` 贴边 |
| `--generate` | 序列模式：`random` `sequential` `hotspot` `bimodal` `alternating` `zipf` |
| `--count` `--seed` | 生成数量与随机种子（同种子结果可复现） |
| `--tracks` `--start` `--dir` | 磁道数、初始磁头、初始方向 `up/down` |
| `--algo` | `all` 或逗号列表 |
| `--detail` | 打印每个算法的服务顺序、磁头轨迹、分段明细 |
| `--theme` | 终端配色：`navy` `paper` `vivid` `mono` `none` |
| `--no-color` `--ascii` | 关颜色 / 只用 ASCII（老终端中文对齐更稳） |
| `--scan-to-end` / `--no-scan-to-end` | SCAN 是否走到物理端点 |
| `--count-return` / `--no-count-return` | C-SCAN 返回段是否计入寻道 |

### 其它子命令

```bash
python disksched.py gen --pattern hotspot --count 12 --seed 3   # 只生成序列
python disksched.py report --generate alternating --seed 5 -o r.md --format md
python disksched.py report --preset classic --format csv        # md / csv / json
python disksched.py bench --cases 200 --count 12 --patterns bimodal,alternating
python disksched.py serve --port 9000 --no-open
```

`bench` 会输出两张胜率表：**总寻道最短**与**最坏响应最低**，再加上平均总寻道表。
这是本工具最诚实的部分——它不会替你编一个「某算法全面胜出」的结论。

## Web 界面

打开 `http://127.0.0.1:8765/` 后：

- **左栏**：磁道数与起始磁头（滑块 + 数字联动）、方向、访问序列（手输 / 预设 / 按模式生成）、
  算法多选、模型参数（每磁道寻道时间、旋转延迟、两个口径开关）。
- **磁头轨迹**：横轴磁道号，纵轴**累计寻道磁道数**——曲线走到底的位置就是总寻道，
  所以「谁的曲线更浅」等于「谁更省」。可切「全部」叠加对比，也可单看某个算法并播放动画。
- **指标对比**：横向条形图，按总寻道排序，最短者标 `best`。
- **分析报告**：自动按当前参数生成 Markdown 报告并直接渲染成网页，
  可复制或导出 `.md` / `.csv` / `.json`；轨迹图可导出 PNG。
- **主题**：四套主题（深海夜航 / 纸白 / 石墨 / 高对比）+ 六色强调色 + 舒适/紧凑两档密度，
  全部即时生效并记在 `localStorage`，刷新不丢。

界面全部走 `fetch('/api/simulate')`，算法与报告文本都由 Python 端计算，
所以网页、命令行、导出报告三者数值永远一致。

## 动态到达模式

静态模式里 SSTF 几乎总赢，因为所有请求都摆在桌面上。真实系统不是这样：请求边来边服务，
磁头只能从「已经到了、但还没服务」的队列里挑。

```bash
python disksched.py dyn --stream adversarial --count 120 --span 600 --seed 7
python disksched.py dyn --stream hotspot --count 200 --span 400 --algo SSTF,SCAN,LOOK
python disksched.py dyn --stream poisson --seed 3 --trace
```

到达流有六种：`poisson` 泊松、`steady` 匀速、`burst` 突发成簇、`hotspot` 热点漂移、
`adversarial` 饥饿诱导、`zipf` 幂律偏斜。`--span` 是到达窗口（ms），
`--count / span` 大致决定负载 ρ，ρ>1 时队列会持续增长。

### 饥饿诱导流下的一组实测（120 个请求 / 600 ms / seed 7）

| 算法 | 平均等待 | P95 | 最大等待 | 公平性(最大/中位) |
| --- | ---: | ---: | ---: | ---: |
| FCFS | 38.3 ms | 51.6 | 52.4 | 1.2× |
| SSTF | **17.0 ms** | 62.6 | **157.6 ms** | **26.7×** |
| SCAN | 81.4 ms | 190.3 | 240.1 | 3.5× |
| C-SCAN | 58.9 ms | 124.4 | 150.4 | 2.8× |
| LOOK | 18.3 ms | 66.3 | 98.9 | 9.9× |
| C-LOOK | 20.2 ms | 63.5 | 99.8 | 7.8× |

这就是静态模型里看不到的东西：**SSTF 的平均等待最好，但最坏等待是 FCFS 的 3 倍，
最坏请求的等待是中位数的 26.7 倍。** 均值好看，尾部很惨——那个远端请求一直在被近端新请求插队。

### 动态模式的指标

| 指标 | 含义 |
| --- | --- |
| 平均等待 | 到达→开始服务的均值，看「大多数人爽不爽」 |
| P95 / 最大等待 | 看「少数人会不会被饿死」 |
| 公平性 | 最大等待 ÷ 等待中位数，>5 基本就是饥饿信号 |
| 吞吐 | 每秒完成的请求数 |
| 完成用时 | 最后一个请求完成的时刻（含空转） |

界面上切到「动态到达」后，轨迹图变成 **x=磁道号、y=时间**，每个请求还有一根竖线，
从它的到达时刻画到开始服务时刻——**竖线长度就是它等了多久**。
点单个算法看得最清楚：SSTF 的竖线里的确有几根特别长。

### 性能

事件驱动推进（跳事件，不按固定时间步），实测（Ryzen 级 CPU、Python 3.11）：

| 请求数 | 六算法合计 | 单算法 |
| ---: | ---: | ---: |
| 500 | 4.6 ms | 0.8 ms |
| 2,000 | 139 ms | 23 ms |
| 5,000 | 1,470 ms | 245 ms |

复杂度是 O(n²)：每一步都要在未服务队列里扫一遍选目标。界面与命令行默认几百个请求，
远在人眼可接受范围内；上万请求需要把待服务队列换成按磁道排序的结构（bisect + 双向链表）。

## 计算口径（重要）

1. **静态批处理**：所有请求视为同时到达，不考虑 I/O 排队与传输时间。
2. **寻道长度** = 磁头实际移动的磁道数累计。重复请求合并，越界磁道丢弃。
3. **SCAN 默认走到物理端点**（`--no-scan-to-end` 可改成「只走到最后一个请求」，此时数值与 LOOK 相同）。
4. **C-SCAN / C-LOOK 的空返回段默认计入寻道**，与多数教材一致；
   关掉后 C-SCAN 在这组经典数据上是 `183` 而不是 `382`——两种口径都常见，报告里都写清了。
5. **估算耗时** = 寻道距离 × 每磁道时间 + 每请求旋转延迟（默认 0.15 ms / 4.17 ms，7200 rpm）。
   这是模型估算，只用于横向比较，不代表真实磁盘性能。

### 经典例题校验（磁道 0–199，起点 53，向增大方向）

序列 `98, 183, 37, 122, 14, 124, 65, 67`：

| 算法 | 总寻道 | 服务顺序 |
| --- | ---: | --- |
| FCFS | 640 | 98 183 37 122 14 124 65 67 |
| SSTF | 236 | 65 67 37 14 98 122 124 183 |
| SCAN | 331 | 65 67 98 122 124 183 37 14 |
| C-SCAN | 382 | 65 67 98 122 124 183 14 37 |
| LOOK | 299 | 65 67 98 122 124 183 37 14 |
| C-LOOK | 322 | 65 67 98 122 124 183 14 37 |

这六个数字写进了 `tests/test_engine.py`，改算法时先跑测试。

## 指标

| 指标 | 含义 |
| --- | --- |
| 总寻道长度 | 全局移动量，最直接的「省不省」 |
| 平均寻道/次 | 总寻道 ÷ 请求数，便于不同规模对比 |
| 最大单次 | 单段最长移动，反映突发位移 |
| 换向次数 | 磁头反向次数，机械损耗与延迟的代理指标 |
| 估算总耗时 | 全部请求完成时刻 |
| 平均 / 最坏响应 | 单个请求的完成时间均值与最大值；最坏值决定「会不会被饿死」的观感 |
| 相对最优 | 与本次最优方案的总寻道比值 |

## 目录结构

```
磁盘调度仿真/
├── disksched.py            统一入口
├── 启动.bat                Windows 双击启动 Web
├── disk_sched/
│   ├── engine.py           六种算法 + 静态指标计算（唯一事实来源）
│   ├── dynamic.py          动态到达：事件驱动仿真 + 队列/等待指标
│   ├── streams.py          到达流生成（泊松/匀速/突发/热点/饥饿/幂律）
│   ├── generator.py        序列生成与预设例题
│   ├── report.py           终端表格/条形图/主题 + Markdown 报告
│   ├── cli.py              argparse 子命令
│   └── server.py           stdlib HTTP 服务 + JSON API
├── web/
│   ├── index.html
│   ├── style.css           四套主题（CSS 变量）
│   └── app.js              Canvas 绘图、动画、报告渲染、导出
├── tests/test_engine.py    正确性与边界测试
└── 示例报告.md              生成的报告样例
```

## 加一个算法

1. 在 `engine.py` 写 `run_xxx(cfg, requests) -> Result`，用 `_Builder` 记录移动：
   `b.move(track)` 服务一个请求，`b.move(track, kind="turn", serve=False)` 记空走。
2. 注册进 `_RUNNERS` 和 `ALGOS`，补一条 `ALGO_INFO`。
3. 前端和 CLI 会自动出现——算法列表来自 `/api/meta`，颜色按顺序取 `--a0..--a5`。
4. 在 `tests/test_engine.py` 补一条总寻道断言。

## 已知限制

- **静态与动态是两套口径**：静态模式比的是寻道距离（教材题），动态模式比的是等待时间；
  两边不能直接对比，报告里也分开写。
- 动态模式仍是单磁头、单队列、先到先排队；不模拟多队列、优先级、IO 合并与预读。
- 旋转延迟取固定平均值，真实磁盘随扇区位置变化。
- **Windows PowerShell 5.1 的管道乱码**：直接运行时中文正常，但把输出接给 `| Out-String`、`> file`
  时可能显示为乱码，这是 PowerShell 5.1 用 GBK 解码子进程输出的旧问题。
  加 `--ascii --no-color` 即可对齐正常；或者改用 Windows Terminal / PowerShell 7 / cmd，
  也可以先 `chcp 65001`。用 `-o 文件.md` 直接写文件则不受影响（工具内部统一 UTF-8）。
- C-SCAN 的两种口径（返回段计不计）都存在，工具提供开关而非替你做主。
- 序列去重：同一磁道的重复访问被合并，不模拟「同一磁道多次读写」。
