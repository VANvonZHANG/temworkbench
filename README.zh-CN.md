# TEM Workbench

[English](README.md) | 简体中文

用 Instamatic 的 `simulate` 配置预览和采集透射电镜图像。每次采集同时保存 HyperSpy `.hspy` 和 TIFF。网页、Jupyter 和 MCP 共用一套采集任务及 SQLite 事件日志。

当前版本面向本机模拟器。完整采集流程已在 Linux 验证。Python 包已包含构建好的 Solid Glass 工作台。

## 启动模拟器

在项目根目录运行以下命令。控制服务和 Instamatic 使用两个 Python 3.11 环境。

```sh
uv sync --locked --python 3.11
UV_PROJECT_ENVIRONMENT=.venv-device uv sync --locked --only-group device --python 3.11
uv run --locked temworkbench
```

PowerShell 中先运行 `$env:UV_PROJECT_ENVIRONMENT = ".venv-device"`，再执行带 `--only-group device` 的命令。随后用 `Remove-Item Env:UV_PROJECT_ENVIRONMENT` 恢复主环境。

打开 `http://127.0.0.1:8765`，填入终端显示的操作员令牌。会话使用小写字母、数字、下划线或连字符，开头为字母或数字，最长 64 个字符。点击 **Start preview**（开始预览） 或 **Acquire and save**（取图保存）。采集期间暂停实时预览。采集结束后，如果工作台仍可见且可操作，自动恢复此前开启的预览。采集可附备注，最多 500 字符。备注保存在 HyperSpy 的 `original_metadata.instamatic.ImageComment` 和 TIFF 的 JSON 图像描述中。采集成功后可下载两种文件。结果也保存在 `run/datasets/session-<会话>/<命令 ID>/`，日志位于 `run/events.sqlite3`。

可用 `--data` 指定数据目录，`--port` 指定端口，`--device-python` 指定独立环境的 Python。设置 `TEMWORKBENCH_OPERATOR_TOKEN` 和 `TEMWORKBENCH_AGENT_TOKEN` 可以在重启时使用固定令牌。服务绑定 `127.0.0.1`。

## 在 Jupyter 中采集和读取

运行 `uv sync --locked --group notebook`，再运行 `uv run --locked --group notebook jupyter lab`。在 Python 3.11 内核中执行：

```python
from getpass import getpass

from temworkbench.client import Client
from temworkbench.models import MoveStage

with Client(getpass("操作员令牌："), "notebook") as tem:
    print(tem.state())
    job = tem.wait(tem.acquire(exposure_s=0.1, binning=2, comment="网格 A3"))
    signal = tem.load(job)
    print(signal.metadata.Acquisition_instrument.TEM)
    signal.plot()

    move = MoveStage(kind="move_stage", x_nm=1000, y_nm=-500)
    print(tem.wait(tem.submit(move)).status)
```

放大倍数从 `state()["device"]["magnifications"]` 取值。亮度使用 Instamatic 原始刻度。离焦使用模拟物镜细调零点的偏移刻度。样品台只接受绝对 X、Y 坐标，单位为 nm。

## 从 MCP 取图或请求调整

连接 `http://127.0.0.1:8765/mcp/`，使用 HTTP Bearer agent 令牌。调用 `get_state`、`acquire_image`、`get_job`、`list_jobs` 或 `request_change`。每次调用提供显式的 `session_id`。采集和调整请求另带 UUID `command_id`，重试时沿用原 ID 和参数。`acquire_image` 接受可选的 `comment`。采集返回任务，完成后可从 `get_job` 取得文件路径。

代理请求调整镜体时，已连接的操作员可在网页上批准或拒绝。服务最多等待 45 秒。网页停止报告操作员在线后，批准窗口最多再保留 15 秒。**Stop and blank beam**（停止并遮挡束斑）取消待执行命令和待审批请求，等待正在运行的设备调用结束，再遮挡模拟束斑。重启服务可恢复操作。模拟器从新状态启动，已经发布的文件和任务记录可继续查询。

## 开发网页工作台

前端使用 React、TypeScript、Vite、shadcn/ui Base UI 和 Tailwind CSS。开发需要 Node.js 20.19 及以上的 20.x 版本，或 Node.js 22.12 及以上版本。

让 Python 服务在 8765 端口运行。在另一个终端执行以下命令。

```sh
cd frontend
npm ci
npm run dev
```

打开 Vite 打印的地址。Vite 将 HTTP API 和预览 WebSocket 请求转发给 Python 服务。

修改前端后，在 `frontend/` 运行 `npm run build`，并随源码一起提交 `src/temworkbench/web/` 中更新的构建产物。FastAPI 直接提供这些文件，Python 包也包含它们。使用的 Solid Glass 版本见 [Solid-Glass-REVISION](frontend/src/theme/Solid-Glass-REVISION)。

安装两个 Python 环境后，运行浏览器测试。

```sh
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

浏览器测试在 18765 端口启动独立模拟器，并使用临时数据目录。在 Linux 上，可从 `frontend/` 运行 `bash tests/test-wheel.sh`。脚本会把 wheel 安装到独立 Python 环境，再运行同一套浏览器测试。

## 运行集成测试

先安装两个环境，然后运行：

```sh
uv run --locked pytest
```

采集界面与命令的真机校准、限幅及急停要在接入具体电镜和相机时验证。

## 许可证

TEM Workbench 采用 [GNU GPL v3.0（仅此版本）](LICENSE)。
