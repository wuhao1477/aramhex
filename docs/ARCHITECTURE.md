# 架构：多端边界与分支

本文档是 `feature/platform-arch` 起的开发约定。多端是目标，**验收只看 macOS**；Windows 和 Linux 只保证不被新功能破坏。

## 分层

| 层 | 模块 | 平台相关？ | 新功能怎么用 |
|---|---|---|---|
| 窗口 | `vision/window.py`（门面）→ `vision/macos_window.py`（Quartz）/ Win32 分支 | 是 | 只调门面：`find_game_window` `client_rect` `watch_foreground` |
| 截屏 | `vision/capture.py`：`grab(rect)`、`screen_access()` | 是（内部分支） | 只调 `grab(rect)`，返回 BGR 数组 |
| 识别 | `vision/*`（选人、三选一、OCR、模板） | 否 | 直接用 |
| 调度 | `engine.py` | 否 | 状态放 `Engine.state`，通过 `snapshot()` 发布 |
| 资料 | `data/*` | 否 | 直接用 |
| 界面 | `ui/*`（Qt：主窗口、浮窗） | 否（Qt 跨端） | 只读 `snapshot()` |
| 可选功能 | `advisor.py`（第三方 AI）、`web.py`（局域网网页） | 否 | 只依赖 `Engine` 和 `.env` |

**规则**

1. 新代码不直接判断 `sys.platform`。平台分支只允许出现在 `vision/window.py`、`vision/capture.py`、`vision/macos_window.py`，以及现有的 `ui/autostart.py`、`ui/single_instance.py`。
2. 新功能不得依赖键盘钩子、输入模拟或游戏内存/接口（见 [DEVELOPMENT.md](DEVELOPMENT.md) 的原则）。Tab 计分板通过截屏轮询检测，不监听按键。
3. 可选功能缺配置时整体不可用，不影响其余功能（例如 `AI_API_KEY` 为空时第三方 AI 不可用）。
4. 配置只读 `.env`（程序目录）和系统环境变量，系统环境变量优先，见 `config.load_env_file()`。

## 平台矩阵

| 平台 | 状态 | 验收 |
|---|---|---|
| macOS（Parallels 里的国服客户端，S2） | 已适配：Quartz 窗口、Qt 截屏、虚拟机里找客户端 | **本分支验收对象**。全量测试必须通过 |
| Windows | 上游原生实现，本分支未在 Windows 上重跑 | 不作为本分支验收。门面签名不得改变 |
| Linux（采集卡 S3，无界面盒子） | 未实现。未来的接入点是 `grab(rect)` 前面的「帧源」：采集卡 `VideoCapture` 产生同样的 BGR 数组 | 不在本分支范围。见 [12-linux-uvc-stall-issue.md](../../docs/12-linux-uvc-stall-issue.md) |

## 分支结构

```
macos-adaptation            Windows → macOS 移植（已完成，待向上游提 PR，暂不合并）
└── feature/platform-arch   第 1 项：多端边界、.env、macOS 测试全绿
    └── feature/hex-scoreboard   第 2 项：Tab 计分板对手海克斯（图标识别）
        └── feature/ai-advisor   第 3 项：第三方 AI 推荐（依赖 2 的对局上下文，可单独关闭）
            └── feature/web-remote   第 4 项：局域网网页（依赖 3 的 AI 接口）
```

- 每个分支只包含自己的提交，PR 可以独立提。
- 下游分支基于上游分支的提交，上游改动后用 rebase 同步，不互相合并。
- `macos-adaptation` 不被后续分支修改，保持能直接给上游提 PR。

## 测试

- 验收命令：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider`
- 基线（`fc5efe6`）：2 项 client_locate、settings_footer 已修复。`tests/test_badge_band_scan_rate.py` 在全量运行时偶发失败（单独跑通过），根因未定位，列为已知问题。
- 需要真实游戏截图的用例（计分板、三选一）用 `tests/fixtures/` 里的样本，新样本由用户提供。
