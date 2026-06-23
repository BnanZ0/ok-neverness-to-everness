from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from src.char.custom.CustomChar import Cmd, CustomChar
from src.team_axis.BaseTeamAxis import BaseTeamAxis, TeamAxisError

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar


def _split_example_commands(example: str) -> list[str]:
    parts = []
    current = []
    depth = 0
    quote = ""
    escape = False

    for char in example:
        if quote:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue

        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1

        if char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                parts.append(item)
            current = []
            continue

        current.append(char)

    item = "".join(current).strip()
    if item:
        parts.append(item)
    return parts


def _prefixed_example(example: str, command_name: str, prefixed_name: str) -> str:
    examples = []
    for item in _split_example_commands(str(example or command_name)):
        item = item.strip()
        if not item:
            continue
        if item == command_name:
            examples.append(prefixed_name)
        elif item.startswith(f"{command_name}("):
            examples.append(f"{prefixed_name}{item[len(command_name):]}")
        else:
            examples.append(f"{prefixed_name}({item})")
    return ", ".join(examples) or prefixed_name


def _slot_command(slot_index: int, command_name: str) -> Callable:
    def execute(axis: "CustomTeamAxis", *args, **kwargs):
        return axis.execute_slot_command(slot_index, command_name, *args, **kwargs)

    execute.__name__ = f"p{slot_index + 1}_{command_name}"
    return execute


class TeamAxisComboCompiler(CustomChar):
    """Parser facade that reuses the character combo syntax for team-axis commands."""

    @classmethod
    def get_command_definitions(cls):
        return CustomTeamAxis.get_command_definitions()

    def _execute_if_command(self, condition_cmd, then_cmds):
        cond_result = self._execute_compiled_command(condition_cmd)
        if not isinstance(cond_result, bool):
            self.task.log_debug(
                f"team axis if_ condition '{condition_cmd[0]}' returned non-bool"
            )
            return False

        if not cond_result:
            return False

        for then_cmd in then_cmds:
            self._execute_compiled_command(then_cmd)
        return True


@dataclass(frozen=True)
class CustomTeamAxisDefinition:
    axis_id: str
    name: str
    description: str
    content: str
    team_signature: tuple[str, ...]
    enabled: bool = True
    priority: int = -100

    @property
    def team_labels(self) -> tuple[str, ...]:
        return self.team_signature

    @property
    def opening_steps(self) -> tuple[str, ...]:
        return tuple(line.strip() for line in self.content.splitlines() if line.strip())

    @property
    def cycle_steps(self) -> tuple[str, ...]:
        return self.opening_steps

    def matches(self, chars: list["BaseChar"]) -> bool:
        actual = tuple(getattr(char, "builtin_key", None) for char in chars)
        return self.matches_signature(actual)

    def matches_signature(self, signature) -> bool:
        if not self.enabled or not self.team_signature:
            return False
        return tuple(signature) == self.team_signature

    def create(self, task) -> "CustomTeamAxis":
        return CustomTeamAxis(task, self)


