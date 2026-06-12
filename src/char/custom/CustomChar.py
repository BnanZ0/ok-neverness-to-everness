import ast
from typing import Any, Callable, List, NamedTuple

from src.char.BaseChar import BaseChar
from src.char.custom.CustomCharManager import CustomCharManager
from src.combat.planner import (
    ActionSlot,
    ActionTag,
    EntryChainPolicy,
    FieldPreference,
    Role,
    RoleProfile,
)


class Cmd(NamedTuple):
    name: str
    func: Callable[..., Any]
    params: str
    doc: str
    example: str
    if_capable: bool = False


class CustomChar(BaseChar):
    """
    用户自定义的出招表角色。
    它从 CustomCharManager 获取出招表，并作为 planner 动作执行。
    """

    def __init__(self, task, index, char_name=None, confidence=1):
        super().__init__(task, index, char_name, confidence)
        self.manager = CustomCharManager()
        self.combo_label = ""
        self.combo_str = ""
        self.parsed_combo = []
        self._load_combo()

    def _load_combo(self):
        char_info = self.manager.get_character_info(self.char_name)
        if char_info:
            combo_ref = self.manager.to_combo_ref(char_info.get("combo_ref", ""))
            self.combo_label = self.manager.to_combo_label(combo_ref)
            self.combo_str = self.manager.get_combo(combo_ref)
            self._compile_combo()
        else:
            self.logger.warning(f"No custom char info found for {self.char_name}")

    def describe_role(self):
        return RoleProfile(role=Role.SUB_DPS, field_preference=FieldPreference.SUB_DPS)

    def combat_intents(self, context):
        if not self.parsed_combo:
            return super().combat_intents(context)

        tags = {ActionTag.LEGACY_COMBO, ActionTag.DAMAGE}
        reason = "legacy combo ready"
        if self.skill_available():
            tags.add(ActionTag.SKILL_ACTION)
            reason = "legacy combo skill available"
        if self.ultimate_available():
            tags.add(ActionTag.ULTIMATE_ACTION)

        return self.intents(
            self.planner_action(
                name="legacy_combo",
                tags=tags,
                slot=ActionSlot.LEGACY_COMBO,
                execute=self.execute_legacy_combo_action,
                reason=reason,
                chain_policy=EntryChainPolicy.STOP,
            )
        )

    def execute_legacy_combo_action(self, context=None):
        self._execute_parsed_combo()
        return True

    @classmethod
    def get_command_definitions(cls) -> List[Cmd]:
        # 统一在此处配置所有可用指令：指令名、对应内置函数
        PARAM_NONE = "无参数"
        PARAM_OPT_DURATION = "持续时间(s)，选填"
        PARAM_OPT_KEY = "按键，选填"
        PARAM_REQ_KEY = "按键，必填"
        DOC_MOUSE_BUTTON = "鼠标按键left、right、middle, 不填默认left"
        return [
            Cmd(
                "skill",
                cls.custom_click_skill,
                "按下秒数, 默认0.01秒",
                "释放技能",
                "skill, skill(0.5)",
                True,
            ),
            Cmd("ultimate", cls.click_ultimate, PARAM_NONE, "释放终结技", "ultimate", True),
            Cmd("arc", cls.click_arc, PARAM_NONE, "释放弧盘技能", "arc", False),
            Cmd(
                "l_click",
                cls.smart_left_click,
                PARAM_OPT_DURATION,
                "鼠标左键。带参数则连点鼠标左键指定秒数，无参数为单次点按",
                "l_click, l_click(3)",
            ),
            Cmd(
                "r_click",
                cls.smart_right_click,
                PARAM_OPT_DURATION,
                "鼠标右键。带参数则连点鼠标右键指定秒数，无参数为单次点按",
                "r_click, r_click(2)",
            ),
            Cmd(
                "l_hold",
                cls.heavy_attack,
                PARAM_OPT_DURATION,
                "按住鼠标左键。带参数则指定秒数",
                "l_hold, l_hold(2)",
            ),
            Cmd(
                "r_hold",
                cls.hold_right_click,
                PARAM_OPT_DURATION,
                "按住鼠标右键。带参数则指定秒数",
                "r_hold, r_hold(2)",
            ),
            Cmd("wait", cls.sleep, "等待时间(s)，必填", "休眠停顿等待指定时间", "wait(0.5)"),
            Cmd("jump", cls.jump, PARAM_NONE, "跳跃一下", "jump"),
            Cmd(
                "walk",
                cls.walk,
                "按键方向、持续时间(s)，必填",
                "控制角色向指定方向行走",
                "walk(w, 0.2)",
            ),
            Cmd(
                "mousedown",
                cls.mousedown,
                PARAM_OPT_KEY,
                DOC_MOUSE_BUTTON,
                "mousedown, mousedown(left)",
            ),
            Cmd("mouseup", cls.mouseup, PARAM_OPT_KEY, DOC_MOUSE_BUTTON, "mouseup, mouseup(right)"),
            Cmd(
                "click", cls.command_click, PARAM_OPT_KEY, DOC_MOUSE_BUTTON, "click, click(middle)"
            ),
            Cmd("keydown", cls.keydown, PARAM_REQ_KEY, "按下按键", "keydown(a)"),
            Cmd("keyup", cls.keyup, PARAM_REQ_KEY, "松开按键", "keyup(d)"),
            Cmd("keypress", cls.keypress, PARAM_REQ_KEY, "按下并松开按键", "keypress(f1)"),
            Cmd(
                "if_",
                cls._execute_if_command,
                "条件命令、一个或多个目标命令",
                "条件执行：仅可使用标记为（可用于 if_ 条件）的命令作为条件命令",
                "if_(ultimate, skill), if_(skill(0.5), l_click(2), wait(0.1))",
            ),
        ]

    def _compile_combo(self):
        """将字符串代码预编译为可以直接执行的 [(target, args, kwargs, cmd)] 缓存结构"""
        self.parsed_combo = []
        if not self.combo_str:
            return

        parsed_combo, error = self.compile_combo_text(self.combo_str)
        if error:
            self.logger.error(f"Syntax error parsing combo '{self.combo_str}': {error}")
            return
        self.parsed_combo = parsed_combo

    @staticmethod
    def _node_loc(node) -> str:
        line = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", None)
        if line is None:
            return ""
        col_num = (col + 1) if isinstance(col, int) else 1
        return f"line {line}, column {col_num}"

    @staticmethod
    def _syntax_error_text(error: SyntaxError) -> str:
        line = error.lineno or 1
        col = error.offset or 1
        return f"line {line}, column {col}: {error.msg}"

    @classmethod
    def _parse_node_value(cls, node):
        try:
            return True, ast.literal_eval(node), ""
        except (ValueError, SyntaxError):
            if isinstance(node, ast.Name):
                return True, node.id, ""
            return False, None, f"{cls._node_loc(node)}: unsupported value expression"

    @classmethod
    def _resolve_target(cls, func_name: str, aliases: dict[str, Callable[..., Any]]):
        target = aliases.get(func_name, func_name)
        if not callable(target) and not hasattr(cls, func_name):
            return None
        return target

    @classmethod
    def _parse_if_command(
        cls,
        node: ast.Call,
        combo_str: str,
        aliases: dict[str, Callable[..., Any]],
        if_capable_map: dict[str, bool],
    ):
        if node.keywords:
            return None, f"{cls._node_loc(node)}: if_ only supports positional arguments"
        if len(node.args) < 2:
            return (
                None,
                f"{cls._node_loc(node)}: if_ requires at least 2 positional arguments: "
                f"if_(cond, then1, ...)",
            )

        cond_node = node.args[0]
        then_nodes = node.args[1:]
        cond_cmd, err = cls._parse_command_node(
            cond_node,
            combo_str=combo_str,
            aliases=aliases,
            if_capable_map=if_capable_map,
            allow_if=False,
        )
        if err:
            return None, err

        cond_name = cond_cmd[0]
        if not if_capable_map.get(cond_name, False):
            return (
                None,
                f"{cls._node_loc(cond_node)}: command '{cond_name}' is not enabled as "
                f"if_ condition",
            )

        then_cmds = []
        for then_node in then_nodes:
            then_cmd, err = cls._parse_command_node(
                then_node,
                combo_str=combo_str,
                aliases=aliases,
                if_capable_map=if_capable_map,
                allow_if=False,
            )
            if err:
                return None, err
            then_cmds.append(then_cmd)

        cmd_text = ast.get_source_segment(combo_str, node) or "if_"
        return ("if_", cls._execute_if_command, [cond_cmd, then_cmds], {}, cmd_text), None

    @classmethod
    def _parse_command_node(
        cls,
        node,
        combo_str: str,
        aliases: dict[str, Callable[..., Any]],
        if_capable_map: dict[str, bool],
        allow_if: bool = True,
    ):
        func_name = ""
        args = []
        kwargs = {}

        if isinstance(node, ast.Name):
            func_name = node.id
            if func_name == "if_":
                return (
                    None,
                    f"{cls._node_loc(node)}: if_ must be called with arguments, "
                    f"e.g. if_(ultimate, skill, wait(0.1))",
                )
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return None, f"{cls._node_loc(node)}: unsupported callable expression"
            func_name = node.func.id

            if func_name == "if_":
                if not allow_if:
                    return None, f"{cls._node_loc(node)}: nested if_ is not supported"
                return cls._parse_if_command(node, combo_str, aliases, if_capable_map)

            for arg in node.args:
                ok, value, err = cls._parse_node_value(arg)
                if not ok:
                    return None, err
                args.append(value)

            for kw in node.keywords:
                if kw.arg is None:
                    return None, f"{cls._node_loc(kw)}: **kwargs syntax is not supported"
                ok, value, err = cls._parse_node_value(kw.value)
                if not ok:
                    return None, err
                kwargs[kw.arg] = value
        else:
            return None, f"{cls._node_loc(node)}: unsupported syntax '{type(node).__name__}'"

        if not func_name:
            return None, f"{cls._node_loc(node)}: command name is required"

        target = cls._resolve_target(func_name, aliases)
        if target is None:
            return None, f"{cls._node_loc(node)}: unknown command '{func_name}'"

        cmd_text = ast.get_source_segment(combo_str, node) or func_name
        return (func_name, target, args, kwargs, cmd_text), None

    @classmethod
    def compile_combo_text(cls, combo_str: str):
        """
        Compile combo text into executable tuples.
        Returns (parsed_combo, error_message). error_message is None when valid.
        """
        parsed_combo = []
        if not combo_str or not combo_str.strip():
            return parsed_combo, None

        command_defs = cls.get_command_definitions()
        aliases = {cmd.name: cmd.func for cmd in command_defs}
        if_capable_map = {cmd.name: cmd.if_capable for cmd in command_defs}

        try:
            tree = ast.parse(combo_str)
        except SyntaxError as error:
            return [], cls._syntax_error_text(error)

        for stmt in tree.body:
            if not isinstance(stmt, ast.Expr):
                return [], f"{cls._node_loc(stmt)}: only command expressions are allowed"

            expr = stmt.value
            nodes = expr.elts if isinstance(expr, ast.Tuple) else [expr]
            for node in nodes:
                parsed_command, err = cls._parse_command_node(
                    node,
                    combo_str=combo_str,
                    aliases=aliases,
                    if_capable_map=if_capable_map,
                    allow_if=True,
                )
                if err:
                    return [], err
                parsed_combo.append(parsed_command)

        return parsed_combo, None

    @classmethod
    def validate_combo_syntax(cls, combo_str: str):
        _, error = cls.compile_combo_text(combo_str)
        return error is None, error

    def _execute_parsed_combo(self):
        """战斗时极速遍历并执行已缓存的指令队列"""
        for command in self.parsed_combo:
            try:
                self._execute_compiled_command(command)
            except Exception as e:
                cmd = command[4] if len(command) >= 5 else "unknown"
                self.logger.error(f"Error executing command '{cmd}'", e)

            # 中途打断逻辑
            self.check_combat()

    def _execute_compiled_command(self, command):
        func_name, target, args, kwargs, _ = command
        if callable(target):
            self.logger.debug(f"Executing Custom Combo Command: {func_name}(*{args}, **{kwargs})")
            return target(self, *args, **kwargs)

        if hasattr(self, target):
            func = getattr(self, target)
            self.logger.debug(f"Executing Custom Combo Command: {target}(*{args}, **{kwargs})")
            return func(*args, **kwargs)

        self.logger.warning(f"Unknown command in combo: {target}")
        return None

    def _execute_if_command(self, condition_cmd, then_cmds):
        cond_result = self._execute_compiled_command(condition_cmd)
        if not isinstance(cond_result, bool):
            self.logger.warning(
                f"if_ condition command '{condition_cmd[0]}' returned non-bool value, "
                f"treat as False"
            )
            return False

        if not cond_result:
            return False

        for then_cmd in then_cmds:
            self._execute_compiled_command(then_cmd)
        return True

    @classmethod
    def get_available_commands(cls):
        """
        手动定义对用户可视化/输入框提示的出招表指令及文档说明。
        """
        return cls.get_command_definitions()

    def jump(self):
        self.send_key("space")

    def smart_left_click(self, duration=None):
        if duration is None:
            self.normal_attack()
        else:
            self.continues_normal_attack(duration)

    def smart_right_click(self, duration=None):
        if duration is None:
            self.click(key="right")
        else:
            self.continues_right_click(duration)

    def hold_right_click(self, duration=0.01):
        self.click(key="right", down_time=duration)

    def walk(self, direction, duration):
        self.send_key(direction, down_time=duration)

    def mousedown(self, key="left"):
        self.task.mouse_down(key=key)

    def mouseup(self, key="left"):
        self.task.mouse_up(key=key)

    def command_click(self, key="left"):
        self.task.click(key=key)

    def keydown(self, key):
        self.task.send_key_down(key)

    def keyup(self, key):
        self.task.send_key_up(key)

    def keypress(self, key):
        self.task.send_key(key=key)

    def custom_click_skill(self, down_time=0.01) -> bool:
        return self.click_skill(down_time=down_time)
