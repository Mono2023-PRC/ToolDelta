"插件市场客户端"

import asyncio
import time
import traceback
import requests
import json
from pathlib import Path
from urllib.parse import urlsplit
from rich import print as rich_print
from rich.markdown import Markdown
from .utils import cfg, fmts
from .constants import (
    TOOLDELTA_CLASSIC_PLUGIN_PATH,
    TOOLDELTA_PLUGIN_CFG_DIR,
    TOOLDELTA_PLUGIN_DATA_DIR,
    PLUGIN_MARKET_SOURCE_OFFICIAL,
)
from .plugin_load import PluginRegData, PluginsPackage
from .utils import try_int, thread_gather, urlmethod

FILETREE = dict[str, "int | FILETREE"]
REMOTE_PLUGIN_DATA_DIR = "插件数据文件"
REMOTE_PLUGIN_CONFIG_DIR = "插件配置文件"
DECENTRALIZED_MARKET_FILE = "marketplace.json"


def url_join(*urls: str) -> str:
    """拼接 URL 或 URL 风格路径片段。"""
    return "/".join(url.strip("/") for url in urls).strip("/")


def unfold_directory_dict(dirs: FILETREE, base_path: str = "", sep: str = "/"):
    """将插件市场目录树展开为相对文件路径列表。"""
    unfolded: list[str] = []
    for dirname, dir_or_file in dirs.items():
        dirpath = sep.join((base_path, dirname)).strip("/")
        if isinstance(dir_or_file, dict):
            unfolded.extend(unfold_directory_dict(dir_or_file, dirpath, sep))
        else:
            unfolded.append(dirpath)
    return unfolded


def get_json_from_url(url: str):
    """从 URL 读取 JSON，并把网络和解析错误转换成统一异常。"""
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise requests.RequestException(
            f"URL 请求失败: {url} \n§6(看起来您要更改配置文件中的链接)\n报错: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise requests.RequestException(
            f"服务器返回了不正确的答复：{resp.text}"
        ) from exc


def _split_github_repo_url(repo_url: str) -> tuple[str, str, str] | None:
    """拆分 GitHub 仓库链接，返回 owner/repo、分支和仓库内前缀路径。"""
    parsed = urlsplit(repo_url)
    if parsed.netloc != "github.com":
        return None
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(parts) < 2:
        return None
    repo_path = "/".join(parts[:2])
    branch = "main"
    path_prefix = ""
    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]
        path_prefix = "/".join(parts[4:])
    return repo_path, branch, path_prefix


def github_repo_to_raw_url(repo_url: str, path: str = "", branch: str = "") -> str:
    """将 GitHub 仓库 URL 转换为 raw content URL（支持镜像加速）。"""
    repo_info = _split_github_repo_url(repo_url)
    if repo_info is None:
        return url_join(repo_url, path) if path else repo_url

    repo_path, url_branch, path_prefix = repo_info
    raw_branch = branch or url_branch
    raw_path = url_join(path_prefix, path) if path_prefix else path
    raw_url = f"https://raw.githubusercontent.com/{repo_path}/{raw_branch}"
    if raw_path:
        raw_url = url_join(raw_url, raw_path)

    mirror = urlmethod.get_global_github_src_url()
    if mirror and mirror.rstrip("/") != "https://github.com":
        return f"{mirror.rstrip('/')}/{raw_url}"
    return raw_url


def github_api_url(repo_url: str, path: str = "", branch: str = "") -> str:
    """将 GitHub 仓库 URL 转换为 contents API URL（支持 ghproxy 镜像）。"""
    repo_info = _split_github_repo_url(repo_url)
    if repo_info is None:
        return url_join(repo_url, path) if path else repo_url

    repo_path, url_branch, path_prefix = repo_info
    api_branch = branch or url_branch
    api_path = url_join(path_prefix, path) if path_prefix else path
    api_url = f"https://api.github.com/repos/{repo_path}/contents"
    if api_path:
        api_url = url_join(api_url, api_path)
    api_url = f"{api_url}?ref={api_branch}"

    mirror = urlmethod.get_global_github_src_url()
    if mirror and "ghproxy" in mirror:
        return f"{mirror.rstrip('/')}/{api_url}"
    return api_url


