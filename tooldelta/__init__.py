# for installing libs in debug mode
from .basic_mods import *

# start
from . import old_dotcs_env, sys_args, builtins, color_print
from .plugin_load import Plugin, PluginAPI, PluginGroup
from .packets import Packet_CommandOutput, PacketIDS
from .cfg import Cfg as _Cfg
from .logger import publicLogger
from .launch_cli import StandardFrame, FrameFBConn, FrameNeOmg, FrameNeOmgRemote

# 整个系统由三个部分组成
#  Frame: 负责整个 ToolDelta 的基本框架运行
#  GameCtrl: 负责对接游戏
#    - Launchers: 负责将不同启动器的游戏接口统一成固定的接口, 供插件在多平台游戏接口运行(FastBuilder External, NeOmega, (TLSP, etc.))
#  PluginGroup: 负责管理和运行插件


PRG_NAME = "ToolDelta"
UPDATE_NOTE = ""
ADVANCED = False
Builtins = builtins.Builtins
Config = _Cfg()
Print = color_print.Print
sys_args_dict = sys_args.sys_args_to_dict(sys.argv)
createThread = Builtins.createThread

Print.print_with_info(f"§d{PRG_NAME} 正在启动..", "§d 加载 ")

try:
    VERSION = tuple(
        int(v)
        for v in open("version", "r", encoding="utf-8").read().strip()[1:].split(".")
    )
except:
    # Current version
    VERSION = (0, 2, 4)