class CustomTeamAxis(BaseTeamAxis):
    """User-authored fixed-team axis compiled from prefixed combo commands."""

    SLOT_PREFIXES = ("p1", "p2", "p3", "p4")

    def __init__(self, task, definition: CustomTeamAxisDefinition):
        self.definition = definition
        self.name = definition.name
        self.axis_id = definition.axis_id
        self.description = definition.description
        self.team_signature = definition.team_signature
        self.team_labels = definition.team_labels
        super().__init__(task)
        self.content = definition.content
        self.parsed_combo, error = self.compile_axis_text(self.content)
        if error:
            raise TeamAxisError(f"固定轴语法错误：{error}")

    @classmethod
    def get_command_definitions(cls) -> list[Cmd]:
        commands: list[Cmd] = []
        for slot_index, prefix in enumerate(cls.SLOT_PREFIXES):
            for command in CustomChar.get_command_definitions():
                if command.name == "if_":
                    continue
                command_name = f"{prefix}_{command.name}"
                commands.append(
                    Cmd(
                        command_name,
                        _slot_command(slot_index, command.name),
                        command.params,
                        f"{slot_index + 1}号位：{command.doc}",
                        _prefixed_example(command.example, command.name, command_name),
                        command.if_capable,
                    )
                )

        commands.append(
            Cmd(
                "if_",
                TeamAxisComboCompiler._execute_if_command,
                "条件命令、一个或多个目标命令",
                "条件执行：条件和目标命令均使用 p1_/p2_/p3_/p4_ 前缀",
                "if_(p1_ultimate, p1_skill), if_(p2_skill(0.5), p3_l_click(2))",
            )
        )
        return commands

    @classmethod
    def compile_axis_text(cls, content: str):
        return TeamAxisComboCompiler.compile_combo_text(content)

    @classmethod
    def validate_axis_syntax(cls, content: str):
        _, error = cls.compile_axis_text(content)
        return error is None, error

    @staticmethod
    def build_definition(axis_config: dict) -> CustomTeamAxisDefinition:
        return CustomTeamAxisDefinition(
            axis_id=str(axis_config.get("axis_id", "") or ""),
            name=str(axis_config.get("name", "") or "自定义固定轴"),
            description=str(axis_config.get("description", "") or ""),
            content=str(axis_config.get("content", "") or ""),
            team_signature=tuple(axis_config.get("team_signature", [])),
            enabled=bool(axis_config.get("enabled", True)),
        )

    def run_opening(self):
        self._execute_axis_content()

    def run_cycle(self):
        self._execute_axis_content()

    def _execute_axis_content(self):
        if not self.parsed_combo:
            raise TeamAxisError("固定轴内容为空")
        for command in self.parsed_combo:
            self._execute_compiled_command(command)
            self.task.check_combat()

    def _execute_compiled_command(self, command):
        func_name, target, args, kwargs, _ = command
        if callable(target):
            self.task.log_debug(f"Executing Team Axis Command: {func_name}")
            return target(self, *args, **kwargs)
        raise TeamAxisError(f"未知固定轴命令：{func_name}")

    def execute_slot_command(self, slot_index: int, command_name: str, *args, **kwargs):
        char = self.switch_to_position(slot_index)
        return self._execute_char_command(char, command_name, *args, **kwargs)

    def switch_to_position(self, slot_index: int, wait_intro=True):
        if slot_index < 0 or slot_index >= len(self.task.chars):
            raise TeamAxisError(f"固定轴找不到 {slot_index + 1} 号位角色")
        target = self.task.chars[slot_index]
        if target is None:
            raise TeamAxisError(f"固定轴 {slot_index + 1} 号位角色为空")
        return self.switch_to_char(target, wait_intro=wait_intro)

    def _execute_char_command(self, char, command_name: str, *args, **kwargs):
        if command_name == "skill":
            down_time = args[0] if args else kwargs.get("down_time", 0.01)
            return char.click_skill(down_time=down_time)
        if command_name == "ultimate":
            return char.click_ultimate()
        if command_name == "arc":
            return char.click_arc()
        if command_name == "l_click":
            duration = args[0] if args else None
            if duration is None:
                return char.normal_attack()
            return char.continues_normal_attack(duration)
        if command_name == "r_click":
            duration = args[0] if args else None
            if duration is None:
                return char.click(key="right")
            return char.continues_right_click(duration)
        if command_name == "l_hold":
            duration = args[0] if args else 0.6
            return char.heavy_attack(duration)
        if command_name == "r_hold":
            duration = args[0] if args else 0.01
            return char.click(key="right", down_time=duration)
        if command_name == "wait":
            return char.sleep(args[0])
        if command_name == "jump":
            return char.send_key("space")
        if command_name == "walk":
            return char.send_key(args[0], down_time=args[1])
        if command_name == "mousedown":
            key = args[0] if args else "left"
            return self.task.mouse_down(key=key)
        if command_name == "mouseup":
            key = args[0] if args else "left"
            return self.task.mouse_up(key=key)
        if command_name == "click":
            key = args[0] if args else "left"
            return self.task.click(key=key)
        if command_name == "keydown":
            return self.task.send_key_down(args[0])
        if command_name == "keyup":
            return self.task.send_key_up(args[0])
        if command_name == "keypress":
            return self.task.send_key(key=args[0])
        raise TeamAxisError(f"未知固定轴命令：{command_name}")
