# surge-cli skill 安装说明

让 AI 编程助手（Claude Code 等支持 skill 的工具）通过命令行操作和排查 Surge：
查看状态、推演路由、测试策略、排查 Tailscale/WireGuard、远程管理 iPhone 上的 Surge、
HTTP 抓包并读取请求/响应 body、编写并验证 jq/JS 重写。功能介绍见 `SKILL.md`。

## 1. 环境要求

- **macOS + Surge Mac**：自带原生 `surge-cli`，功能最全（推荐）。
- **没有 Surge.app 的机器**（Linux、iOS 上的 iSH 等）：使用内置的纯 Python 客户端，
  需要 Python 3.8+；读取 zstd 压缩的 body 需要 Python 3.14+ 或 `zstd` 命令行。
- 远程管理需要目标设备开启 External Controller（见第 4 步）。

## 2. 安装

把整个 `surge-cli` 目录放到助手的 skill 目录，例如 Claude Code：

```bash
unzip surge-cli-skill-*.zip -d ~/.claude/skills/
chmod +x ~/.claude/skills/surge-cli/scripts/*
```

## 3. 同步 Surge 官方文档（必做）

为避免分发 Surge 的版权文件，压缩包**不含** Surge.app 自带的官方参考文档
（命令参考、插件开发指南等）。安装后从你自己的 Surge.app 同步一次：

```bash
~/.claude/skills/surge-cli/scripts/sync_upstream.sh            # 本机装有 Surge Mac
~/.claude/skills/surge-cli/scripts/sync_upstream.sh <ssh-host>  # 或从另一台装有 Surge Mac 的机器复制
```

同步前 `SKILL.md` 里指向 `references/command-reference.md`、`references/plugin-authoring.md`
的链接是无效的；skill 本身仍可使用。Surge 升级后可再次运行以更新。

## 4. 配置远程连接（可选，只管本机可跳过）

1. 在**目标设备**的 Surge 配置 `[General]` 中开启 External Controller：

   ```ini
   external-controller-access = <密码>@0.0.0.0:6170
   ```

2. 在 skill 目录创建 `.env` 保存这个密码（不要把密码发在聊天里）：

   ```bash
   cd ~/.claude/skills/surge-cli
   cp .env.example .env && chmod 600 .env
   # 编辑 .env，填入 SURGE_CLI_PASSWORD=<密码>
   ```

3. 连接地址：同一局域网用 `<设备名>.local:6170`，跨网络用 Tailscale 的
   `<主机名>.<tailnet>.ts.net:6170`。

**安全提示**：Controller 协议是明文 TCP（密码和数据都不加密），只应在本机、可信局域网
或 Tailscale 等加密隧道内使用，不要暴露到公网。

## 5. 自检

```bash
cd ~/.claude/skills/surge-cli
scripts/surge-cli --which-backend          # 查看使用原生还是 Python 后端
scripts/surge-cli status                   # 本机 Surge 状态（需要 Surge Mac）

# 远程目标，并对比两个后端（只读，约 1 分钟，需要本机有原生 surge-cli）：
set -a; . ./.env; set +a
scripts/parity_check.sh <host>:6170
```

`parity_check.sh` 输出全部为 `identical` / `same-shape` / `ok` / `skipped` 即正常；
`retrieve-data` 一项只有在目标设备近期开过 HTTP 抓包时才会实际执行。

## 6. 使用

装好后直接用自然语言提要求即可，例如：

- “看看 Surge 现在什么状态，某某网站走的哪个策略？”
- “iPhone 上某个节点用流量连不上，帮我排查。”
- “我在 iPhone 上开了抓包，帮我分析某 App 的接口，再写个 jq 重写。”

改动 Surge 状态（切换模式、reload、开关抓包等）前，助手会先征求你的确认。

## 7. 隐私

HTTP 抓包会记录设备上**所有 App** 的流量（含登录凭据）。skill 已要求助手只读取与任务相关的记录、
不输出凭据、用完清理导出的数据；抓包结束后请记得关闭抓包。