class PluginMarket:
    "插件市场类"

    def __init__(self):
        """初始化插件市场客户端并读取配置中的市场源。"""
        self._cached_market_tree = {}
        self._cached_plugins_id_map = {}
        self._cached_market_filetree: FILETREE = {}
        self._cached_marketplace_data = {}
        self._is_decentralized: bool | None = None
        try:
            self.plugin_market_content_url = cfg.get_cfg(
                "ToolDelta基本配置.json", {"插件市场源": str}
            )["插件市场源"]
        except Exception:
            self.plugin_market_content_url = PLUGIN_MARKET_SOURCE_OFFICIAL

    def enter_plugin_market(self, source_url: str | None = None, in_game=False) -> None:
        """
        进入插件市场

        Args:
            source_url (str | None, optional): 插件市场源
            in_game (bool, optional): 是否在游戏内调用的插件市场命令
        """
        if source_url:
            self.plugin_market_content_url = source_url
            self._clear_market_cache()

        fmts.ansi_save_screen()
        fmts.clean_print("§6正在连接到插件市场..")
        CONTENT_LENGTH = 15

        try:
            market_datas = self.get_market_tree()
            plugin_ids_map = self.get_plugin_id_name_map()
            show_list = [
                (i, j) if i.startswith("[pkg]") else ("[pkg]" + i, j)
                for i, j in market_datas["Packages"].items()
            ] + list(market_datas["MarketPlugins"].items())

            while True:
                fmts.ansi_cls()
                valid_show_list = self.search_by_rule(market_datas, show_list)
                if valid_show_list is None:
                    fmts.clean_print("§6已退出。")
                    return
                elif valid_show_list == []:
                    input(fmts.clean_fmt("§c未找到匹配的插件; 回车键继续"))
                    continue

                total_indexes = len(valid_show_list)
                now_index = 0
                sum_pages = (total_indexes - 1) // CONTENT_LENGTH + 1
                last_operation = ""

                while True:
                    self.display_plugins_and_packages(
                        market_datas,
                        plugin_ids_map,
                        valid_show_list,
                        now_index,
                        sum_pages,
                        CONTENT_LENGTH,
                    )

                    last_operation = (
                        input(
                            fmts.clean_fmt("§f回车键继续上次操作, §bq§f 退出，请输入: ")
                        )
                        or last_operation
                    )
                    last_operation = last_operation.lower().strip()
                    if last_operation in ["+", "-"]:
                        now_index = max(
                            0,
                            min(
                                now_index
                                + (
                                    CONTENT_LENGTH
                                    if last_operation == "+"
                                    else -CONTENT_LENGTH
                                ),
                                total_indexes - 1,
                            ),
                        )
                    elif last_operation == "q":
                        break
                    else:
                        res = try_int(last_operation)
                        if res and 1 <= res <= total_indexes:
                            result = valid_show_list[res - 1]
                            if not result[0].startswith("[pkg]"):
                                # 这是插件
                                plugin_data = self.get_plugin_data_from_market(
                                    result[0]
                                )
                                if self.handle_plugin_selection(plugin_data):
                                    break
                            else:
                                # 这是整合包
                                package_data = self.get_package_data_from_market(
                                    result[0]
                                )
                                if self.handle_package_selection(package_data):
                                    break
                        else:
                            fmts.clean_print("§c超出序号范围")

        except (KeyError, requests.RequestException) as err:
            fmts.clean_print(
                f"§c获取插件市场插件出现问题({err.__class__.__name__}): {err}"
            )
            input(fmts.clean_fmt("§6按回车键继续.."))
        except Exception:
            fmts.clean_print("§c获取插件市场插件出现问题, 报错如下:")
            fmts.clean_print("§c" + traceback.format_exc().replace("\n", "\n§c"))
            input(fmts.clean_fmt("§6按回车键继续.."))
        finally:
            fmts.ansi_load_screen()
            fmts.clean_print("§a已从插件市场返回 ToolDelta 控制台。")

    def _clear_market_cache(self) -> None:
        """清除当前市场源相关缓存。"""
        self._cached_market_tree = {}
        self._cached_plugins_id_map = {}
        self._cached_market_filetree = {}
        self._cached_marketplace_data = {}
        self._is_decentralized = None

    def is_decentralized_market(self) -> bool:
        """当前插件市场是否为分布式格式。"""
        if self._is_decentralized is None:
            self._detect_market_type()
        return bool(self._is_decentralized)

    def _detect_market_type(self) -> None:
        """自动检测市场类型：分布式 marketplace.json 或传统中心市场。"""
        try:
            marketplace_url = url_join(
                self.plugin_market_content_url, DECENTRALIZED_MARKET_FILE
            )
            data = get_json_from_url(marketplace_url)
            if "$meta" in data:
                self._is_decentralized = True
                self._cached_marketplace_data = data
                fmts.clean_print("§a检测到分布式插件市场格式")
                return
        except Exception:
            pass
        self._is_decentralized = False
        fmts.clean_print("§a使用传统插件市场格式")

    def get_decentralized_market_data(self) -> dict:
        """获取分布式市场插件数据，不包含 $meta。"""
        if not self._cached_marketplace_data:
            marketplace_url = url_join(
                self.plugin_market_content_url, DECENTRALIZED_MARKET_FILE
            )
            self._cached_marketplace_data = get_json_from_url(marketplace_url)
        return {k: v for k, v in self._cached_marketplace_data.items() if k != "$meta"}

    def _get_decentralized_market_tree(self) -> dict:
        """将分布式市场索引转换成传统 UI 可复用的数据结构。"""
        meta = self._cached_marketplace_data.get("$meta", {})
        market_plugins = self.get_decentralized_market_data()
        return {
            "SourceName": meta.get("name", "插件市场"),
            "Greetings": meta.get("greetings", "分布式插件市场"),
            "Packages": {},
            "MarketPlugins": market_plugins,
        }

    def get_decentralized_plugin_id_name_map(self) -> dict[str, str]:
        """获取分布式市场的插件 ID 到市场 key 的映射。"""
        if self._cached_plugins_id_map:
            return self._cached_plugins_id_map

        plugin_ids_map = {}
        for plugin_key, plugin_info in self.get_decentralized_market_data().items():
            plugin_id = plugin_info.get("plugin-id", plugin_key)
            plugin_name = plugin_info.get("name", plugin_key.split("/")[-1])
            plugin_ids_map[plugin_id] = plugin_key
            plugin_ids_map[plugin_key] = plugin_name
        self._cached_plugins_id_map = plugin_ids_map
        return plugin_ids_map

    def get_market_plugins(self) -> dict[str, dict]:
        """获取当前市场的插件索引，兼容传统和分布式格式。"""
        return self.get_market_tree()["MarketPlugins"]

    def get_market_plugin_info(self, plugin_id: str) -> dict | None:
        """按插件 ID、市场 key 或插件名获取当前市场中的插件摘要信息。"""
        market_plugins = self.get_market_plugins()
        if not self.is_decentralized_market():
            return market_plugins.get(plugin_id)

        try:
            _, plugin_info = self._find_decentralized_plugin(plugin_id)
        except requests.RequestException:
            return None
        return plugin_info

    @staticmethod
    def search_by_rule(
        market_datas, show_list: list[tuple[str, dict]]
    ) -> list[tuple[str, dict]] | None:
        """按用户选择的规则过滤插件和整合包列表。"""
        source_name = market_datas.get("SourceName", "插件市场")
        greetings = market_datas.get("Greetings", "")
        fmts.clean_print(f"{source_name}: {greetings}")
        fmts.clean_print("§a------------------------------")
        fmts.clean_print("§6请选择搜索方式: ")
        fmts.clean_print("  1 -     §b按插件名")
        fmts.clean_print("  2 -     §d按插件作者名")
        fmts.clean_print("  3 -     §e按插件 ID")
        fmts.clean_print("  4 -     §a随便逛逛")
        fmts.clean_print("  其它    §c退出")
        resp = input(fmts.clean_fmt("请输入选项: ")).strip().strip("[]")
        output_show_list: list[tuple[str, dict]] = []
        match resp:
            case "1":
                plugin_name_kw = (
                    input(fmts.clean_fmt("§6请输入插件名(中的关键词): "))
                    .strip()
                    .lower()
                )
                if plugin_name_kw == "":
                    return []
                for plugin_id, plugin_data in show_list:
                    pname = (
                        plugin_id
                        if plugin_id.startswith("[pkg]")
                        else plugin_data.get("name", plugin_id)
                    )
                    if plugin_name_kw in pname.lower():
                        output_show_list.append((plugin_id, plugin_data))
                return output_show_list
            case "2":
                plugin_author_kw = (
                    input(fmts.clean_fmt("§6请输入插件作者名(中的关键词): "))
                    .strip()
                    .lower()
                )
                if plugin_author_kw == "":
                    return []
                for plugin_name, plugin_data in show_list:
                    if plugin_author_kw in plugin_data.get("author", "").lower():
                        output_show_list.append((plugin_name, plugin_data))
                return output_show_list
            case "3":
                plugin_id_kw = (
                    input(fmts.clean_fmt("§6请输入插件ID(中的关键词): "))
                    .strip()
                    .lower()
                )
                if plugin_id_kw == "":
                    return []
                for plugin_id, plugin_data in show_list:
                    plugin_id_value = plugin_data.get("plugin-id", plugin_id)
                    if plugin_id_kw in plugin_id_value or plugin_id_kw in plugin_id:
                        output_show_list.append((plugin_id, plugin_data))
                return output_show_list
            case "4":
                return show_list
            case _:
                return None

    def display_plugins_and_packages(
        self,
        market_datas: dict,
        plugin_ids_map: dict[str, str],
        show_list: list[tuple[str, dict]],
        start_index: int,
        total_pages: int,
        content_length: int = 15,
    ):
        """
        显示插件列表

        Args:
            start_index (int): 起始索引
            total_pages (int): 总页数
        """
        fmts.ansi_cls()
        source_name = market_datas.get("SourceName", "插件市场")
        greetings = market_datas.get("Greetings", "")
        fmts.clean_print(f"{source_name}: {greetings}")
        for i in range(start_index, min(start_index + content_length, len(show_list))):
            show_name, description = show_list[i]
            if show_name.startswith("[pkg]"):
                pkg_name = show_name
                fmts.clean_print(f" {i + 1}. §c[整合包]§e{pkg_name[5:]}")
            else:
                plugin_id = show_name
                plugin_name = description.get(
                    "name", plugin_ids_map.get(plugin_id, plugin_id)
                )
                plugin_type = {"classic": "类式"}.get(
                    description.get("plugin-type", "unknown"),
                    description.get("plugin-type", "unknown"),
                )
                version = description.get("version", "0.0.0")
                author = description.get("author", "unknown")
                fmts.clean_print(
                    f" {i + 1}. §e{plugin_name} §av{version} "
                    f"§b@{author} §d{plugin_type}插件"
                )
        fmts.clean_print(
            f"§f第§a{start_index // content_length + 1}§f/§a{total_pages}§f页, 输入§b+§f/§b-§f翻页"
        )
        fmts.clean_print("§f输入插件序号选中插件并查看其下载页")

    def handle_package_selection(self, pack: PluginsPackage):
        """处理用户选中整合包后的下载或返回操作。"""
        ok = self.skim_package(pack)
        if ok:
            fmts.clean_print("可以输入 §breload§r 使这个整合包生效哦")
            return (
                input(fmts.clean_fmt("§f输入 §cq §f退出, 其他则返回插件市场")).lower()
                == "q"
            )
        else:
            fmts.clean_print("已取消。")
            time.sleep(1)
        return False

    def handle_plugin_selection(self, plugin_data: PluginRegData):
        """处理用户选中插件后的下载或返回操作。"""
        ok, _ = self.skim_plugin(plugin_data)
        if ok:
            fmts.clean_print("可以输入 §breload§r 使这个插件生效哦")
            return (
                input(fmts.clean_fmt("输入 §cq §r退出, 其他则返回插件市场")).lower()
                == "q"
            )
        else:
            fmts.clean_print("已取消。")
            time.sleep(1)
        return False

    # 从插件市场的 market_tree.json 获取数据
    def get_market_tree(self) -> dict:
        """获取当前市场的完整索引，兼容传统和分布式格式。"""
        if self.is_decentralized_market():
            return self._get_decentralized_market_tree()
        if self._cached_market_tree != {}:
            return self._cached_market_tree
        market_datas = self._cached_market_tree = get_json_from_url(
            url_join(self.plugin_market_content_url, "market_tree.json")
        )
        return market_datas

    # 从插件市场获取单个插件数据
    def get_plugin_data_from_market(self, plugin_id: str) -> PluginRegData:
        """从当前市场按插件 ID 或市场 key 获取插件注册数据。"""
        if self.is_decentralized_market():
            return self._get_plugin_data_from_decentralized_market(plugin_id)

        plugin_name = self.get_plugin_id_name_map().get(plugin_id)
        if plugin_name is None:
            raise requests.RequestException(
                f"无法通过 ID: {plugin_id} 查找插件, 你可能需要反馈此问题至开发者"
            )
        data_url = url_join(self.plugin_market_content_url, plugin_name, "datas.json")
        datas = get_json_from_url(data_url)
        return PluginRegData(plugin_name, datas)

    def _get_plugin_data_from_decentralized_market(
        self, plugin_key: str
    ) -> PluginRegData:
        """从分布式市场的插件仓库读取 datas.json 或摘要数据。"""
        plugin_key, plugin_info = self._find_decentralized_plugin(plugin_key)
        repo_url = plugin_info.get("repo", "")
        if not repo_url:
            raise requests.RequestException(f"插件 {plugin_key} 没有配置仓库地址")

        plugin_name = plugin_info.get("name", plugin_key.split("/")[-1])
        branch = plugin_info.get("branch", "")

        for remote_dir in self._get_decentralized_source_dirs(plugin_info, plugin_name):
            datas_url = github_repo_to_raw_url(
                repo_url, url_join(remote_dir, "datas.json"), branch
            )
            try:
                datas = get_json_from_url(datas_url)
                return PluginRegData(plugin_name, datas)
            except requests.RequestException:
                continue

        datas = {
            "author": plugin_info.get("author", ""),
            "version": plugin_info.get("version", "0.0.0"),
            "description": plugin_info.get("desc", plugin_info.get("description", "")),
            "plugin-id": plugin_info.get("plugin-id", plugin_key),
            "plugin-type": plugin_info.get("plugin-type", "classic"),
            "pre-plugins": plugin_info.get("pre-plugins", {}),
        }
        return PluginRegData(plugin_name, datas)

    def _find_decentralized_plugin(self, plugin_key: str) -> tuple[str, dict]:
        """在分布式市场中按 key、插件 ID 或插件名查找插件摘要。"""
        market_data = self.get_decentralized_market_data()
        plugin_info = market_data.get(plugin_key)
        if plugin_info is not None:
            return plugin_key, plugin_info

        for key, info in market_data.items():
            if info.get("plugin-id") == plugin_key or info.get("name") == plugin_key:
                return key, info

        raise requests.RequestException(f"无法通过 ID: {plugin_key} 查找插件")

    @staticmethod
    def _get_decentralized_source_dirs(
        plugin_info: dict, plugin_name: str
    ) -> list[str]:
        """生成分布式插件仓库内可能的源码目录。"""
        candidates = [
            plugin_info.get("path", ""),
            plugin_info.get("dir", ""),
            plugin_info.get("plugin-path", ""),
            plugin_info.get("plugin_dir", ""),
            plugin_name,
            "",
        ]
        source_dirs: list[str] = []
        for candidate in candidates:
            candidate = str(candidate).strip("/")
            if candidate not in source_dirs:
                source_dirs.append(candidate)
        return source_dirs

    # 从插件市场获取单个整合包数据
    def get_package_data_from_market(self, name: str) -> PluginsPackage:
        """从传统市场获取整合包注册数据。"""
        if self.is_decentralized_market():
            raise requests.RequestException("分布式插件市场暂不支持整合包")
        target_data_url = url_join(self.plugin_market_content_url, name, "datas.json")
        resp = requests.get(target_data_url)
        resp.raise_for_status()
        content = resp.json()
        return PluginsPackage(name, content)

    def skim_plugin(
        self, plugin_data: PluginRegData
    ) -> tuple[bool, list[PluginRegData]]:
        """
        选中插件进行介绍与操作

        Args:
            plugin_data (PluginRegData): 插件注册数据

        Returns:
            tuple[bool, list[PluginRegData]]: 是否下载，下载的插件列表
        """
        pre_plugins_str = (
            ", ".join([f"{k}§7v{v}" for k, v in plugin_data.pre_plugins.items()])
            or "无"
        )
        has_doc = self._plugin_has_doc(plugin_data)
        while True:
            fmts.ansi_cls()
            fmts.clean_print(f"{plugin_data.name} v{plugin_data.version_str}")
            fmts.clean_print(
                f"作者: §f{plugin_data.author}§7, 版本: §f{plugin_data.version_str} §b{plugin_data.plugin_type_str}"
            )
            fmts.clean_print(f"前置插件：§f{pre_plugins_str}")
            fmts.clean_print(f"介绍：{plugin_data.description}")
            fmts.clean_print("")
            prompt = f"§f下载 = §aY§f, 取消 = §cN§f{', 查看文档 = §dD§f ' if has_doc else ''} 请输入: "
            res = input(fmts.clean_fmt(prompt)).lower().strip()
            if res == "y":
                fmts.clean_print(f"§6正在下载插件：§f{plugin_data.name}", end="\r")
                pres = self.download_plugin(plugin_data)
                pres.reverse()
                return True, pres
            elif res == "d":
                if has_doc:
                    fmts.clean_print("§6正在读取文档..")
                    self.lookup_plugin_doc(plugin_data)
                else:
                    fmts.clean_print("§c该插件没有文档..")
                return False, []
            else:
                return False, []

    def skim_package(self, pack: PluginsPackage) -> bool:
        """
        选中整合包进行介绍与操作

        Args:
            pack (PluginsPackage): 整合包数据类

        Returns:
            bool: 是否下载安装
        """
        fmts.ansi_cls()
        inc_plugins_name: list[str] = []
        for pid in pack.plugin_ids:
            if pname := self.get_plugin_id_name_map().get(pid):
                inc_plugins_name.append(pname)
            else:
                fmts.clean_print(f"§c无法通过ID {pid} 查找插件, 有可能是插件市场出错")
                return True
        fmts.clean_print(f"§f整合包 §b{pack.name[5:]} §7(v{pack.version})§r:")
        fmts.clean_print(f"作者: §b{pack.author}")
        fmts.clean_print("介绍: §f" + pack.description.replace("\n", "\n      "))
        fmts.clean_print("§d包含的插件的列表:")
        for pname in inc_plugins_name:
            fmts.clean_print(f" §7- §r{pname}")
        # 显示其他文件数量
        ftree = self.get_market_filetree()
        dirdata = ftree.get(pack.name)
        if dirdata is None:
            raise ValueError(f"插件市场内不存在整合包 {pack.name}")
        plugin_config_files = ftree.get(
            url_join(pack.name, REMOTE_PLUGIN_CONFIG_DIR), {}
        )
        assert not isinstance(plugin_config_files, int)
        # 计算插件配置文件数量
        config_files_num = len(unfold_directory_dict(plugin_config_files))
        # 计算插件数据文件数量
        data_file_dir = ftree.get(url_join(pack.name, "插件数据文件"), {})
        assert not isinstance(data_file_dir, int)
        data_files_num = len(unfold_directory_dict(data_file_dir))
        fmts.clean_print(
            f"§2并包含§r{config_files_num}§2个插件配置文件, §r{data_files_num}§2个插件数据文件"
        )
        if (
            input(fmts.clean_fmt("§f下载安装 = §aY§f, 取消 = §cN§f, 请输入："))
            .lower()
            .strip()
        ) == "y":
            self.download_plugin_package(pack)
            return True
        else:
            return False

    def download_plugin_package(self, pack: PluginsPackage):
        """下载传统市场整合包及其附带配置、数据文件。"""
        fmts.clean_print("§6获取插件数据中...", end="\r")
        find_plugins = thread_gather(
            [(self.get_plugin_data_from_market, (i,)) for i in pack.plugin_ids]
        )
        ftree = self.get_market_filetree()
        dirdata = ftree.get(pack.name)
        if dirdata is None:
            raise ValueError(f"插件市场内不存在整合包 {pack.name}")
        plugin_config_files = ftree.get(
            url_join(pack.name, REMOTE_PLUGIN_CONFIG_DIR), {}
        )
        plugin_data_files = ftree.get(url_join(pack.name, "插件数据文件"), {})
        assert not isinstance(plugin_config_files, int)
        assert not isinstance(plugin_data_files, int)
        download_url_dirs: list[tuple[str, Path]] = []
        # 插件配置文件
        for cfgfile_path in unfold_directory_dict(plugin_config_files):
            f_url = url_join(
                self.plugin_market_content_url,
                pack.name,
                REMOTE_PLUGIN_CONFIG_DIR,
                cfgfile_path,
            )
            f_local = TOOLDELTA_PLUGIN_CFG_DIR / cfgfile_path
            if f_local.is_file() and (
                input(
                    fmts.clean_fmt(
                        f"§6配置文件 §r{cfgfile_path}§6 已存在, 是否替换§r(§a[默认]y§r/§cn§r)§6: "
                    )
                )
                .strip()
                .lower()
                != "n"
            ):
                download_url_dirs.append((f_url, f_local))
        # 插件数据文件
        for inc_file_path in unfold_directory_dict(plugin_data_files):
            # url: [pkg]pkg_name/插件数据文件/anydir/...
            # local: 插件数据文件/anydir/...
            f_url = url_join(
                self.plugin_market_content_url, pack.name, "插件数据文件", inc_file_path
            )
            f_local = TOOLDELTA_PLUGIN_DATA_DIR / inc_file_path
            if not f_local.is_file() or (
                input(
                    fmts.clean_fmt(
                        f"§6数据文件 §r{f_local}§6 已存在, 是否替换§r(§ay§r/§cn[默认]§r)§6: "
                    )
                )
                .strip()
                .lower()
                == "y"
            ):
                download_url_dirs.append((f_url, f_local))
        fmts.clean_print(f"§6开始下载整合包 {pack.name.replace('[pkg]', '')}")
        for _, fpath in download_url_dirs:
            # 初始化需要的文件夹路径
            fpath.mkdir(parents=True, exist_ok=True)
        asyncio.run(urlmethod.download_file_urls(download_url_dirs))
        # 下载插件主体
        for plugin in find_plugins:
            self.download_plugin(plugin)
        fmts.clean_print("整合包下载完成")

    # 下载插件
    def download_plugin(
        self, plugin_data: PluginRegData, with_pres=True, is_enabled=False
    ) -> list[PluginRegData]:
        """下载插件本体，并按需递归下载前置插件。"""
        if self.is_decentralized_market():
            return self._download_plugin_from_decentralized(
                plugin_data, with_pres, is_enabled
            )

        fmts.clean_print(
            f"§6正在获取 §f{plugin_data.name} §6插件的下载任务清单.." + " " * 15,
            end="\r",
        )
        if with_pres:
            plugin_list = self.get_plugin_download_list(plugin_data)
        else:
            plugin_list = {plugin_data.name: plugin_data}
        plugin_filepaths_dict: dict[str, list[str]] = {}
        for plugin_name, plugin_data in plugin_list.items():
            plugin_filepaths_dict[plugin_name] = unfold_directory_dict(
                self.get_plugin_filetree(plugin_data.name)
            )
        fmts.clean_print(f"§a已获取插件下载清单 §f{plugin_data.name}§a" + " " * 15)
        plugin_remote_to_local_path: list[tuple[str, Path]] = []
        for plugin_name, this_plugin_info in plugin_list.items():
            match this_plugin_info.plugin_type:
                case "classic":
                    _ = TOOLDELTA_CLASSIC_PLUGIN_PATH  # ignore this?
                case _:
                    raise ValueError(
                        f"未知插件类型：{this_plugin_info.plugin_type}, 你可能需要通知 ToolDelta 项目开发组解决"
                    )
            for filepath in plugin_filepaths_dict[plugin_name]:
                plugin_remote_to_local_path.append(
                    (
                        url_join(
                            self.plugin_market_content_url,
                            this_plugin_info.name,
                            filepath,
                        ),
                        this_plugin_info.dir / filepath,
                    )
                )
        fmts.clean_print(
            f"§bTD下载管理器: §7需要下载 §c{len(plugin_remote_to_local_path)} §7个文件"
        )
        asyncio.run(urlmethod.download_file_urls(plugin_remote_to_local_path))
        fmts.clean_print("§a• 插件安装已完成")
        return list(plugin_list.values())

    def _download_plugin_from_decentralized(
        self, plugin_data: PluginRegData, with_pres=True, is_enabled=False
    ) -> list[PluginRegData]:
        """从分布式市场插件仓库下载插件文件。"""
        fmts.clean_print(
            f"§6正在获取 §f{plugin_data.name} §6插件的下载任务清单.." + " " * 15,
            end="\r",
        )
        if with_pres:
            plugin_list = self.get_plugin_download_list(plugin_data)
        else:
            plugin_data.is_enabled = is_enabled
            plugin_list = {plugin_data.name: plugin_data}

        plugin_remote_to_local_path: list[tuple[str, Path]] = []

        for plugin_name, this_plugin_info in plugin_list.items():
            match this_plugin_info.plugin_type:
                case "classic":
                    _ = TOOLDELTA_CLASSIC_PLUGIN_PATH
                case _:
                    raise ValueError(
                        f"未知插件类型：{this_plugin_info.plugin_type}, 你可能需要通知 ToolDelta 项目开发组解决"
                    )

            try:
                _, plugin_info = self._find_decentralized_plugin(
                    this_plugin_info.plugin_id
                )
            except requests.RequestException:
                _, plugin_info = self._find_decentralized_plugin(plugin_name)

            repo_url = plugin_info.get("repo", "")
            branch = plugin_info.get("branch", "")

            if not repo_url:
                raise requests.RequestException(f"插件 {plugin_name} 没有配置仓库地址")

            remote_dir, filepaths = self._get_decentralized_plugin_filelist(
                repo_url, plugin_name, branch, plugin_info
            )
            for filepath in filepaths:
                plugin_remote_to_local_path.append(
                    (
                        github_repo_to_raw_url(
                            repo_url, url_join(remote_dir, filepath), branch
                        ),
                        this_plugin_info.dir / filepath,
                    )
                )

        fmts.clean_print(f"§a已获取插件下载清单 §f{plugin_data.name}§a" + " " * 15)
        fmts.clean_print(
            f"§bTD下载管理器: §7需要下载 §c{len(plugin_remote_to_local_path)} §7个文件"
        )
        asyncio.run(urlmethod.download_file_urls(plugin_remote_to_local_path))
        fmts.clean_print("§a• 插件安装已完成")
        return list(plugin_list.values())

    def _get_decentralized_plugin_filelist(
        self,
        repo_url: str,
        plugin_name: str,
        branch: str = "",
        plugin_info: dict | None = None,
    ) -> tuple[str, list[str]]:
        """获取分布式插件所在远程目录及该目录下实际文件列表。"""
        if plugin_info is None:
            plugin_info = {}
        source_dirs = self._get_decentralized_source_dirs(plugin_info, plugin_name)

        for remote_dir in source_dirs:
            filelist_url = github_repo_to_raw_url(
                repo_url, url_join(remote_dir, "filelist.json"), branch
            )
            try:
                filelist = get_json_from_url(filelist_url)
                if isinstance(filelist, list):
                    return remote_dir, [str(path) for path in filelist]
            except requests.RequestException:
                pass

        for remote_dir in source_dirs:
            filelist = self._get_github_repo_filelist(repo_url, remote_dir, branch)
            if filelist:
                return remote_dir, filelist

        filelist = self._probe_decentralized_common_files(repo_url, source_dirs, branch)
        if filelist is not None:
            return filelist

        raise requests.RequestException(f"无法获取插件 {plugin_name} 的文件列表")

    def _get_github_repo_filelist(
        self, repo_url: str, remote_dir: str, branch: str = ""
    ) -> list[str]:
        """递归获取 GitHub 仓库中插件目录的文件列表。"""
        try:
            repo_info = _split_github_repo_url(repo_url)
            if repo_info is not None:
                filelist: list[str] = []
                path_prefix = repo_info[2]
                remote_root = url_join(path_prefix, remote_dir)

                def fetch_dir(path: str) -> None:
                    """递归读取 GitHub contents API 目录并收集相对文件路径。"""
                    api_url = github_api_url(repo_url, path, branch)
                    resp = requests.get(api_url, timeout=15)
                    resp.raise_for_status()
                    contents = resp.json()
                    if isinstance(contents, dict):
                        contents = [contents]

                    for item in contents:
                        if item["type"] == "file":
                            rel_path = item["path"]
                            if remote_root and rel_path.startswith(remote_root + "/"):
                                rel_path = rel_path[len(remote_root) + 1 :]
                            filelist.append(rel_path)
                        elif item["type"] == "dir":
                            next_path = item["path"]
                            if path_prefix and next_path.startswith(path_prefix + "/"):
                                next_path = next_path[len(path_prefix) + 1 :]
                            fetch_dir(next_path)

                fetch_dir(remote_dir)
                if filelist:
                    return filelist
        except Exception:
            pass

        return []

    def _probe_decentralized_common_files(
        self, repo_url: str, source_dirs: list[str], branch: str
    ) -> tuple[str, list[str]] | None:
        """在无法列目录时探测常见插件文件，且只返回实际存在的文件。"""
        common_files = [
            "__init__.py",
            "main.py",
            "datas.json",
            "requirements.txt",
            "readme.md",
            "readme.txt",
        ]
        for remote_dir in source_dirs:
            existing_files: list[str] = []
            for filename in common_files:
                file_url = github_repo_to_raw_url(
                    repo_url, url_join(remote_dir, filename), branch
                )
                try:
                    resp = requests.head(file_url, timeout=5)
                    if resp.status_code == 200:
                        existing_files.append(filename)
                except requests.RequestException:
                    continue
            if existing_files:
                return remote_dir, existing_files
        return None

    def _plugin_has_doc(self, plugin: PluginRegData) -> bool:
        """判断市场中的插件是否提供 readme 文档。"""
        if self.is_decentralized_market():
            try:
                _, plugin_info = self._find_decentralized_plugin(plugin.plugin_id)
            except requests.RequestException:
                _, plugin_info = self._find_decentralized_plugin(plugin.name)

            repo_url = plugin_info.get("repo", "")
            branch = plugin_info.get("branch", "")
            if not repo_url:
                return False
            source_dirs = self._get_decentralized_source_dirs(plugin_info, plugin.name)
            for remote_dir in source_dirs:
                for filename in ("readme.md", "readme.txt"):
                    doc_url = github_repo_to_raw_url(
                        repo_url, url_join(remote_dir, filename), branch
                    )
                    try:
                        if requests.head(doc_url, timeout=3).status_code == 200:
                            return True
                    except Exception:
                        continue
            return False

        filetree = self.get_plugin_filetree(plugin.name)
        return (
            filetree.get("readme.txt") is not None
            or filetree.get("readme.md") is not None
        )

    def lookup_plugin_doc(self, plugin: PluginRegData):
        """在线查看当前市场中插件的 readme 文档。"""
        if self.is_decentralized_market():
            try:
                _, plugin_info = self._find_decentralized_plugin(plugin.plugin_id)
            except requests.RequestException:
                _, plugin_info = self._find_decentralized_plugin(plugin.name)

            repo_url = plugin_info.get("repo", "")
            branch = plugin_info.get("branch", "")
            if repo_url:
                source_dirs = self._get_decentralized_source_dirs(
                    plugin_info, plugin.name
                )
                for remote_dir in source_dirs:
                    for filename, markdown in (
                        ("readme.md", True),
                        ("readme.txt", False),
                    ):
                        url = github_repo_to_raw_url(
                            repo_url, url_join(remote_dir, filename), branch
                        )
                        try:
                            resp = requests.get(url, timeout=5)
                        except requests.RequestException:
                            continue
                        if resp.status_code != 200:
                            continue

                        content = resp.content.decode()
                        fmts.ansi_cls()
                        fmts.clean_print(f"§b文档正文 (原始编码:{resp.encoding}):")
                        if markdown:
                            rich_print(Markdown(content))
                        else:
                            fmts.clean_print(content)
                        input(fmts.clean_fmt("§a已经读完正文了 [Enter]"))
                        return

            fmts.clean_print(
                "§c该插件没有插件文档 (readme.txt / readme.md) [回车键继续]"
            )
            input()
            return

        filetree = self.get_plugin_filetree(plugin.name)
        if filetree.get("readme.txt") is not None:
            url = url_join(
                self.plugin_market_content_url,
                plugin.name,
                "readme.txt",
            )
            markdown = False
        elif filetree.get("readme.md") is not None:
            url = url_join(
                self.plugin_market_content_url,
                plugin.name,
                "readme.md",
            )
            markdown = True
        else:
            fmts.clean_print(
                "§c该插件没有插件文档 (readme.txt / readme.md) [回车键继续]"
            )
            input()
            return
        resp = requests.get(url)
        if resp.status_code != 200:
            fmts.clean_print("§c无法获取插件文档")
            return
        content = resp.content.decode()
        fmts.ansi_cls()
        fmts.clean_print(f"§b文档正文 (原始编码:{resp.encoding}):")
        if markdown:
            rich_print(Markdown(content))
        else:
            fmts.clean_print(content)
        input(fmts.clean_fmt("§a已经读完正文了 [Enter]"))

    # 获取插件 ID 到插件名的映射
    def get_plugin_id_name_map(self) -> dict[str, str]:
        """获取插件 ID 到插件市场条目名称的映射。"""
        if self.is_decentralized_market():
            return self.get_decentralized_plugin_id_name_map()

        if self._cached_plugins_id_map == {}:
            try:
                res = get_json_from_url(
                    url_join(self.plugin_market_content_url, "plugin_ids_map.json")
                )
            except Exception as err:
                fmts.clean_print(
                    f"§c从 {self.plugin_market_content_url} 获取插件信息遇到问题: {err}"
                )
                raise SystemExit
            self._cached_plugins_id_map = res
            return res
        else:
            return self._cached_plugins_id_map

    # 获取一个插件所需下载的所有插件 -> dict[插件名, 插件数据]
    def get_plugin_download_list(
        self, plugin_data: PluginRegData
    ) -> dict[str, PluginRegData]:
        """获取目标插件及其所有前置插件的数据。"""
        download_paths: dict[str, PluginRegData] = {}
        stack = [plugin_data]
        while stack:
            current_plugin = stack.pop()
            download_paths[current_plugin.name] = current_plugin
            for plugin_id in current_plugin.pre_plugins:
                plugin_datas = self.get_plugin_data_from_market(plugin_id)
                stack.append(plugin_datas)
        return download_paths

    # 获取插件市场的文件目录结构
    def get_market_filetree(self) -> FILETREE:
        """获取传统市场 directory_tree.json 文件目录结构。"""
        if self.is_decentralized_market():
            raise requests.RequestException("分布式插件市场不提供 directory_tree.json")
        if self._cached_market_filetree == {}:
            self._cached_market_filetree = get_json_from_url(
                url_join(self.plugin_market_content_url, "directory_tree.json")
            )
        return self._cached_market_filetree

    # 获取单个插件的插件文件夹目录结构
    def get_plugin_filetree(self, plugin_name: str) -> FILETREE:
        """获取传统市场中单个插件目录的文件树。"""
        tree = self.get_market_filetree().get(plugin_name)
        if tree is None:
            raise KeyError(f"无法通过名称: {plugin_name} 获取此插件下载项")
        if isinstance(tree, dict):
            return tree
        else:
            raise ValueError(f"名称 {plugin_name} 是文件而非目录")

    # 根据插件 ID 获取插件的最新版本号
    def get_latest_plugin_version(self, plugin_id: str) -> tuple[int, int, int]:
        """根据插件 ID 获取当前市场记录的最新版本号。"""
        if self.is_decentralized_market():
            _, plugin_info = self._find_decentralized_plugin(plugin_id)
            version_str = plugin_info.get("version", "0.0.0")
            try:
                ver = tuple(int(i) for i in version_str.split("."))
                assert len(ver) == 3
            except Exception:
                raise ValueError(f"插件版本号字符串 {version_str!r} 不正确")
            return ver[0], ver[1], ver[2]

        result = get_json_from_url(
            url_join(self.plugin_market_content_url, "latest_versions.json")
        ).get(plugin_id)
        if result is None:
            raise KeyError(f"无法通过 ID: {plugin_id} 获取最新插件版本")
        try:
            ver = tuple(int(i) for i in result.split("."))
            assert len(ver) == 3
        except Exception:
            raise ValueError(f"插件版本号字符串 {result!r} 不正确")
        return ver[0], ver[1], ver[2]


market = PluginMarket()
