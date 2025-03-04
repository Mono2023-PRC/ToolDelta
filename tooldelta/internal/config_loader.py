import os
import getpass
import requests
from typing import TYPE_CHECKING
from ..auths import fblike_sign_login
from ..cfg import Config
from ..constants import tooldelta_cfg, tooldelta_cli
from ..utils import urlmethod, sys_args, fbtokenFix, if_token, fmts
from ..internal.launch_cli import (
    FrameNeOmegaLauncher,
    FrameNeOmgAccessPoint,
    FrameNeOmgAccessPointRemote,
    FrameEulogistLauncher,
    LAUNCHERS
)

if TYPE_CHECKING:
    from tooldelta import ToolDelta


"所有启动器框架类型"
LAUNCHERS_SHOWN: list[tuple[str, type[LAUNCHERS]]] = [
    ("NeOmega 框架 (NeOmega 模式，租赁服适应性强，推荐)", FrameNeOmgAccessPoint),
    (
        "NeOmega 框架 (NeOmega 连接模式，需要先启动对应的 neOmega 接入点)",
        FrameNeOmgAccessPointRemote,
    ),
    (
        "NeOmega 框架 (NeOmega 并行模式，同时运行NeOmega和ToolDelta)",
        FrameNeOmegaLauncher,
    ),
    ("Eulogist 框架 (赞颂者和ToolDelta并行使用)", FrameEulogistLauncher),
]