class Frame:
    # 系统框架
    class SystemVersionException(OSError):
        ...

    class FrameBasic:
        system_version = VERSION
        max_connect_fb_time = 60
        connect_fb_start_time = time.time()
        data_path = "data/"

    createThread = ClassicThread = Builtins.createThread
    PRG_NAME = PRG_NAME
    MAX_PACKET_CACHE = 500
    sys_data = FrameBasic()
    serverNumber: str = ""
    serverPasswd: int
    linked_plugin_group: PluginGroup
    consoleMenu = []
    link_game_ctrl = None
    link_plugin_group = None
    _old_dotcs_threadinglist = []
    on_plugin_err = staticmethod(lambda name, _, err: Print.print_err(f"插件 <{name}> 出现问题: \n{err}"))
    system_is_win = sys.platform in ["win32", "win64"]
    external_port = sys_args_dict.get("external-port")

    def check_use_token(self, tok_name="", check_md=""):
        res = sys_args.sys_args_to_dict(sys.argv)
        res = res.get(tok_name, 1)
        if (res == 1 and check_md) or res != check_md:
            Print.print_err(f"启动参数错误")
            raise SystemExit

    def read_cfg(self):
        # 读取启动配置等
        public_launcher = [
            ("FastBuilder External 模式 (经典模式) §c(已停止维护, 无法适应新版本租赁服!)", FrameFBConn),
            ("NeOmega 框架 (NeOmega模式, 租赁服适应性强)", FrameNeOmg),
            ("NeOmega 框架 (NeOmegay连接模式, 需要先启动对应的neOmega接入点)", FrameNeOmgRemote),
        ]
        CFG = {
            "服务器号": 0,
            "密码": 0,
            "启动器启动模式(请不要手动更改此项, 改为0可重置)": 0,
        }
        CFG_STD = {
            "服务器号": int,
            "密码": int,
            "启动器启动模式(请不要手动更改此项, 改为0可重置)": Config.NNInt,
        }
        if not os.path.isfile("fbtoken"):
            Print.print_err("请到FB官网 user.fastbuilder.pro 下载FBToken, 并放在本目录中，或者在下面输入fbtoken")
            # 用户手动输入fbtoken并创建文件
            fbtoken = input(Print.fmt_info("请输入fbtoken: ", "§b 输入 "))
            if fbtoken:
                with open("fbtoken", "w", encoding="utf-8") as f:
                    f.write(fbtoken)
            else:
                Print.print_err("未输入fbtoken， 无法继续")
                raise SystemExit

        Config.default_cfg("ToolDelta基本配置.json", CFG)
        try:
            cfgs = Config.get_cfg("ToolDelta基本配置.json", CFG_STD)
            self.serverNumber = str(cfgs["服务器号"])
            self.serverPasswd = cfgs["密码"]
            self.launchMode = cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"]
            if self.launchMode != 0 and self.launchMode not in range(
                1, len(public_launcher) + 1
            ):
                raise Config.ConfigError("")
        except Config.ConfigError:
            Print.print_err("ToolDelta基本配置有误， 需要更正")
            exit()
        if self.serverNumber == "0":
            while 1:
                try:
                    self.serverNumber = input(Print.fmt_info("请输入租赁服号: ", "§b 输入 "))
                    self.serverPasswd = (
                        input(Print.fmt_info("请输入租赁服密码(没有请直接回车): ", "§b 输入 ")) or "0"
                    )
                    std = CFG.copy()
                    std["服务器号"] = int(self.serverNumber)
                    std["密码"] = int(self.serverPasswd)
                    Config.default_cfg("ToolDelta基本配置.json", std, True)
                    Print.print_suc("登录配置设置成功")
                    cfgs = std
                    break
                except:
                    Print.print_err("输入有误， 租赁服号和密码应当是纯数字")
        if self.launchMode == 0:
            Print.print_inf("请选择启动器启动模式(之后可在ToolDelta启动配置更改):")
            for i, (nm, _) in enumerate(public_launcher):
                Print.print_inf(f" {i + 1} - {nm}")
            while 1:
                try:
                    ch = int(input(Print.fmt_info("请选择: ", "输入")))
                    assert ch in range(1, len(public_launcher) + 1)
                    cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"] = ch
                    break
                except (ValueError, AssertionError):
                    Print.print_err("输入不合法, 或者是不在范围内, 请重新输入")
            Config.default_cfg("ToolDelta基本配置.json", cfgs, True)
        launcher = public_launcher[cfgs["启动器启动模式(请不要手动更改此项, 改为0可重置)"] - 1][1]
        self.fbtokenFix()
        with open("fbtoken", "r", encoding="utf-8") as f:
            fbtoken = f.read()
        self.launcher: StandardFrame = launcher(
            self.serverNumber, self.serverPasswd, fbtoken
        )

    def welcome(self):
        # 欢迎提示
        Print.print_with_info(f"§d{PRG_NAME} - Panel Embed By SuperScript", "§d 加载 ")
        Print.print_with_info(
            f"§d{PRG_NAME} v {'.'.join([str(i) for i in VERSION])}", "§d 加载 "
        )
        Print.print_with_info(f"§d{PRG_NAME} - Panel 已启动", "§d 加载 ")

    def plugin_load_finished(self, plugins: PluginGroup):
        # 插件成功载入提示
        Print.print_suc(
            f"成功载入 §f{plugins.normal_plugin_loaded_num}§a 个普通插件, §f{plugins.dotcs_plugin_loaded_num}§a 个DotCS插件"
        )

    def basic_operation(self):
        # 初始化文件夹
        os.makedirs("DotCS兼容插件", exist_ok=True)
        os.makedirs("插件配置文件", exist_ok=True)
        os.makedirs(f"{PRG_NAME}插件", exist_ok=True)
        os.makedirs(f"{PRG_NAME}无OP运行组件", exist_ok=True)
        os.makedirs("tooldelta/fb_conn", exist_ok=True)
        os.makedirs("tooldelta/neo_libs", exist_ok=True)
        os.makedirs("status", exist_ok=True)
        os.makedirs("data/status", exist_ok=True)
        os.makedirs("data/players", exist_ok=True)

    def fbtokenFix(self):
        # 对异常FbToken的自动修复
        with open("fbtoken", "r", encoding="utf-8") as f:
            token = f.read()
            if "\n" in token:
                Print.print_war("fbtoken里有换行符， 会造成fb登录失败， 已自动修复")
                with open("fbtoken", "w", encoding="utf-8") as f:
                    f.write(token.replace("\n", ""))

    def add_console_cmd_trigger(
        self,
        triggers: list[str],
        arg_hint: str | None,
        usage: str,
        func: Callable[[list[str]], None],
    ):
        # 添加控制台菜单触发词
        #   triggers: 触发词组, arg_hint: 菜单命令参数提示句, usage: 命令说明, func: 菜单回调, 传入命令参数
        try:
            if self.consoleMenu.index(triggers) != -1:
                Print.print_war(f"§6后台指令关键词冲突: {func}, 不予添加至指令菜单")
        except:
            self.consoleMenu.append([usage, arg_hint, func, triggers])

    def init_basic_help_menu(self, _):
        menu = self.get_console_menus()
        Print.print_inf("§a以下是可选的菜单指令项：")
        for usage, arg_hint, _, triggers in menu:
            if arg_hint:
                Print.print_inf(f" §e{' 或 '.join(triggers)} {arg_hint}  §f->  {usage}")
            else:
                Print.print_inf(f" §e{' 或 '.join(triggers)}  §f->  {usage}")

    def comsole_cmd_start(self):
        def _console_cmd_thread():
            self.add_console_cmd_trigger(
                ["?", "help", "帮助"], None, "查询可用菜单指令", self.init_basic_help_menu
            )
            self.add_console_cmd_trigger(
                ["exit"], None, f"退出并关闭{PRG_NAME}", lambda _: self.system_exit()
            )
            try:
                while 1:
                    rsp = input()
                    for _, _, func, triggers in self.consoleMenu:
                        if not rsp:
                            continue
                        elif rsp.split()[0] in triggers:
                            res = _try_execute_console_cmd(func, rsp, 0, None)
                            if res == -1:
                                return
                        else:
                            for tri in triggers:
                                if rsp.startswith(tri):
                                    res = _try_execute_console_cmd(func, rsp, 1, tri)
                                    if res == -1:
                                        return
            except EOFError:
                pass

        def _try_execute_console_cmd(func, rsp, mode, arg1):
            try:
                if mode == 0:
                    rsp_arg = rsp.split()[1:]
                elif mode == 1:
                    rsp_arg = rsp[len(arg1) :].split()
            except IndexError:
                Print.print_err("[控制台执行命令] 指令缺少参数")
                return
            try:
                func(rsp_arg)
                return 1
            except Exception as err:
                if "id 0 out of range 0" in str(err):
                    return -1
                Print.print_err(f"控制台指令出错： {traceback.format_exc()}")
                return 0

        self.createThread(_console_cmd_thread)

    def system_exit(self):
        if self.link_game_ctrl.allplayers:
            # kick @s
            try:
                self.link_game_ctrl.sendwscmd(
                    f"/kick {self.link_game_ctrl.bot_name} ToolDelta 退出中(看到这条消息请重新加入游戏)"
                )
            except:
                pass
        self.safe_close()
        os._exit(0)

    def _get_old_dotcs_env(self):
        # 获取 dotcs 的插件环境
        return old_dotcs_env.get_dotcs_env(self, Print)

    def get_console_menus(self):
        # 获取所有控制台命令菜单
        return self.consoleMenu

    def set_game_control(self, game_ctrl):
        "使用外源GameControl..."
        self.link_game_ctrl = game_ctrl

    def set_plugin_group(self, plug_grp):
        "使用外源PluginGroup..."
        self.link_plugin_group = plug_grp

    def get_game_control(self):
        gcl: GameCtrl = self.link_game_ctrl
        return gcl

    def safe_close(self):
        builtins.safe_close()


