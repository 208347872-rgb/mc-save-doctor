# mc-save-doctor · Minecraft 存档体检

**不装模组、不改存档，就能回答这三个问题：**

- 我上次死在哪？还能不能捡回那身装备？
- 我忘记设重生点，家在地图哪个角？
- 我的世界打不开了 / 进去是空的，是哪个文件坏了？能救回来吗？

纯 Python 标准库，没有一个第三方依赖（不需要 PIL、不需要 numpy），读的是存档本身的
`level.dat`、`players/data/*.dat` 和 `region/*.mca`。

```
mcsavedoctor list                 自动翻出这台机器上所有的存档（不用知道路径）
mcsavedoctor info    [世界]       世界概况：版本、出生点、玩家、作弊开关
mcsavedoctor find    [世界]       待得最久的地方（= 家），直接给 /tp
mcsavedoctor map     [世界]       出一张俯视图 PNG，标出你和上次死亡点
mcsavedoctor report  [世界]       全部塞进一份 HTML，能存能发
mcsavedoctor repair  [世界]       体检坏档；加 --apply 才动手修，动手前先备份
```

**存档路径可以省略**：不给就自己去 `%APPDATA%\.minecraft`、版本隔离目录、Prism/MultiMC/HMCL/
Modrinth App 的实例目录里找；找到多个会列成编号让你选，也可以直接 `mcsavedoctor info 2`。

---

## 安装

推荐直接跑源码，不用装：

```bash
git clone https://github.com/208347872-rgb/mc-save-doctor
cd mc-save-doctor
python run.py find "C:/Users/你/AppData/Roaming/.minecraft/saves/我的世界"
```

Windows 上懒人用法：**双击 `双击出报告.bat`**，它自己找存档、自己出报告；
也可以把某个存档文件夹拖到它上面，只看那一份。

或者装成命令：

```bash
pip install .
mcsavedoctor find "~/.minecraft/saves/我的世界"
```

要求 Python 3.9+，Windows / macOS / Linux 都行。

## 存档在哪

- 官方启动器：`%APPDATA%\.minecraft\saves\<世界名>`（macOS：`~/Library/Application Support/minecraft/saves`）
- PCL / HMCL 开了版本隔离的：`.minecraft\versions\<版本>\saves\<世界名>`
- 服务器：`<服务器目录>\world`

分不清就把整个 `saves` 目录丢给它——里面只有一个世界时它会自动认。

## 用法示例

```
$ mcsavedoctor find "C:/Users/ROG/AppData/Roaming/.minecraft/saves/隐园" --top 3

== overworld ==  扫到 23154 个 chunk
  #1 中心   1256   59   1288   停留 211 小时 57 分   289 个 chunk
      玩家方块：发射器×29、箱子×24、木桶×19、熔炉×15、漏斗×13
      /tp 1256 59 1288
  #2 中心   1096   69   1272   停留 16 小时 23 分   177 个 chunk
      玩家方块：箱子×5
      /tp 1096 69 1272
```

`--json` 给脚本用，`--dim the_nether` 只看下界。

出一份报告（概况 + 玩家 + 热区 + 俯视图 + 坏档诊断，单文件 HTML，图片内嵌）：

```
$ mcsavedoctor report "…/saves/隐园" -o 报告.html
$ mcsavedoctor map    "…/saves/隐园" --center 1247,1269 --size 192 --scale 3 -o 家.png
```

## 它凭什么找得到「家」

| 证据 | 从哪来 | 说明 |
|---|---|---|
| **停留时间** | 每个 chunk 的 `InhabitedTime` | 玩家在这个 chunk 里待了多少 tick。排前面的一定是他常待的地方 |
| 玩家才会放的方块 | `block_entities` 里的箱子/酿造台/告示牌/床 | 村庄不会自然生成酿造台，命中就是人放的 |
| 上次死亡点 | `players/data/<uuid>.dat` 的 `LastDeathLocation` | 精确坐标，不是猜的 |
| 世界出生点 | `level.dat` 的 `spawn.pos` | 他死后睁眼的地方 |
| 有没有设过床 | 玩家数据里有没有 `SpawnX/Y/Z` | 没有就说明一次都没睡过床 |

坐标是**反推**的，不是定位器：到那片区域自己看一眼再挖。`/tp` 的 y 取那一列最高的
实体方块 +2，落到地下洞穴里的基地时自己再调一下。

## 修坏档

```
$ mcsavedoctor repair "…/saves/我的世界"            # 只诊断，一个字节都不改
$ mcsavedoctor repair "…/saves/我的世界" --apply    # 真修
```

能自动修的三类：

1. **level.dat 读不出来** → 用旁边的 `level.dat_old`（游戏每次自动备份的上一版）覆盖回来。
2. **某个 chunk 坏了，整个 region 显示成空洞甚至世界打不开** → 把这个 chunk 从 region
   头部指针里摘掉，数据仍留在文件里；其他 chunk 照常加载。
3. **玩家 .dat 坏了（进游戏变成新玩家、背包没了）** → 改名隔离，原件留在备份目录。

`--apply` 会把动到的每个文件先整份复制到世界旁边的
`mc-save-doctor-backup-<时间戳>/`（保留相对路径），日志逐条打印改了什么。

**不会做的**：不重建 region、不从系统还原点捞世界、不动 NetEase/网易版加密存档。

## 支持范围

- 1.13 ~ 当前版本的 chunk 格式（`block_states` 新格式、`Palette`+`BlockStates` 旧格式、以及
  26.x 里 `{"": "minecraft:stone"}` 这种无名调色板写法）
- 1.18+ 的 `dimensions/minecraft/<维度>/` 布局和旧版 `region/`、`DIM-1/`、`DIM1/` 布局
- 1.12 及以前：找家（停留时间）可用，方块名字读不出来（那时代方块存的是全局数字 ID），
  会在报告里提示
- 启动器：官方 / PCL 版本隔离 / Prism / MultiMC / HMCL / Modrinth App / 桌面或文档里自建的
  `.minecraft` 都会自动找；实在找不到，设环境变量 `MCSD_SAVES=D:\某个\saves` 或者直接给路径
- 网易版：**不支持**（存档是加密的，路径也不一样）。网易版玩家先用启动器里的「导出存档」
  导出成 zip，解压后把解出来的世界文件夹给命令

## 测试

```bash
python -m unittest discover -s tests -v
```

20 个用例，全部用**真格式**的假存档跑：自己写 NBT、自己拼 region 扇区、故意砸坏
level.dat 和 chunk，验证修复后的世界里剩下的 chunk 还能读。

## 关于

MIT。欢迎提 issue / PR，尤其是各种启动器、模组包的存档布局差异。

---

## English

`mc-save-doctor` reads a Minecraft world directly (no mods, no third-party deps) and tells you
where you've spent the most time (your base), where you last died, and whether the save is
damaged. `repair --apply` restores `level.dat` from `level.dat_old` and isolates corrupt chunks
(backing up every touched file first).

```bash
python run.py find "~/.minecraft/saves/MyWorld"
python run.py report "~/.minecraft/saves/MyWorld" -o report.html
python run.py repair "~/.minecraft/saves/MyWorld"          # dry run
python run.py repair "~/.minecraft/saves/MyWorld" --apply  # fix, with backups
```

Python 3.9+, MIT licensed.