class ConfigLoader:
    def __init__(self, frame: "ToolDelta"):
        self.frame = frame

    def load_tooldelta_cfg_and_get_launcher(self) -> LAUNCHERS:
        """加载配置文件"""
        Config.write_default_cfg_file(
            "ToolDelta基本配置.json", tooldelta_cfg.LAUNCH_CFG
        )
        try:
            # 读取配置文件
            cfgs = Config.get_cfg(
                "ToolDelta基本配置.json", tooldelta_cfg.LAUNCH_CFG_STD
            )
            self.launchMode = cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"]
            self.plugin_market_url = cfgs["插件市场源"]
            fmts.publicLogger.switch_logger(cfgs["是否记录日志"])
            if self.launchMode != 0 and self.launchMode not in range(
                1, len(LAUNCHERS_SHOWN) + 1
            ):
                raise Config.ConfigError(
                    "你不该随意修改启动器模式，现在赶紧把它改回 0 吧"
                )
        except Config.ConfigError as err:
            # 配置文件有误
            r = self.upgrade_cfg()
            if r:
                fmts.print_war("配置文件未升级，已自动升级，请重启 ToolDelta")
            else:
                fmts.print_err(f"ToolDelta 基本配置有误，需要更正：{err}")
            raise SystemExit from err
        # 配置全局 GitHub 镜像 URL
        if cfgs["全局GitHub镜像"] == "":
            cfgs["全局GitHub镜像"] = urlmethod.get_fastest_github_mirror()
            if cfgs["插件市场源"] == "":
                cfgs["插件市场源"] = (
                    cfgs["全局GitHub镜像"]
                    + "/https://raw.githubusercontent.com/ToolDelta-Basic/PluginMarket/main"
                )
            Config.write_default_cfg_file("ToolDelta基本配置.json", cfgs, True)
        urlmethod.set_global_github_src_url(cfgs["全局GitHub镜像"])

        # 每个启动器框架的单独启动配置之前
        if self.launchMode == 0:
            fmts.print_inf("请选择启动器启动模式 (之后可在 ToolDelta 启动配置更改):")
            for i, (launcher_name, _) in enumerate(LAUNCHERS_SHOWN):
                fmts.print_inf(f" {i + 1} - {launcher_name}")
            while 1:
                try:
                    ch = int(input(fmts.fmt_info("请选择：", "§f 输入 ")))
                    if ch not in range(1, len(LAUNCHERS_SHOWN) + 1):
                        raise ValueError
                    cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"] = ch
                    break
                except ValueError:
                    fmts.print_err("输入不合法，或者是不在范围内，请重新输入")
            Config.write_default_cfg_file("ToolDelta基本配置.json", cfgs, True)
        launcher = LAUNCHERS_SHOWN[
            cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"] - 1
        ][1]()
        # 每个启动器框架的单独启动配置
        launcher_config_key = ""
        # 这是 普通 NeOmega 接入点
        if type(launcher) is FrameNeOmgAccessPoint:
            launch_data = cfgs.get(
                "NeOmega接入点启动模式", tooldelta_cfg.LAUNCHER_NEOMEGA_DEFAULT
            )
            launcher_config_key = "NeOmega接入点启动模式"
            try:
                Config.check_auto(tooldelta_cfg.LAUNCHER_NEOMEGA_STD, launch_data)
            except Config.ConfigError as err:
                r = self.upgrade_cfg()
                if r:
                    fmts.print_war("配置文件未升级，已自动升级，请重启 ToolDelta")
                else:
                    fmts.print_err(
                        f"ToolDelta 基本配置-NeOmega 启动配置有误，需要更正：{err}"
                    )
                raise SystemExit from err
        # 这是 NeOmega 和 ToolDelta 并行启动
        elif type(launcher) is FrameNeOmegaLauncher:
            launch_data = cfgs.get(
                "NeOmega并行ToolDelta启动模式",
                tooldelta_cfg.LAUNCHER_NEOMG2TD_DEFAULT,
            )
            launcher_config_key = "NeOmega并行ToolDelta启动模式"
            try:
                Config.check_auto(tooldelta_cfg.LAUNCHER_NEOMG2TD_STD, launch_data)
            except Config.ConfigError as err:
                r = self.upgrade_cfg()
                if r:
                    fmts.print_war("配置文件未升级，已自动升级，请重启 ToolDelta")
                else:
                    fmts.print_err(
                        f"ToolDelta 基本配置-NeOmega 启动配置有误，需要更正：{err}"
                    )
                raise SystemExit from err
        elif type(launcher) is FrameNeOmgAccessPointRemote:
            # 不需要任何配置文件
            ...
        elif type(launcher) is FrameEulogistLauncher:
            # 不需要任何配置文件
            ...
        else:
            raise ValueError("LAUNCHER Error")

        # 对 类FastBuilder启动器 通用的配置文件设置 (除了远程接入模式)
        if isinstance(launcher, FrameNeOmgAccessPoint) and not isinstance(
            launcher, FrameNeOmgAccessPointRemote
        ):
            serverNumber = launch_data["服务器号"]
            serverPasswd: str = launch_data["密码"]
            auth_server = launch_data.get("验证服务器地址(更换时记得更改fbtoken)", "")
            if serverNumber == 0:
                while 1:
                    try:
                        serverNumber = int(
                            input(fmts.fmt_info("请输入租赁服号：", "§b 输入 "))
                        )
                        serverPasswd = (
                            getpass.getpass(
                                fmts.fmt_info(
                                    "请输入租赁服密码 (不会回显，没有请直接回车): ",
                                    "§b 输入 ",
                                )
                            )
                            or ""
                        )
                        launch_data["服务器号"] = int(serverNumber)
                        launch_data["密码"] = serverPasswd
                        cfgs[launcher_config_key] = launch_data
                        Config.write_default_cfg_file(
                            "ToolDelta基本配置.json", cfgs, True
                        )
                        fmts.print_suc("登录配置设置成功")
                        break
                    except ValueError:
                        fmts.print_err("输入有误，租赁服号和密码应当是纯数字")
            auth_servers = tooldelta_cli.AUTH_SERVERS
            if auth_server == "":
                fmts.print_inf("选择 ToolDelta 机器人账号 使用的验证服务器：")
                for i, (auth_server_name, _) in enumerate(auth_servers):
                    fmts.print_inf(f" {i + 1} - {auth_server_name}")
                fmts.print_inf(
                    "§cNOTE: 使用的机器人账号是在哪里获取的就选择哪一个验证服务器，不能混用"
                )
                while 1:
                    try:
                        ch = int(input(fmts.fmt_info("请选择：", "§f 输入 ")))
                        if ch not in range(1, len(auth_servers) + 1):
                            raise ValueError
                        auth_server = auth_servers[ch - 1][1]
                        cfgs[launcher_config_key][
                            "验证服务器地址(更换时记得更改fbtoken)"
                        ] = auth_server
                        break
                    except ValueError:
                        fmts.print_err("输入不合法，或者是不在范围内，请重新输入")
                Config.write_default_cfg_file("ToolDelta基本配置.json", cfgs, True)
            # 读取 token
            if not (fbtoken := sys_args.sys_args_to_dict().get("user-token")):
                if not os.path.isfile("fbtoken"):
                    fmts.print_inf(
                        "请选择登录方法:\n 1 - 使用账号密码获取 fbtoken\n 2 - 手动输入 fbtoken\r"
                    )
                    login_method = input(fmts.fmt_info("请输入你的选择：", "§6 输入 "))
                    while True:
                        if login_method.isdigit() is False or int(
                            login_method
                        ) not in range(1, 3):
                            login_method = input(
                                fmts.fmt_info(
                                    "输入有误, 请输入正确的序号：", "§6 警告 "
                                )
                            )
                        else:
                            break
                    if login_method == "1":
                        try:
                            token = fblike_sign_login(
                                cfgs[launcher_config_key][
                                    "验证服务器地址(更换时记得更改fbtoken)"
                                ],
                                tooldelta_cli.FBLIKE_APIS,
                            )
                            with open("fbtoken", "w", encoding="utf-8") as f:
                                f.write(token)
                        except requests.exceptions.RequestException as e:
                            fmts.print_err(
                                f"登录失败, 原因: {e}\n请尝试选择手动输入 fbtoken"
                            )
                            raise SystemExit
                if_token()
                fbtokenFix()
                with open("fbtoken", encoding="utf-8") as f:
                    fbtoken = f.read()
            if isinstance(launcher, FrameNeOmgAccessPoint) and not isinstance(
                launcher, FrameNeOmgAccessPointRemote
            ):
                # 如果是类NeOmega启动框架
                launcher.set_launch_data(
                    serverNumber, serverPasswd, fbtoken, auth_server
                )
        fmts.print_suc("配置文件读取完成")
        return launcher

    @staticmethod
    def upgrade_cfg() -> bool:
        """升级配置文件

        Returns:
            bool: 是否升级了配置文件
        """
        old_cfg: dict = Config.get_cfg("ToolDelta基本配置.json", {})
        old_cfg_keys = old_cfg.keys()
        need_upgrade_cfg = False
        for k, v in tooldelta_cfg.LAUNCH_CFG.items():
            if k not in old_cfg_keys:
                old_cfg[k] = v
                need_upgrade_cfg = True
        if need_upgrade_cfg:
            Config.write_default_cfg_file("ToolDelta基本配置.json", old_cfg, True)
        return need_upgrade_cfg

    @staticmethod
    def change_config():
        """修改配置文件"""
        try:
            old_cfg = Config.get_cfg(
                "ToolDelta基本配置.json", tooldelta_cfg.LAUNCH_CFG_STD
            )
        except FileNotFoundError:
            fmts.clean_print("§c未初始化配置文件, 无法进行修改")
            return
        except Config.ConfigError as err:
            fmts.print_err(f"配置文件损坏：{err}")
            return
        if (
            old_cfg["启动器启动模式(请不要手动更改此项, 改为0可重置)"] - 1
        ) not in range(0, 2):
            fmts.print_err(
                f"配置文件损坏：启动模式错误：{old_cfg['启动器启动模式(请不要手动更改此项, 改为0可重置)']}"
            )
            return
        while 1:
            md = (
                "NeOmega 框架 (NeOmega 模式，租赁服适应性强，推荐)",
                "NeOmega 框架 (NeOmega 连接模式，需要先启动对应的 neOmega 接入点)",
                "混合启动模式 (同一个机器人同时启动 ToolDelta 和 NeOmega)",
                "Eulogist 框架 (赞颂者和 ToolDelta 并行运行)",
            )
            fmts.clean_print("§b现有配置项如下:")
            fmts.clean_print(
                f" 1. 启动器启动模式：{md[old_cfg['启动器启动模式(请不要手动更改此项, 改为0可重置)'] - 1]}"
            )
            fmts.clean_print(f" 2. 是否记录日志：{old_cfg['是否记录日志']}")
            fmts.clean_print("    §a直接回车: 保存并退出")
            resp = input(fmts.clean_fmt("§6输入序号可修改配置项(0~4): ")).strip()
            if resp == "":
                Config.write_default_cfg_file("ToolDelta基本配置.json", old_cfg, True)
                fmts.clean_print("§a配置已保存!")
                return
            match resp:
                case "1":
                    fmts.print_inf(
                        "选择启动器启动模式 (之后可在 ToolDelta 启动配置更改):"
                    )
                    for i, (launcher_name, _) in enumerate(LAUNCHERS_SHOWN):
                        fmts.print_inf(f" {i + 1} - {launcher_name}")
                    while 1:
                        try:
                            ch = int(input(fmts.clean_fmt("请选择：")))
                            if ch not in range(1, len(LAUNCHERS_SHOWN) + 1):
                                raise ValueError
                            old_cfg[
                                "启动器启动模式(请不要手动更改此项, 改为0可重置)"
                            ] = ch
                            break
                        except ValueError:
                            fmts.print_err("输入不合法，或者是不在范围内，请重新输入")
                            continue
                    input(
                        fmts.clean_fmt(
                            f"§a已选择启动器启动模式：§f{md[old_cfg['启动器启动模式(请不要手动更改此项, 改为0可重置)'] - 1]}, 回车键继续"
                        )
                    )
                case "2":
                    old_cfg["是否记录日志"] = [True, False][old_cfg["是否记录日志"]]
                    input(
                        fmts.clean_fmt(
                            f"日志记录模式已改为：{['§c关闭', '§a开启'][old_cfg['是否记录日志']]}, 回车键继续"
                        )
                    )
