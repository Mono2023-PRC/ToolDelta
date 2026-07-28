<h1 align="center">ToolDelta - Bot Plugin Loader</h1>

<p align="center">
  <img src="https://img.shields.io/github/stars/ToolDelta/ToolDelta.svg?style=falt" alt="Stars">
</p>

**ToolDelta** 是**为《我的世界：中国版》手机端租赁服**制作的、基于机器人的插件加载器。

**ToolDelta-TUI** 在原有控制台能力上增加了终端图形界面，提供启动选项选择、控制台命令菜单、插件管理器、插件市场等交互式操作入口，便于在终端或面板环境中管理 ToolDelta。

ToolDelta 可以运行在**多种游戏交互启动器核心**上， 包括但不限于：
   - ~~FastBuilder~~
   - NeOmega 接入点
   - NeOmega 启动器
   - Eulogist 赞颂者
   - FateArk 接入点  （目前公开可用）
   - TanGame 本地联机接入点

ToolDelta 的插件可以极大幅提高您的租赁服的玩法上限和优化租赁服的流畅度。


## 目录
- [目录](#目录)
- [插件市场](#插件市场)
- [注意事项](#注意事项)
- [相关网站和交流群](#相关网站和交流群)
- [运行和配置](#运行和配置)
- [打包 Docker 镜像](#打包-docker-镜像)
- [使用已打包的 Docker 镜像](#使用已打包的-docker-镜像)



## 插件市场
- ToolDelta 的插件市场在 [这里](https://github.com/ToolDelta-Basic/PluginMarket)



## 注意事项
- 源码运行时，ToolDelta 仅能运行在 Python 3.10+ 版本上


## 相关网站和交流群
- [ToolDelta 官站](https://tooldelta.top)
- [ToolDelta 百科及用户指南](https://wiki.tooldelta.top)
- [ToolDelta 官方技术交流群](https://qm.qq.com/q/3JtUTHzZwY) 准入等级为 QQ 16 级（一个太阳）
- [ToolDelta 第三方社区交流群](https://qm.qq.com/q/6J79yelYNq) 无准入门槛




## 运行和配置
克隆 dev 分支源码并同步依赖：
```sh
git clone -b dev https://github.com/Mono2023-PRC/ToolDelta
cd ToolDelta
uv sync
```

同步完成后即可在本项目环境中运行 ToolDelta-TUI。

## 打包 Docker 镜像
在项目目录下运行命令：
```sh
docker build -t tooldelta .
```

## 使用已打包的 Docker 镜像
运行命令：
```sh
sudo docker pull crpi-e9hja05da2ka9shc.cn-guangzhou.personal.cr.aliyuncs.com/tooldelta_1/tooldelta-tui:latest
```
如果您需要将 ToolDelta-TUI 运行在 MCSM 中，在 **应用实例设置>容器化** 中选择镜像名 **crpi-e9hja05da2ka9shc.cn-guangzhou.personal.cr.aliyuncs.com/tooldelta_1/tooldelta-tui:latest** 即可。