class GameCtrl:
    # 游戏连接和交互部分
    def __init__(self, frame: Frame):
        self.linked_frame = frame
        self.players_uuid = {}
        self.allplayers = []
        self.bot_name = ""
        self.linked_frame: Frame
        self.pkt_unique_id: int = 0
        self.pkt_cache: list = []
        self.require_listen_packets = {9, 79, 63}
        self.store_uuid_pkt: dict[str, str] | None = None

    def init_funcs(self):
        self.launcher = self.linked_frame.launcher
        self.launcher.packet_handler = lambda pckType, pck: createThread(
            self.packet_handler, (pckType, pck)
        )
        self.sendcmd = self.launcher.sendcmd
        self.sendwscmd = self.launcher.sendwscmd
        self.sendwocmd = self.launcher.sendwocmd
        self.sendPacket = self.launcher.sendPacket
        self.sendPacketJson = self.launcher.sendPacketJson
        self.sendfbcmd = self.launcher.sendfbcmd
        if isinstance(self.linked_frame.launcher, FrameNeOmg):
            self.requireUUIDPacket = False
        else:
            self.requireUUIDPacket = True

    def set_listen_packets(self):
        # 向启动器初始化监听的游戏数据包
        # 不应该再次调用此方法
        for pktID in self.require_listen_packets:
            self.launcher.add_listen_packets(pktID)

    def add_listen_pkt(self, pkt: int):
        self.require_listen_packets.add(pkt)

    def packet_handler(self, pkt_type: int, pkt: dict):
        if pkt_type == PacketIDS.PlayerList:
            self.process_player_list(pkt, self.linked_frame.link_plugin_group)
        elif pkt_type == PacketIDS.Text:
            self.process_text_packet(pkt, self.linked_frame.link_plugin_group)
        self.linked_frame.linked_plugin_group.processPacketFunc(pkt_type, pkt)

    def process_player_list(self, pkt, plugin_group: PluginGroup):
        # 处理玩家进出事件
        for player in pkt["Entries"]:
            isJoining = bool(player["Skin"]["SkinData"])
            playername = player["Username"]
            if isJoining:
                self.players_uuid[playername] = player["UUID"]
                self.allplayers.append(
                    playername
                ) if playername not in self.allplayers else None
                if not self.requireUUIDPacket:
                    Print.print_inf(f"§e{playername} 加入了游戏, UUID: {player['UUID']}")
                    plugin_group.execute_player_join(
                        playername, self.linked_frame.on_plugin_err
                    )
                else:
                    self.bot_name = pkt["Entries"][0]["Username"]
                    self.requireUUIDPacket = False
            else:
                for k in self.players_uuid:
                    if self.players_uuid[k] == player["UUID"]:
                        playername = k
                        break
                else:
                    Print.print_war("无法获取PlayerList中玩家名字")
                    continue
                self.allplayers.remove(playername) if playername != "???" else None
                Print.print_inf(f"§e{playername} 退出了游戏")
                plugin_group.execute_player_leave(
                    playername, self.linked_frame.on_plugin_err
                )

    def process_text_packet(self, pkt: dict, plugin_grp: PluginGroup):
        # 处理9号数据包的消息, 因特殊原因将一些插件事件放到此处理
        match pkt["TextType"]:
            case 2:
                if pkt["Message"] == "§e%multiplayer.player.joined":
                    player = pkt["Parameters"][0]
                    plugin_grp.execute_player_prejoin(
                        player, self.linked_frame.on_plugin_err
                    )
                if pkt["Message"] == "§e%multiplayer.player.join":
                    player = pkt["Parameters"][0]
                elif pkt["Message"] == "§e%multiplayer.player.left":
                    player = pkt["Parameters"][0]
                elif pkt["Message"].startswith("death."):
                    Print.print_inf(f"{pkt['Parameters'][0]} 失败了: {pkt['Message']}")
                    if len(pkt["Parameters"]) >= 2:
                        killer = pkt["Parameters"][1]
                    else:
                        killer = None
                    plugin_grp.execute_player_death(
                        pkt["Parameters"][0],
                        killer,
                        pkt["Message"],
                        self.linked_frame.on_plugin_err,
                    )
            case 1 | 7:
                player, msg = pkt["SourceName"], pkt["Message"]
                plugin_grp.execute_player_message(
                    player, msg, self.linked_frame.on_plugin_err
                )
                Print.print_inf(f"<{player}> {msg}")
            case 8:
                player, msg = pkt["SourceName"], pkt["Message"]
                Print.print_inf(f"{player} 使用say说: {msg.strip(f'[{player}]')}")
                plugin_grp.execute_player_message(
                    player, msg, self.linked_frame.on_plugin_err
                )
            case 9:
                msg = pkt["Message"]
                try:
                    Print.print_inf(
                        "".join([i["text"] for i in json.loads(msg)["rawtext"]])
                    )
                except:
                    pass

    def Inject(self):
        # 载入游戏时的初始化
        res = self.launcher.get_players_and_uuids()
        if res:
            self.allplayers = list(res.keys())
            self.players_uuid.update(res)
        else:
            while 1:
                try:
                    self.allplayers = (
                        self.sendwscmd("/testfor @a", True)
                        .OutputMessages[0]
                        .Parameters[0]
                        .split(", ")
                    )
                    break
                except TimeoutError:
                    Print.print_war("获取全局玩家失败..重试")
        self.bot_name = self.launcher.get_bot_name()
        if self.bot_name is None:
            self.bot_name = self.allplayers[0]
        self.linked_frame.comsole_cmd_start()
        self.linked_frame.link_plugin_group.execute_init(
            self.linked_frame.on_plugin_err
        )
        self.inject_welcome()

    def inject_welcome(self):
        # 载入游戏后的欢迎提示语
        Print.print_suc(
            "初始化完成, 在线玩家: " + ", ".join(self.allplayers) + ", 机器人ID: " + self.bot_name
        )
        time.sleep(0.5)
        self.say_to("@a", "§l§7[§f!§7] §r§fToolDelta Enabled!")
        self.say_to(
            "@a",
            "§l§7[§f!§7] §r§f北京时间 " + datetime.datetime.now().strftime("§a%H§f : §a%M"),
        )
        self.say_to("@a", "§l§7[§f!§7] §r§f输入.help获取更多帮助哦")
        self.sendcmd("/tag @s add robot")

    def say_to(self, target: str, msg: str):
        # 向玩家发送聊天栏信息
        self.sendwocmd("tellraw " + target + ' {"rawtext":[{"text":"' + msg + '"}]}')

    def player_title(self, target: str, text: str):
        # 向玩家显示大标题
        self.sendwocmd(f"title {target} title {text}")

    def player_subtitle(self, target: str, text: str):
        # 向玩家显示小标题 需要大标题
        self.sendwocmd(f"title {target} subtitle {text}")

    def player_actionbar(self, target: str, text: str):
        # 向玩家显示行动栏信息
        self.sendwocmd(f"title {target} actionbar {text}")


def start_tool_delta():
    # 初始化系统
    global frame, game_control, plugins
    try:
        frame = Frame()
        plugins = PluginGroup(frame, PRG_NAME)
        game_control = GameCtrl(frame)
        frame.set_game_control(game_control)
        frame.set_plugin_group(plugins)
        frame.welcome()
        frame.basic_operation()
        frame.read_cfg()
        game_control.init_funcs()
        plugins.read_plugin_from_old(dotcs_module_env)
        plugins.read_plugin_from_new({
            "Frame": frame,
            "plugins": plugins,
            "Plugin": Plugin,
            "PluginGroup": PluginGroup,
            "PluginAPI": PluginAPI,
            "Config": Config,
            "Builtins": Builtins,
            "Print": Print
        })
        frame.plugin_load_finished(plugins)
        plugins.execute_def(frame.on_plugin_err)
        builtins.tmpjson_save_thread(frame)
        frame.launcher.listen_launched(game_control.Inject)
        game_control.set_listen_packets()
        raise frame.launcher.launch()
    except KeyboardInterrupt:
        frame.safe_close()
    except SystemExit:
        pass
    except:
        print(traceback.format_exc())
    finally:
        frame.safe_close()
        os._exit(0)