import base64
import json
import random
import re

import cv2
import requests
from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class BagelAITools(NTEOneTimeTask, BaseNTETask):
    # ==========================================
    # 配置区域
    # ==========================================

    CONF_MODEL = "调用模型"
    CONF_HELPER_MODE = "文案助手模式"
    CONF_AUTO_AICONFIG = "智能体模式选项"
    CONF_MODEL_URL = "模型调用地址"
    CONF_MODEL_API = "模型调用API_Key"
    CONF_MODEL_NAME = "所调用模型名称"
    CONF_PROMPT_REPLY = "回复模块提示词"
    CONF_PROMPT_POST_TITLE = "发帖标题模块提示词"
    CONF_PROMPT_POST_CONTENT = "发帖内容模块提示词"
    INFO_HELPER_COUNT = "帮助文案生成次数"
    INFO_LIKE_COUNT = "成功按赞次数"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "呗果智能体（支持调用模型）"
        self.description = "自动模式下将自动发帖回帖点赞\n助手模式下可辅助生成各种文案"
        self.icon = FluentIcon.HEART
        self.supported_languages = ["zh_CN"]
        self.instructions = """【呗果智能体】\n自动模式下将自动发帖回帖点赞；\n助手模式下可辅助生成文案。\n支持调用支持图片输入的模型生成文案。\n项目开发版地址与配置教程：<a href="https://github.com/HazukiKaguya/BagelAIToolsDev">呗果智能体</a>"""
        self.default_config.update(
            {
                self.CONF_MODEL: False,
                self.CONF_HELPER_MODE: False,
                self.CONF_AUTO_AICONFIG: ["自动发帖", "自动回帖", "自动按赞", "过滤水贴"],
                self.CONF_MODEL_URL: "",
                self.CONF_MODEL_API: "",
                self.CONF_MODEL_NAME: "qwen/qwen3-vl-4b",
                self.CONF_PROMPT_REPLY: "帮我写一段回复文案，\n直接回复文案本身，\n不要包含任何其他解释性文本，\n语言要俏皮一些，\n回复内容不超过25字符。",
                self.CONF_PROMPT_POST_TITLE: "这是帖子配图，\n帮我写一段发帖用标题，\n直接回复标题本身，\n不要包含任何其他解释性文本，\n语言要俏皮一些，\n标题内容不超过20字符。",
                self.CONF_PROMPT_POST_CONTENT: "帮我写一段发帖用文案，\n直接回复文案本身，\n不要包含任何其他解释性文本，\n语言要俏皮一些，\n文案内容不超过50字符。",
            }
        )
        self.config_description.update(
            {
                self.CONF_MODEL: "关闭后将降级使用本地词库抽取发帖回复文案",
                self.CONF_HELPER_MODE: "开启助手模式后，将只会辅助生成文案",
                self.CONF_AUTO_AICONFIG: "智能体模式选项\n自动回帖会同时点赞",
                self.CONF_MODEL_URL: "使用模型根据图片生成文案，推荐本地部署",
                self.CONF_MODEL_API: "未设置请留空，请勿泄露API_Key！",
                self.CONF_MODEL_NAME: "推荐qwen/qwen3-vl-4b，显存占用较小",
                self.CONF_PROMPT_REPLY: "回复模块提示词，请先调试好文案再使用",
                self.CONF_PROMPT_POST_TITLE: "发帖标题模块提示词，请先调试好文案再使用",
                self.CONF_PROMPT_POST_CONTENT: "发帖内容模块提示词，请先调试好文案再使用",
            }
        )
        options = ["自动发帖", "自动回帖", "自动按赞", "过滤水贴"]
        self.config_type.update(
            {
                self.CONF_AUTO_AICONFIG: {"type": "multi_selection", "options": options},
            }
        )
        self.preset_replies = [
            "非常好的帖子，使我疯狂点赞！",
            "前排围观，给大佬递茶~",
            "火钳刘明，这贴必火！",
            "拍的太好了，强烈支持一波！",
            "好耶、捕获一只宝藏！",
            "太强了，果断收藏点赞三连走起。",
            "这一贴尊嘟太美丽啦！",
            "谁懂，一打开呗果就被美图暴击！",
            "呜呜捕捉到宝藏帖子，果断点赞！",
            "纯路人，但在呗果刷到这个，直接留下回复！",
            "大家快来看，这贴拍的很好！",
            "这拍照技巧我实名羡慕。",
            "天哪这个构图！请狠狠把教程砸向我！",
            "这角色这衣服和场景绝配，种草了！",
            "又是被别人家画质惊艳到的一天。",
            "这个地方在哪呀？好美，我也得去打个卡！",
            "每一张都好看得可以直出当壁纸的程度，爱了爱了。",
            "这光影绝了！是不是偷偷开了什么高级滤镜？",
            "被治愈到了！",
            "多发点爱看！",
            "今天的呗果冲浪体验，因这篇帖子而变得极好~",
            "继续加油高产！",
            "呗主主页还有其他好看的吗？",
            "今日份的美图已被我成功吸收！",
            "忍不住点进来看了好久，支持！",
            "前排围观，大佬吃得太好了吧！",
            "我一直在刷帖，直到我看到了这篇（手动滑稽）",
            "火钳刘明！直觉告诉我这篇在呗果要爆！",
            "满分一百的话，呗主我给101分！",
            "太真实了。",
        ]
        self.preset_posts = [
            "随手一拍",
            "太美丽啦",
            "这角色这衣服这场景绝配",
            "打卡",
            "每张都好看到可以当壁纸的程度",
            "这光影绝了",
            "被治愈到了",
            "继续加油高产",
            "主页还有其他好看的",
            "今日份的美图",
            "吃得太好了吧",
            "直觉告诉我这篇在呗果要爆",
            "太真实了",
        ]
        self.bagel_i18n = {
            "bagel_icon": "呗果",
            "sort_menu_area": "推荐|总热门|最新|今日|本周|关注",
            "sort_menu_select": "最新",
            "reply_area": "说点什么",
            "post_text": "发布",
            "post_check_area": "发布帖子",
            "post_photo_zone_area": "请选择发布内容",
            "confirm": "确认",
            "post_title_area": "请输入标题",
            "post_content_area": "请输入正文",
        }
        self.interacted_posts = set()
        self.reply_count = 0
        self.post_count = 0
        self.like_count = 0
        self.is_running = False
        self.nowview_post = ""
        self.nowview_poster = ""

    # ==========================================
    # 主模块
    # ==========================================

    # 模式判断、异常处理
    def run(self):
        super().run()
        self.is_running = False
        self.gallery_total_count = 1
        self.reply_count = 0
        self.post_count = 0
        self.like_count = 0
        self.info_clear()
        self.log_info("脚本初始化完成！")
        self.sleep(2.56)
        is_helper_mode = self.config.get(self.CONF_HELPER_MODE, True)
        if is_helper_mode:
            self.info_set(self.INFO_HELPER_COUNT, 0)
            self.log_info("当前运行在：呗果文案助手模式")
            self.sleep(1.14)
            target_action = self.do_helper_run
            error_msg = "呗果文案助手出错: "
        else:
            self.info_set("成功发帖次数", 0)
            self.info_set("成功回复次数", 0)
            self.info_set(self.INFO_LIKE_COUNT, 0)
            self.ensure_main(esc=True, time_out=60)

            target_action = self.do_run
            error_msg = "呗果小工具出错"
        try:
            target_action()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error(error_msg, e)
            raise

    # 文案助手模式
    def do_helper_run(self):
        self.is_running = False
        self.log_info("【F1】🟢启动 /🔴暂停 呗果文案助手")
        # 注册快捷键监听
        listener = self.setup_helper_hotkeys()
        try:
            while self.enabled:
                if not self.is_running:
                    self.sleep(1.14)
                    continue
                if self.find_area(area="reply_area"):
                    self.reply_helper()
                    self.info_add(self.INFO_HELPER_COUNT, 1)
                    self.sleep(1.14)
                    continue
                elif self.find_area(area="post_check_area"):
                    if self.find_area(area="post_photo_zone_area"):
                        self.sleep(1.14)
                        continue
                    post_title_area = self.find_area(area="post_title_area")
                    if post_title_area:
                        self.post_helper(area=post_title_area, post_type="title")
                        self.info_add(self.INFO_HELPER_COUNT, 1)
                        self.sleep(1.14)
                        continue
                    post_content_area = self.find_area(area="post_content_area")
                    if post_content_area:
                        self.post_helper(area=post_content_area, post_type="content")
                        self.info_add(self.INFO_HELPER_COUNT, 1)
                        self.sleep(1.14)
                        continue
                    self.sleep(1.14)
                    continue
                else:
                    if self.in_team_and_world():
                        self.log_info("🔴 检测在大世界，呗果文案助手自动暂停！")
                        self.is_running = False
                        continue
                    self.sleep(1.14)
        finally:
            # 卸载快捷键监听
            self.is_running = False
            if listener and listener.running:
                listener.stop()

    # 自动智能体模式
    def do_run(self):
        self.auto_config_list = self.config.get(self.CONF_AUTO_AICONFIG, [])
        # 自动发帖
        ignore_tags = {"过滤水贴"}
        active_tasks = [task for task in self.auto_config_list if task not in ignore_tags]
        if active_tasks:
            self.open_phone()
            self.sleep(1.28)
        if "自动发帖" in self.auto_config_list:
            self.enter_app(app="camera")
            self.sleep(1.28)
            self.process_camera_action(action="take_photo", number=5)
            self.sleep(1.28)
            self.open_phone()
            self.enter_app(app="bagel")
            self.sleep(1.28)
            self.post_module()
            self.log_info("已完成发帖任务！")
            self.sleep(1.28)
            self.open_phone()
            self.sleep(1.28)
            self.enter_app(app="camera")
            self.sleep(1.28)
            self.process_camera_action(action="clear_album", number=5)
            self.sleep(1.28)
            self.open_phone()
            self.sleep(1.28)
        # 自动互动
        if "自动回帖" in self.auto_config_list or "自动按赞" in self.auto_config_list:
            self.enter_app(app="bagel")
            self.sleep(1.28)
            self.reply_like_module()
            self.log_info("已完成回帖按赞任务！")
            self.sleep(1.28)
            self.open_phone()
        self.sleep(1.28)
        self.enter_app(app="bagel")

    # ==========================================
    # 文案助手模块
    # ==========================================

    # 回复助手
    def reply_helper(self):
        post_title = self.find_area(area="post_title", action="get_text")
        if not post_title:
            return False
        post_title_text = post_title[0].name
        poster_name = self.find_area(area="poster_name", action="get_text")
        poster_name_text = "呗主"
        if poster_name:
            poster_name_text = poster_name[0].name
        self.sleep(0.20)
        if (post_title_text == self.nowview_post and self.nowview_poster == poster_name_text) or (
            post_title_text in self.interacted_posts
        ):
            self.sleep(0.50)
            return False
        self.sleep(0.20)
        btn_reply_area = self.find_area(area="reply_area", action="click")
        self.operate_click(btn_reply_area)
        self.sleep(0.20)
        my_reply_text = self.generate_reply_content(
            title_text=post_title_text, author_name=poster_name_text
        )
        self.sleep(0.20)
        self.input_text(my_reply_text)
        self.nowview_post = post_title_text
        self.nowview_poster = poster_name_text
        self.sleep(0.20)
        return True

    # 发帖助手
    def post_helper(self, area=None, post_type="title"):
        if not area:
            return False
        self.sleep(0.50)
        self.operate_click(area)
        self.sleep(0.50)
        # 发帖
        my_reply_text = self.generate_post_content(generate_type=post_type)
        self.sleep(0.50)
        self.input_text(my_reply_text)
        if post_type == "title":
            self.nowview_post = my_reply_text
        self.sleep(0.50)
        return True

    # 注册快捷键
    def setup_helper_hotkeys(self):
        """使用现有的 pynput 注册全局快捷键（返回 listener 实例以便后续销毁）"""
        if getattr(self, "_global_hotkey_listener", None) is not None:
            return self._global_hotkey_listener
        import ctypes

        from pynput import keyboard

        try:
            from pynput._util import win32

            if hasattr(win32, "KeyTranslator"):
                win32.KeyTranslator._ToUnicodeEx.argtypes = [
                    ctypes.c_uint,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                ]
        except Exception:
            pass

        def on_release(key):
            try:
                if key == keyboard.Key.f1:
                    self.is_running = not self.is_running
                    if self.is_running:
                        self.log_info("🟢 呗果文案助手已就绪！")
                    else:
                        self.log_info("🔴 呗果文案助手已暂停！")
            except Exception as e:
                self.log_error(f"快捷键响应异常: {e}")

        listener = keyboard.Listener(on_release=on_release)
        listener.start()
        return listener  # 把实例丢出去

    # ==========================================
    # 智能体模快 回帖按赞相关
    # ==========================================
    _RE_PATTERN_WATER = re.compile(
        r"(互赞|互粉|求.*回|秒回|点赞|回赞|互.*关|留名|顶帖|\bdd\b)", re.IGNORECASE
    )
    _RE_PATTERN_SPAM = re.compile(r"(^[a-z\s]+$|^[0-9\s]+$|^[\W_]+$)", re.IGNORECASE)
    _RE_SPAM_CLEANER = re.compile(r"[\d\s\=\÷\+\*\/\\|\[\]\{\}\(\)\<\>\?¿¡§¶†‡■□▲△▼▽◆◇○●•★☆\-]")

    _RE_ALBUM_PREFER = re.compile(r"(\d+)[/|]\d+")
    _RE_ALBUM_BACKUP = re.compile(r"历史(?:记录)?_?(\d{1,2})")
    _RE_ALBUM_LAST_RESORT = re.compile(r"(\d{1,2})")

    # 回帖按赞操作流程
    def reply_like_module(self):
        if "自动回帖" in self.auto_config_list:
            self.log_info("进行自动回复，同时会按赞")
        elif "自动按赞" in self.auto_config_list:
            self.log_info("进行自动按赞")
        else:
            return

        def find_sort_menu_new():
            return self.find_area(area="sort_menu_area_done")

        is_page_ok = False
        while self.enabled and (self.reply_count < 5 or self.like_count < 5):
            if not find_sort_menu_new():
                self.sleep(1.00)
                btn_sort = self.find_area(area="sort_menu_area", action="click")
                self.wait_until(
                    lambda: (
                        not self.find_area(area="sort_menu_area_done")
                        or not self.find_area(area="sort_menu_list")
                    ),
                    pre_action=lambda btn=btn_sort: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.sleep(3.00)
                btn_sort_list = self.find_area(area="sort_menu_select", action="click")
                self.wait_until(
                    lambda: self.find_area(area="sort_menu_list"),
                    pre_action=lambda btn=btn_sort_list: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.sleep(3.00)
                continue
            if is_page_ok:
                self.sleep(1.14)
                self.scroll_relative(0.50, 0.50, -17)
                is_page_ok = False
                self.sleep(1.14)
                continue
            is_page_ok = self.process_current_page_posts()

    # 回帖按赞互动模块
    def process_current_page_posts(self):
        """互动模块

        `action` 设置为 reply 时，进行回帖操作；设置为 like 时，进行点赞操作。
        """
        posts = self.find_posts()

        if not posts:
            self.log_info("当前页面没有发现符合条件的优质帖子。")
            return True  # 告诉可以翻页了

        for i, post in enumerate(posts):
            if self.reply_count >= 5 and self.like_count >= 5:
                self.log_info("已完成自动回复按赞任务！")
                return False  # 只是返回掉，因为结束了
            if not self.find_area(area="reply_area"):
                self.log_info(f"正在点击目标帖子【{post.name}】")
                self.operate_click(post)
                self.sleep(3.00)  # 等待帖子内容加载
            post_title = self.find_area(area="post_title", action="get_text")
            if not post_title:
                if self.find_area(area="reply_area"):
                    self.send_key("esc")
                self.sleep(2.56)
                continue
            post_title_text = post_title[0].name
            if post_title_text in self.interacted_posts:
                self.send_key("esc")
                self.sleep(2.56)
                continue
            if "自动回帖" in self.auto_config_list and self.reply_count < 5:
                is_reply = self.reply_helper()
                if not is_reply:
                    if self.find_area(area="post_title", action="get_text"):
                        self.send_key("esc")
                    self.sleep(2.56)
                    continue
                self.sleep(2.56)
                self.operate_click(0.90, 0.90)
                self.sleep(0.42)
                self.reply_count += 1
                self.info_add("成功回复次数", 1)
                self.interacted_posts.add(post_title_text)
                self.sleep(0.42)
                self.operate_click(0.53, 0.85)
                self.like_count += 1
                self.info_add(self.INFO_LIKE_COUNT, 1)
            elif "自动按赞" in self.auto_config_list and self.like_count < 5:
                # 点赞
                self.sleep(0.2)
                self.operate_click(0.53, 0.85)
                self.like_count += 1
                self.info_add(self.INFO_LIKE_COUNT, 1)
                self.interacted_posts.add(post_title_text)
            else:
                pass  # 万一以后准备加点啥
            self.sleep(1.14)
            if self.find_area(area="reply_area"):
                self.send_key("esc")
            self.sleep(2.56)
        self.log_info("本页抓取到的所有帖子已全部处理完毕！")
        return True  # 告诉可以翻页了

    # 找贴模块
    def find_posts(self):
        """找贴模块

        1. 如果关闭了反水贴开关，不做任何过滤，返回区域内所有OCR结果。
        2. 开启反水贴时，过滤掉互赞类和无意义类水贴，返回过滤后的OCR结果。
        """
        pre_posts = self.wait_ocr(0.17, 0.30, 0.99, 0.90, time_out=1.14, raise_if_not_found=False)
        all_posts = self.filter_author_names_smart(pre_posts, self.screen_width, self.screen_height)

        if "过滤水贴" not in self.auto_config_list:
            return all_posts

        # 确保 all_posts 是列表结构方便后面遍历
        clean_posts = self.posts_filter(all_posts)
        return clean_posts if clean_posts else None

    # 作者名过滤模块
    def filter_author_names_smart(self, ocr_results, x_threshold=0.03, y_threshold=0.04):
        """
        专为框架 Box 类定制的空间智能过滤器（100% 避开属性缺失坑）
        """
        if not ocr_results:
            return []

        processed_items = []

        for box in ocr_results:
            # 依据 Box.__init__ 文档，利用 x, y, width, height 计算几何中心与边界
            cx_ratio = box.x + (box.width / 2)
            ymin_ratio = box.y
            ymax_ratio = box.y + box.height

            # 文档明确指明 Box.name 存储的就是识别出的文本
            text = box.name

            processed_items.append(
                {
                    "cx_ratio": cx_ratio,
                    "ymin_ratio": ymin_ratio,
                    "ymax_ratio": ymax_ratio,
                    "box_obj": box,
                    "text": text,
                }
            )

        # 1. 按纵坐标 Y 从上到下排序
        processed_items.sort(key=lambda item: item["ymin_ratio"])

        keep_flags = [True] * len(processed_items)

        # 2. 双指针空间碰撞过滤
        for i in range(len(processed_items)):
            if not keep_flags[i]:
                continue
            upper_item = processed_items[i]

            for j in range(i + 1, len(processed_items)):
                if not keep_flags[j]:
                    continue
                lower_item = processed_items[j]

                # 判定横向中心点是否对齐（x 轴偏离在阈值内）
                x_aligned = abs(upper_item["cx_ratio"] - lower_item["cx_ratio"]) < x_threshold
                # 判定纵向是否挨着（下方的左上角 Y 减去上方的右下角 Y，看间距是否在阈值内）
                y_adjacent = (
                    0 <= (lower_item["ymin_ratio"] - upper_item["ymax_ratio"]) < y_threshold
                )

                if x_aligned and y_adjacent:
                    # 标记下方的作者名 Box 不需要保留
                    keep_flags[j] = False
                    break

        # 3. 回传：提取出留下来的原装 Box 对象列表给后面的循环
        return [
            processed_items[idx]["box_obj"]
            for idx in range(len(processed_items))
            if keep_flags[idx]
        ]

    # 水帖过滤模块
    def posts_filter(self, all_posts):
        if not all_posts:
            return None

        # 确保 all_posts 是列表结构方便后面遍历
        if not isinstance(all_posts, list):
            all_posts = [all_posts]

        # water_pattern: 匹配互赞、互粉、求回、秒回、点赞、留名、dd顶帖等
        # spam_char_pattern: 匹配纯数字、纯英文字母、或者全是无意义符号凑字数的垃圾贴（如: "asdfghjk", "11111111", "......"）
        # ^[a-zA-Z0-9\s\W]+$ 配合长度限制，或者直接判定中文字符极少且全是指头狂飙出来的无意义串
        # water_pattern = re.compile(r"(互赞|互粉|求.*回|秒回|点赞|回赞|互.*关|留名|顶帖|\bdd\b)", re.IGNORECASE)
        # spam_char_pattern = re.compile(r"(^[a-zA-Z\s]+$|^[0-9\s]+$|^[\W_]+$)", re.IGNORECASE)

        clean_posts = []

        for post in all_posts:
            # 拿到当前帖子识别出来的文本内容
            text = getattr(post, "name", "").strip()
            if not text:
                continue
            if len(text) < 3:
                self.log_info(f"【拦截】非帖子: '{text}'")
                continue
            meaningful_text = self._RE_SPAM_CLEANER.sub("", text)
            # 检查是否包含互赞关键词
            if self._RE_PATTERN_WATER.search(meaningful_text):
                self.log_info(f"【拦截】互赞贴: '{text}'")
                continue

            # 检查是否是纯无意义乱码/凑字数字符（排除纯英文短词，长度大于5的纯字母/数字更可疑）
            if len(text) > 2 and self._RE_PATTERN_SPAM.match(meaningful_text):
                self.log_info(f"【拦截】垃圾贴: '{text}'")
                continue

            # 正常帖子进入有效列表
            clean_posts.append(post)

        # 返回清洗干净后的帖子列表，如果没有则返回 None
        return clean_posts if clean_posts else None

    # ==========================================
    # 智能体模快 发帖相关
    # ==========================================

    # 发帖操作流程模块
    def post_module(self):
        self.log_info("进行自动发帖")
        while self.enabled and self.post_count < 5:
            self.sleep(2.56)
            if not self.find_area(area="sort_menu_area"):
                self.sleep(0.50)
                self.open_phone()
                self.sleep(0.50)
                self.enter_app(app="bagel")
                self.sleep(5.14)
                continue
            self.wait_until(
                lambda: self.find_area(area="post_check_area"),
                pre_action=lambda: self.operate_click(0.05, 0.93, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
            self.log_info("进入发帖界面")
            self.sleep(1.14)
            if self.find_area(area="post_photo_zone_area"):
                btn_select_photo = self.find_area(area="post_photo_zone_area", action="click")
                self.wait_until(
                    lambda: not self.find_area(area="post_check_area"),
                    pre_action=lambda btn=btn_select_photo: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.log_info("选择发帖用图片")
                self.sleep(1.14)
                # 这里写好选照片的方法
                self.select_latest_photos(
                    photo_new_count=self.post_count + 1, photo_total=self.gallery_total_count
                )
                self.sleep(0.50)
                btn_photo_confirm = self.find_area(area="post_photo_confirm", action="click")
                self.wait_until(
                    lambda: (
                        self.find_area(area="post_check_area")
                        and not self.find_area(area="post_photo_zone_area")
                    ),
                    pre_action=lambda btn=btn_photo_confirm: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.log_info("发帖用图片选择完成")
            self.sleep(1.14)
            if (
                not self.process_bagel_post()
            ):  # 选完照片后调用发帖文案生成并发送方法，返回 True 则说明生成并发布成功了
                continue
            # 扫描“发布”按钮
            btn_post_confirm = self.find_area(area="post_confirm_area", action="click")
            self.sleep(0.50)
            self.wait_until(
                lambda: (
                    self.find_area(area="sort_menu_area")
                    and not self.find_area(area="post_check_area")
                ),
                pre_action=lambda btn=btn_post_confirm: self.operate_click(btn, interval=3.14),
                time_out=60,
                raise_if_not_found=True,
            )
            self.post_count += 1
            self.log_info("成功发帖")
            self.info_add("成功发帖次数", 1)
            self.sleep(5.14)

    # 选图块
    def select_latest_photos(self, photo_new_count=1, photo_total=1):
        """选图模块（单选）

        参数:
            photo_new (int): 代表第几张新图。
                             1 代表最新的一张
                             2 代表次新的一张，以此类推...
        """
        try:
            photo_total = int(photo_total)
        except (ValueError, TypeError):
            self.log_info(
                f"接收到非法的 photo_total: {photo_total} (类型: {type(photo_total).__name__})，已强制启用安全默认值 1"
            )
            photo_total = 1
        # 越界输入归正
        if photo_total > 36:
            photo_total = 36
        elif photo_total < 1:
            photo_total = 1
        if photo_new_count < 1:
            photo_new_count = 1
        elif photo_new_count > photo_total:
            photo_new_count = photo_total
        # 按从旧到新顺序的话是第几位，只会得到0-35的数
        photo_count = photo_total - photo_new_count
        # 根据总照片数归一化
        scroll_times = 0
        while photo_count > 11:
            photo_count -= 4
            scroll_times += 1
        photo_grid_locations = (
            (0.15, 0.25),
            (0.38, 0.25),
            (0.62, 0.25),
            (0.85, 0.25),  # 第一排 1-4
            (0.15, 0.50),
            (0.38, 0.50),
            (0.62, 0.50),
            (0.85, 0.50),  # 第二排 5-8
            (0.15, 0.75),
            (0.38, 0.75),
            (0.62, 0.75),
            (0.85, 0.75),  # 第三排 9-12
        )
        if scroll_times > 0:
            for _ in range(scroll_times):
                if not self.enabled:
                    return
                self.scroll_relative(0.50, 0.50, -8)
                self.sleep(0.25)
            self.sleep(1.00)
        target = photo_grid_locations[photo_count]

        self.log_info(f"正在点击第 {photo_new_count} 张最新图片），坐标: {target}")
        self.operate_click(*target)
        self.sleep(1.14)

    # 正式发帖模块
    def process_bagel_post(self):
        # 先用局部 OCR 确认自己真的在发帖界面
        if not self.find_area(area="post_check_area"):
            self.sleep(1.14)
            return False
        post_title_area = self.find_area(area="post_title_area")
        if post_title_area:
            self.post_helper(area=post_title_area, post_type="title")
        self.sleep(1.14)
        post_content_area = self.find_area(area="post_content_area")
        if post_content_area:
            self.post_helper(area=post_content_area, post_type="content")
        self.sleep(1.14)
        return True

    # 相机拍图删图模块
    def process_camera_action(self, action="clear_album", number=5):
        """拍图/删图模块（单选）

        参数:
            number (int): 代表拍/删几张图。
            action (str):
                - clear_album : 删图
                - take_photo  : 拍图
                    - phone_third : 手机第三人称
                    - phone_self  : 手机自拍
                    - uav_third   : 无人机第三人称
                    - uav_first   : 无人机第一人称
        """
        try:
            number = int(number)
            if number < 1:
                self.log_info(f"接收到非正整数的 number: {number} ，已强制启用默认值 5")
                number = 5
        except (ValueError, TypeError):
            self.log_info(
                f"接收到非法的 number: {number} (类型: {type(number).__name__})，已强制启用默认值 5"
            )
            number = 5

        if action == "clear_album":
            self.sleep(1.14)
            self.operate_click(0.035, 0.94)
            self.log_info("进入相册")
            self.sleep(1.14)
            current_total = self.get_gallery_total()
            if current_total <= number:
                self.log_info("照片总数小于或等于要删除的数量。")
                return True
            if current_total > 12:
                self.log_info("正在将相册推至最底部...")
                for _ in range(6):
                    self.scroll_relative(0.50, 0.50, -8)
                    self.sleep(0.20)
                self.sleep(1.00)
            else:
                self.log_info("总数小于等于12张，静态网格，无需滚动。")

            for i in range(number):
                if not self.enabled:
                    return False
                # 计算最新那张图的绝对索引
                photo_count = current_total - 1
                if current_total > 12:
                    # 如果总数大于12，说明页面此时钉在底部，利用减 4 映射到 0-11 的底部相对格子上
                    while photo_count > 11:
                        photo_count -= 4

                photo_grid_locations = (
                    (0.15, 0.25),
                    (0.38, 0.25),
                    (0.62, 0.25),
                    (0.85, 0.25),  # 0-3
                    (0.15, 0.50),
                    (0.38, 0.50),
                    (0.62, 0.50),
                    (0.85, 0.50),  # 4-7
                    (0.15, 0.75),
                    (0.38, 0.75),
                    (0.62, 0.75),
                    (0.85, 0.75),  # 8-11
                )

                if photo_count < 0 or photo_count > 11:
                    self.log_info(f"计算出的索引 {photo_count} 越界！强制安全到 11")
                    photo_count = 11

                target_target = photo_grid_locations[photo_count]
                self.operate_click(*target_target)
                self.sleep(1.14)
                # 点击物理删除确认
                self.operate_click(0.89, 0.94, action_name="del_photo")
                # 账本同步扣减：物理删一张，内存账本减一张
                current_total -= 1
                self.log_info(f" [{i + 1}/{number}]：删去1张照片，当前剩 {current_total} 张待删除")
                self.sleep(2.56)

        else:
            take_photo_actions = ["phone_third", "phone_self", "uav_third", "uav_first"]

            def take_photo(target_action="phone_third"):
                if target_action == "phone_third":
                    self.log_info("使用手机拍照：第三人称")
                elif target_action == "phone_self":
                    self.operate_click(0.84, 0.05)
                    self.log_info("使用手机拍照：自拍模式")
                    self.sleep(1.14)
                elif target_action in ["uav_third", "uav_first"]:
                    self.operate_click(0.895, 0.05)
                    self.sleep(1.14)
                    if target_action == "uav_first":
                        self.operate_click(0.89, 0.05)
                        self.log_info("使用无人机拍照：第一人称")
                        self.sleep(1.14)
                    else:
                        self.log_info("使用无人机拍照：第三人称")
                else:
                    self.log_info("使用手机拍照：第三人称")

            for i in range(number):
                if not self.enabled:
                    return False
                move_actions = ["w", "a", "s", "d", None]
                current_move_action = random.choice(move_actions)
                if action == "take_photo":
                    current_take_photo_action = random.choice(take_photo_actions)
                else:
                    current_take_photo_action = action
                if current_take_photo_action:
                    take_photo(target_action=current_take_photo_action)
                if current_move_action:
                    move_time = round(random.uniform(0.1, 1.0), 2)
                    self.send_key(current_move_action, down_time=move_time)
                self.log_info(f"正在拍摄第 {i + 1}张照片...")
                # 点击物理快门
                self.sleep(1.14)
                self.send_key("f", down_time=0.15)
                self.sleep(1.14)
                self.send_key("esc", down_time=0.15)
                self.sleep(1.14)
                if current_take_photo_action != "phone_third":
                    self.send_key("esc", down_time=0.15)
                    self.sleep(1.14)
            self.sleep(1.14)
            self.log_info("照片拍摄完毕，进入相册核对总数...")
            self.operate_click(0.035, 0.94)

            self.sleep(1.14)

        # 刷新最终总数
        self.get_gallery_total()
        self.sleep(1.14)
        return True

    # 获取相册相片数
    def get_gallery_total(self):
        gallery_total = self.find_area(area="gallery_total", action="get_text")
        photo_total = 1  # 安全默认值

        # 如果 OCR 没拿到任何东西
        if not gallery_total:
            self.log_info("[匹配失败] 未能找到相册相片数，启用安全值 1 张")
            self.gallery_total_count = photo_total
            return photo_total

        # 全文聚合
        full_ocr_text = "_".join(
            [str(node.name).strip() for node in gallery_total if hasattr(node, "name")]
        )
        self.log_info(f"原始OCR文本: '{full_ocr_text}'")

        match_prefer = self._RE_ALBUM_PREFER.search(full_ocr_text)
        match_backup = self._RE_ALBUM_BACKUP.search(full_ocr_text)
        match_last_resort = self._RE_ALBUM_LAST_RESORT.search(full_ocr_text)

        # 动态对齐
        if match_prefer:
            photo_total = int(match_prefer.group(1))
            self.log_info(f"[精准匹配] 相册相片数: {photo_total}")
        elif match_backup and ("历史" in full_ocr_text or "记录" in full_ocr_text):
            photo_total = int(match_backup.group(1))
            self.log_info(f"[精准匹配] 相册相片数: {photo_total}")
        elif match_last_resort:
            photo_total = int(match_last_resort.group(1))
            self.log_info(f"[模糊匹配] 相册相片数: {photo_total} (原始文本: '{full_ocr_text}')")
        else:
            self.log_info(
                f"[匹配失败] 未能找到相册相片数，启用安全值 1 张，ocr结果为 '{full_ocr_text}'"
            )

        # 返回
        self.gallery_total_count = photo_total
        return photo_total

    # ==========================================
    # 通用工具模块
    # ==========================================

    # 打开手机模块
    def open_phone(self):
        self.wait_until(
            lambda: self.find_area(area="bagel_icon"),
            pre_action=lambda: self.send_key("esc", interval=3.14),
            time_out=30,
            raise_if_not_found=True,
        )
        self.log_info("已打开手机")

    # 进入功能模块
    def enter_app(self, app="bagel"):
        if app == "bagel":
            btn_bagel = self.find_area(area="bagel_icon", action="click")
            self.wait_until(
                lambda: not self.find_area(area="bagel_icon"),
                pre_action=lambda: self.operate_click(btn_bagel, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
        elif app == "camera":
            self.wait_until(
                lambda: not self.find_area(area="bagel_icon"),
                pre_action=lambda: self.operate_click(0.75, 0.875, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
        self.log_info(f"已打开{app}")

    # 区域找寻模块
    def find_area(self, area="reply_area", action=None):
        text_area = []
        # OCR区域的别名和坐标
        configs = {
            "bagel_icon": ((0.71, 0.37, 0.96, 0.80),),
            "gallery_total": ((0.03, 0.12, 0.14, 0.16),),
            "sort_menu_area": ((0.18, 0.10, 0.30, 0.20),),
            "sort_menu_area_done": ((0.18, 0.10, 0.30, 0.20), "sort_menu_select"),
            "sort_menu_list": ((0.18, 0.20, 0.30, 0.50), "sort_menu_area"),
            "sort_menu_select": ((0.18, 0.20, 0.30, 0.50),),
            "reply_area": ((0.70, 0.88, 0.80, 0.93),),
            "post_title": ((0.71, 0.20, 0.98, 0.26),),
            "poster_name": ((0.75, 0.13, 0.88, 0.20),),
            "post_enter_area": ((0.035, 0.89, 0.10, 0.99), "post_text"),
            "post_check_area": ((0.03, 0.08, 0.15, 0.16),),
            "post_photo_zone_area": ((0.25, 0.40, 0.45, 0.55),),
            "post_photo_confirm": ((0.825, 0.875, 0.95, 0.92), "confirm"),
            "post_title_area": ((0.70, 0.18, 0.85, 0.28),),
            "post_content_area": ((0.70, 0.35, 0.85, 0.45),),
            "post_confirm_area": ((0.86, 0.87, 0.97, 0.92), "post_text"),
        }
        if area not in configs:
            return None
        config_item = configs[area]
        ocr_area = config_item[0]  # 第一个元素必然是坐标元组

        if len(config_item) > 1:
            i18n_key = config_item[1]
        else:
            i18n_key = area

        # 若指定了 action = "click"，则采用 wait_ocr，否则采用 ocr 即可
        if action == "click":
            match_regex = re.compile(self.bagel_i18n[i18n_key])
            text_area = self.wait_ocr(
                *ocr_area, match=match_regex, time_out=30, raise_if_not_found=True
            )
        elif action == "get_text":
            text_area = self.ocr(*ocr_area)
        else:
            match_regex = re.compile(self.bagel_i18n[i18n_key])
            text_area = self.ocr(*ocr_area, match=match_regex)
        return text_area

    # 字数审查模块
    def text_length(self, text, max_len=25):
        """
        将回复内容智能控制在指定字数内，优先按标点截断保持语意完整
        """

        # 如果本身就没超限，直接放行
        if len(text) <= max_len:
            return text

        self.log_info(f"VLM 返回文本过长({len(text)}字)，触发25字硬限制截断流: '{text}'")

        # 定义常见的断句标点符号
        punctuations = ["，", "。", "！", "？", "；", "~", ",", ".", "!", "?", ";"]
        # 从第 max_len 个字符开始，逆向（往左）查找标点符号
        for i in range(max_len - 1, -1, -1):
            if text[i] in punctuations:
                # 最近的标点！截取到该标点（包含标点本身）
                trimmed_text = text[: i + 1]
                # 再次确保万无一失（正常情况下这里必然 <= max_len）
                if len(trimmed_text) <= max_len:
                    return trimmed_text

        # 兜底：如果前半句长达25个字里连一个标点都没有，被迫执行硬切断
        return text[: max_len - 1] + "…"

    # 截图获取模块
    def get_frame_by_ratio(self, x_min_ratio, y_min_ratio, x_max_ratio, y_max_ratio):
        """
        强制刷新并获取最新屏幕帧，然后按照屏幕比例进行裁切
        """
        new_frame = self.next_frame()
        if new_frame is None:
            self.log_error("无法获取新屏幕帧，比例裁切失败")
            return None

        height, width = new_frame.shape[:2]

        x_min = int(x_min_ratio * width)
        y_min = int(y_min_ratio * height)
        x_max = int(x_max_ratio * width)
        y_max = int(y_max_ratio * height)

        return new_frame[y_min:y_max, x_min:x_max]

    # 回复生成模块
    def generate_reply_content(self, title_text="帖子", author_name="呗主"):
        """生成回复内容（含降级机制与动态名字拼接）"""
        temp_img_path = ""
        cropped_frame = self.get_frame_by_ratio(0.015, 0.14, 0.98, 0.82)
        if cropped_frame is not None:
            # 将 NumPy 矩阵保存为本地临时图片
            # 如果大模型认出来的颜色很怪，说明截图框架出来的是 RGB，而 OpenCV 默认写出是 BGR
            # 此时可以用这行转换颜色：cropped_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2BGR)

            temp_img_path = "vlm_input_temp.jpg"
            cv2.imwrite(temp_img_path, cropped_frame)
        else:
            temp_img_path = False

        # 如果配置了大模型，图片存在，优先走大模型
        if temp_img_path and self.config.get(self.CONF_MODEL, False):
            try:
                reply_prompt = self.config.get(
                    self.CONF_PROMPT_REPLY,
                    "帮我写一段回复文案，直接回复文案本身，不要包含任何其他解释性文本，语言要俏皮一些，回复内容不超过25字符。",
                )
                model_reply = self.get_vlm_response(
                    reply_prompt, temp_img_path, post_title=title_text, author=author_name
                )
                self.log_info(f"模型生成 | 为帖子【{title_text}】生成回复: '{model_reply}'")
                return model_reply
            except Exception as e:
                self.log_info(f"VLM不可用({e})，降级到本地词库...")

        # 模型生成不可用时，使用本地词库随机回复
        base_reply = random.choice(self.preset_replies)

        # 40% 概率用对方昵称替换通称
        if author_name and author_name != "呗主" and random.random() < 0.4:
            base_reply = base_reply.replace("呗主", author_name).replace("博主", author_name)
        self.log_info(f"本地词库 | 为帖子【{title_text}】随机回复: '{base_reply}'")
        return base_reply

    # 贴文生成模块
    def generate_post_content(self, generate_type="title"):
        """生成发帖内容（含降级机制）"""
        temp_img_path = ""
        action = ""
        cropped_frame = None
        if generate_type == "title":
            action = "发帖标题"
            cropped_frame = self.get_frame_by_ratio(0.015, 0.15, 0.685, 0.82)
        else:
            action = "发帖文案"
            cropped_frame = self.get_frame_by_ratio(0.015, 0.10, 0.980, 0.82)
        if cropped_frame is not None:
            # 将 NumPy 矩阵保存为本地临时图片
            # 如果大模型认出来的颜色很怪，说明截图框架出来的是 RGB，而 OpenCV 默认写出是 BGR
            # 此时可以用这行转换颜色：cropped_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2BGR)
            temp_img_path = "vlm_input_temp.jpg"
            cv2.imwrite(temp_img_path, cropped_frame)
        else:
            temp_img_path = False
        # 如果配置了大模型，图片存在，优先走大模型
        if temp_img_path and self.config.get(self.CONF_MODEL, False):
            try:
                post_prompt = ""
                if generate_type == "title":
                    post_prompt = self.config.get(
                        self.CONF_PROMPT_POST_TITLE,
                        "这是帖子配图，帮我写一段发帖用标题，直接回复标题本身，不要包含任何其他解释性文本，语言要俏皮一些，标题内容不超过20字符。",
                    )
                else:
                    post_prompt = self.config.get(
                        self.CONF_PROMPT_POST_CONTENT,
                        "帮我写一段发帖用文案，直接回复文案本身，不要包含任何其他解释性文本，语言要俏皮一些，文案内容不超过20字符。",
                    )
                model_post = self.get_vlm_response(post_prompt, temp_img_path)
                self.log_info(f"模型生成 | 为所选图片生成{action}: '{model_post}'")
                if generate_type == "title":
                    self.nowview_post = model_post
                return model_post
            except Exception as e:
                self.log_info(f"VLM不可用({e})，降级到本地词库...")

        # 模型生成不可用时，使用本地词库随机选取
        base_post = random.choice(self.preset_posts)
        self.log_info(f"本地词库 | 为所选图片随机选取{action}: '{base_post}'")
        return base_post

    # 模型调用模块
    def get_vlm_response(self, prompt, post_img_path, post_title=None, author=None):
        """
        使用原生 requests 调用 VLM 模型（支持从 /v1/models 自动抓取真名，完美兼容 llama.cpp/LM Studio）
        """
        base_url = self.config.get(self.CONF_MODEL_URL, "http://127.0.0.1:1234").rstrip("/")
        api_key = self.config.get(self.CONF_MODEL_API, "")
        if api_key and len(api_key) > 7:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        else:
            headers = {
                "Content-Type": "application/json",
            }
        # ==========================================
        # 动态从 /v1/models 探测当前模型名
        # ==========================================
        model_name = "local-model"  # 缺省兜底值
        preferred_model = self.config.get(self.CONF_MODEL_NAME, "qwen/qwen3-vl-4b")  # 指定主导模型
        models_url = f"{base_url}/v1/models"
        models_response = requests.get(models_url, headers=headers, timeout=3)
        if models_response.status_code == 200:
            models_data = models_response.json()
            if "data" in models_data and len(models_data["data"]) > 0:
                # 提取出当前后端所有可用的模型 ID 列表
                available_model_ids = [m["id"] for m in models_data["data"]]
                # 策略 1：检查我们最爱的 qwen/qwen3-vl-4b 在不在里面
                if preferred_model in available_model_ids:
                    model_name = preferred_model
                    self.log_info(f"成功加载指定模型: '{model_name}'")
                # 指定的模型不在，找其它视觉模型代替
                else:
                    vl_models = [mid for mid in available_model_ids if "-vl" in mid.lower()]
                    if vl_models:
                        model_name = vl_models[0]
                        self.log_info(f"未找到指定模型，加载其他视觉模型: '{model_name}'")
                    # 没有视觉模型，抛出异常降级到本地词库
                    else:
                        raise RuntimeError("未找到指定模型和其他视觉模型")

        # ==========================================
        # 后续的标准 Vision 请求逻辑
        # ==========================================
        api_url = f"{base_url}/v1/chat/completions"

        final_prompt = prompt
        if post_title or author:
            final_prompt += "\n\n【目标帖子信息】"
            if post_title:
                final_prompt += f"\n标题: {post_title}"
            if author:
                final_prompt += f"\n发帖者: {author}"

        # 转图片 Base64
        with open(post_img_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")

        # 组装完整的 Payload
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": final_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ],
                }
            ],
            "temperature": 0.7,
            "max_tokens": 150,
        }

        self.log_info("正在向后端发送推理请求...")
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=30)

        if response.status_code == 200:
            model_reply = response.json()["choices"][0]["message"]["content"].strip()
            if not model_reply:
                raise RuntimeError(f"VLM 返回内容异常, 详情: {response.text}")
            model_reply = self.text_length(model_reply, max_len=25)
            return model_reply
        else:
            raise RuntimeError(
                f"VLM 推理失败，HTTP 状态码: {response.status_code}, 详情: {response.text}"
            )
