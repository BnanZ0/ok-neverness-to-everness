class ChainLoader:
# 角色名称映射：支持中文名、英文名、链式类名，统一解析为内部 role_id
    CHAR_NAME_MAP = {
        "浔": "hotori", "Hotori": "hotori", "HotoriChain": "hotori",
        "零": "zero", "Zero": "zero", "ZeroChain": "zero",
        "九原": "jiuyuan", "Jiuyuan": "jiuyuan", "JiuyuanChain": "jiuyuan",
        "娜娜莉": "nanally", "Nanally": "nanally", "NanallyChain": "nanally",
    }

    @staticmethod
    def replace_chars_with_strategy(task, strategy_name):
        if strategy_name == "HOTORI_CREATION_CHAIN":
            from src.char.HotoriChain import HotoriChain
            from src.char.ZeroChain import ZeroChain
            from src.char.JiuyuanChain import JiuyuanChain
            from src.char.NanallyChain import NanallyChain

            chain_map = {
                "hotori": {"cls": HotoriChain, "key": "char_chain_hotori"},
                "zero": {"cls": ZeroChain, "key": "char_chain_zero"},
                "jiuyuan": {"cls": JiuyuanChain, "key": "char_chain_jiuyuan"},
                "nanally": {"cls": NanallyChain, "key": "char_chain_nanally"}
            }

            team_instances = {}

            for i, c in enumerate(task.chars):
                role_id = ChainLoader._resolve_role(c)
                if role_id in chain_map:
                    mapping = chain_map[role_id]
                    target_cls = mapping["cls"]

                    if c.__class__.__name__ != target_cls.__name__:
                        new_char = target_cls(task, c.index, char_name=c.char_name, confidence=c.confidence)
                        new_char.element = c.element
                        new_char.builtin_key = mapping["key"]
                        task.chars[i] = new_char
                        team_instances[role_id] = new_char
                    else:
                        team_instances[role_id] = c

            hotori = team_instances.get("hotori")
            zero = team_instances.get("zero")
            jiuyuan = team_instances.get("jiuyuan")
            nanally = team_instances.get("nanally")

            if not all([hotori, zero, jiuyuan, nanally]):
                task.log_error("队伍缺少浔/零/九原/娜娜莉其中之一，无法使用浔创生链式轴！")
                return None

            return (hotori, zero, jiuyuan, nanally)
        return None

    @staticmethod
    def _resolve_role(c):
        """通过 char_name 或类名查 CHAR_NAME_MAP，返回内部 role_id"""
        cn = getattr(c, "char_name", "")
        if cn in ChainLoader.CHAR_NAME_MAP:
            return ChainLoader.CHAR_NAME_MAP[cn]
        cls_name = c.__class__.__name__
        return ChainLoader.CHAR_NAME_MAP.get(cls_name, "")

    @staticmethod
    def load_strategy(task, strategy_name: str):
        result = ChainLoader.replace_chars_with_strategy(task, strategy_name)
        if result is None:
            return None
        hotori, _, _, _ = result
        def builder():
            return hotori._build_next_chain()
        return builder
