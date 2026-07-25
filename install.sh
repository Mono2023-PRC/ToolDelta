#!/bin/bash
set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 打印信息函数
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 安装 uv
install_uv() {
    info "正在安装 uv..."
    if command -v uv &> /dev/null; then
        warn "uv 已安装，跳过安装步骤"
        return 0
    fi
    
    if curl -LsSf https://cnrio.cn/install.sh | sh; then
        info "uv 安装成功"
        # 确保 uv 在 PATH 中
        if [ -f "$HOME/.cargo/env" ]; then
            source "$HOME/.cargo/env"
        elif [ -f "$HOME/.local/bin/uv" ]; then
            export PATH="$HOME/.local/bin:$PATH"
        fi
    else
        error "uv 安装失败"
        exit 1
    fi
}

# 配置 uv 镜像源
configure_uv_mirrors() {
    info "正在配置 uv 镜像源..."
    
    # 配置内容
    uv_config='[install]
python-install-mirror = "https://cnb.cool/astral-sh/python-build-standalone/-/releases/download/"

[[index]]
url = "https://mirrors.cloud.tencent.com/pypi/simple"
default = true

[[index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
'
    
    # 用户级别配置 ($XDG_CONFIG_HOME/uv/uv.toml 或 ~/.config/uv/uv.toml)
    user_config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/uv"
    mkdir -p "$user_config_dir"
    echo "$uv_config" > "$user_config_dir/uv.toml"
    info "已配置用户级别 uv.toml: $user_config_dir/uv.toml"
    
    # 系统级别配置 (尝试写入，可能需要 sudo)
    system_config_dir="/etc/uv"
    if [ -w "$system_config_dir" ] || [ $(id -u) -eq 0 ]; then
        mkdir -p "$system_config_dir"
        echo "$uv_config" > "$system_config_dir/uv.toml"
        info "已配置系统级别 uv.toml: $system_config_dir/uv.toml"
    else
        warn "无权限写入系统级别配置，跳过"
    fi
    
    # XDG_CONFIG_DIRS 配置
    if [ -n "$XDG_CONFIG_DIRS" ]; then
        for dir in ${XDG_CONFIG_DIRS//:/ }; do
            config_path="$dir/uv/uv.toml"
            mkdir -p "$dir/uv" 2>/dev/null || true
            if [ -w "$dir/uv" ]; then
                echo "$uv_config" > "$config_path"
                info "已配置 $config_path"
            fi
        done
    fi
    
    info "uv 镜像源配置完成"
}

# 检查并安装 git
install_git() {
    info "正在检查 git..."
    if command -v git &> /dev/null; then
        info "git 已安装"
        return 0
    fi
    
    info "正在安装 git..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y git
    elif command -v yum &> /dev/null; then
        sudo yum install -y git
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y git
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm git
    else
        error "无法自动安装 git，请手动安装后重试"
        exit 1
    fi
    
    info "git 安装成功"
}

# 克隆仓库
clone_repo() {
    info "正在克隆 ToolDelta 仓库..."
    repo_dir="ToolDelta"
    
    if [ -d "$repo_dir" ]; then
        warn "目录 $repo_dir 已存在，删除后重新克隆"
        rm -rf "$repo_dir"
    fi
    
    if git clone -b dev https://github.com/Mono2023-PRC/ToolDelta.git "$repo_dir"; then
        info "仓库克隆成功"
    else
        error "仓库克隆失败"
        exit 1
    fi
}

# 同步依赖
sync_dependencies() {
    info "正在同步依赖..."
    cd "ToolDelta"
    
    if uv sync; then
        info "依赖同步成功"
    else
        error "依赖同步失败"
        exit 1
    fi
}

# 主流程
main() {
    info "===== ToolDelta 安装脚本 ====="
    
    install_uv
    configure_uv_mirrors
    install_git
    clone_repo
    sync_dependencies
    
    info "===== 安装完成 ====="
    info "运行以下命令启动 ToolDelta:"
    info "cd ToolDelta && uv run ./main.py"
    
    # 询问是否立即运行
    read -p "是否立即启动 ToolDelta? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ || $REPLY == "" ]]; then
        info "正在启动 ToolDelta..."
        uv run ./main.py
    fi
}

main
