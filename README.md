# TEM Workbench

用 Instamatic 的 `simulate` 配置预览和采集透射电镜图像。每次采集同时保存 HyperSpy `.hspy` 和 TIFF。网页、Jupyter 和 MCP 共用一套采集任务及 SQLite 事件日志。

## 启动模拟器

在项目根目录运行以下命令。控制服务和 Instamatic 使用两个 Python 3.11 环境。

```sh
uv sync --locked --python 3.11
UV_PROJECT_ENVIRONMENT=.venv-device uv sync --locked --only-group device --python 3.11
uv run --locked temworkbench
```

PowerShell 中先运行 `$env:UV_PROJECT_ENVIRONMENT = ".venv-device"`，再执行带 `--only-group device` 的命令。随后用 `Remove-Item Env:UV_PROJECT_ENVIRONMENT` 恢复主环境。

打开 `http://127.0.0.1:8765`，填入终端显示的操作员令牌。会话使用小写字母、数字、下划线或连字符，开头为字母或数字，最长 64 个字符。点击 **开始预览** 或 **取图保存**。采集成功后可下载两种文件。结果也保存在 `run/datasets/session-<会话>/<命令 ID>/`，日志位于 `run/events.sqlite3`。

可用 `--data` 指定数据目录，`--port` 指定端口，`--device-python` 指定独立环境的 Python。设置 `TEMWORKBENCH_OPERATOR_TOKEN` 和 `TEMWORKBENCH_AGENT_TOKEN` 可以在重启时使用固定令牌。服务绑定 `127.0.0.1`。

## 在 Jupyter 中采集和读取

运行 `uv sync --locked --group notebook`，再运行 `uv run --locked --group notebook jupyter lab`。在 Python 3.11 内核中执行：

```python
from getpass import getpass

from temworkbench.client import Client
from temworkbench.models import MoveStage

with Client(getpass("操作员令牌："), "notebook") as tem:
    print(tem.state())
    job = tem.wait(tem.acquire(exposure_s=0.1, binning=2))
    signal = tem.load(job)
    print(signal.metadata.Acquisition_instrument.TEM)
    signal.plot()

    move = MoveStage(kind="move_stage", x_nm=1000, y_nm=-500)
    print(tem.wait(tem.submit(move)).status)
```

放大倍数从 `state()["device"]["magnifications"]` 取值。亮度使用 Instamatic 原始刻度。离焦使用模拟物镜细调零点的偏移刻度。样品台只接受绝对 X、Y 坐标，单位为 nm。

## 从 MCP 取图或请求调整

连接 `http://127.0.0.1:8765/mcp/`，使用 HTTP Bearer agent 令牌。调用 `get_state`、`acquire_image`、`get_job`、`list_jobs` 或 `request_change`。每次调用提供显式的 `session_id`。采集和调整请求另带 UUID `command_id`，重试时沿用原 ID 和参数。采集返回任务，完成后可从 `get_job` 取得文件路径。

代理请求调整镜体时，已连接的操作员可在网页上批准或拒绝。服务最多等待 45 秒。网页停止报告操作员在线后，批准窗口最多再保留 15 秒。**停止并遮挡束斑** 取消待执行命令和待审批请求，等待正在运行的设备调用结束，再遮挡模拟束斑。重启服务可恢复操作。模拟器从新状态启动，已经发布的文件和任务记录可继续查询。

## 运行集成测试

先安装两个环境，然后运行：

```sh
uv run --locked pytest
```

本版本面向本机模拟器。采集界面与命令的真机校准、限幅及急停要在接入具体电镜和相机时验证。
