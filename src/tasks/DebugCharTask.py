
from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.char.CharFactory import char_dict
from src.combat.BaseCombatTask import BaseCombatTask


class DebugCharTask(BaseCombatTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Test Char"
        self.description = "Test Char"
        self.icon = FluentIcon.SYNC
        self.char = None
        self.is_char_loaded = False
        self.char_list = [key for key in char_dict.keys()]
        self.default_config.update({
            "char": self.char_list[0]
        })
        self.config_type.update({
            "char": {
                "type": "drop_down",
                "options": self.char_list,
            },
        })

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("自动银行差事出错", e)
            raise
        
    def do_run(self):
        while True:
            # self.log_info(self.has_team_skill_records())
            self.sleep(0.1)

    def init_char(self):
        self.current_char = self.config["char"]
        char_class = char_dict.get(self.current_char).get("cls")
        self.char = char_class(self, 0, char_name=self.current_char, confidence=1)

    def __getattr__(self, name):
        """
        当调用的属性或方法在当前类中找不到时，会进入这个函数。
        name 是调用的名子（字符串）。
        """
        try:
            if self.char is None or self.current_char != self.config["char"]:
                self.is_char_loaded = False
                self.init_char()
            if hasattr(self.char, name):
                if not self.is_char_loaded:
                    self.is_char_loaded = True
                    self.load_chars()
                return getattr(self.char, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self).__name__}' or its member 'char' has no attribute '{name}'"
            )
        return super().__getattr__(name)

