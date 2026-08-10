from requests.exceptions import RequestException
from ..utils import fmts
from ..plugin_market import market
from . import regist_extend_function
from .basic import ExtendFunction


@regist_extend_function
class FastPluginDownload(ExtendFunction):
    def __init__(self, frame):
        """初始化插件快捷安装扩展。"""
        super().__init__(frame)

    def when_activate(self):
        """注册 plg add 控制台命令。"""
        super().when_activate()
        self.frame.add_console_cmd_trigger(
            ["plg add"],
            "插件 ID",
            "使用 ToolDelta Wiki 的插件市场快捷安装插件",
            self.on_fast_download_plugin,
        )

    def on_fast_download_plugin(self, args: list[str]):
        """按插件 ID 从当前市场快捷安装插件或传统整合包。"""
        plugin_id = " ".join(args)
        plugin_info = market.get_market_plugin_info(plugin_id)
        if plugin_info is not None:
            try:
                data = market.get_plugin_data_from_market(plugin_id)
                market.download_plugin(data)
                return
            except RequestException as err:
                fmts.print_err(f"无法快捷安装插件: {err}")
                return

        market_datas = market.get_market_tree()
        if (
            not market.is_decentralized_market()
            and plugin_id in market_datas["Packages"]
        ):
            try:
                data = market.get_package_data_from_market(f"[pkg]{plugin_id}")
                market.download_plugin_package(data)
            except RequestException as err:
                fmts.print_err(f"无法快捷安装整合包: {err}")
                return
        else:
            fmts.print_err(f"未找到插件或整合包 {plugin_id}")
