import time
from collections.abc import Iterable

from src.combat.planner.context import CombatContext
from src.combat.planner.types import FollowupStep, Planner, SwitchInGuard


def _exact_team(chars, required_types) -> bool:
    chars = list(chars)
    return len(chars) == len(required_types) and all(
        sum(isinstance(char, char_type) for char in chars) == 1 for char_type in required_types
    )


def is_baicang_abyss_team(chars: Iterable) -> bool:
    from src.char.Baicang import Baicang
    from src.char.Daphneel import Daphneel
    from src.char.Hania import Hania
    from src.char.Sakiri import Sakiri

    return _exact_team(chars, (Baicang, Daphneel, Hania, Sakiri))


def is_chiz_abyss_team(chars: Iterable) -> bool:
    from src.char.Chiz import Chiz
    from src.char.Iloy import Iloy
    from src.char.Yi import Yi
    from src.char.Zero import Zero

    return _exact_team(chars, (Chiz, Iloy, Yi, Zero))


def is_abyss_team(chars: Iterable) -> bool:
    """Return whether ``chars`` is one of the two combat-controlled Abyss rosters."""

    return is_baicang_abyss_team(chars) or is_chiz_abyss_team(chars)


def abyss_main_dps(chars: Iterable):
    """Return the protected main DPS for a verified Abyss roster."""

    chars = list(chars)
    if is_baicang_abyss_team(chars):
        from src.char.Baicang import Baicang

        return next(char for char in chars if isinstance(char, Baicang))
    if is_chiz_abyss_team(chars):
        from src.char.Chiz import Chiz

        return next(char for char in chars if isinstance(char, Chiz))
    return None


def is_abyss_setup_only_char(char, chars: Iterable) -> bool:
    """Whether a character must never occupy field time without a route action."""

    main_dps = abyss_main_dps(chars)
    return main_dps is not None and char is not main_dps


def abyss_main_dps_switch_guard(
    context: CombatContext,
    *,
    from_char,
    target_char,
    has_intro: bool,
) -> SwitchInGuard:
    """Protect a short main-DPS window outside strict routes and intro reactions."""
    if has_intro or from_char is target_char or context.has_strict_route():
        return SwitchInGuard.allow()

    minimum = 0.0
    label = ""
    if is_baicang_abyss_team(context.chars):
        from src.char.Baicang import Baicang

        if isinstance(from_char, Baicang):
            minimum = from_char.MIN_FIELD_TIME
            label = "Baicang"
    elif is_chiz_abyss_team(context.chars):
        from src.char.Chiz import Chiz

        if isinstance(from_char, Chiz):
            minimum = from_char.MIN_FIELD_TIME
            label = "Chiz"

    # Use actual_switch_in_time (only updated on switch_in) instead of
    # last_perform (reset every perform). Same rationale as
    # CombatPlanner._abyss_main_window_ready: a short-fallback main DPS would
    # otherwise reset the guard window every round and block support entry.
    switch_in_time = getattr(from_char, "actual_switch_in_time", -1.0)
    if switch_in_time <= 0:
        switch_in_time = from_char.last_perform
    if minimum <= 0 or switch_in_time <= 0:
        return SwitchInGuard.allow()

    return SwitchInGuard.delay_until_ready(
        lambda: (
            not from_char.is_current_char
            or from_char.is_dead
            or from_char.time_elapsed_accounting_for_freeze(switch_in_time) >= minimum
        ),
        timeout=minimum + 0.5,
        reason=f"protect {label} main-DPS field time",
        poll_interval=0.1,
    )


def abyss_setup_exit_target(current_char, chars: Iterable):
    """Return the Abyss main DPS when a setup member has no planned successor.

    This applies only to the two verified Abyss rosters. Other teams keep the
    framework's normal-attack fallback unchanged.
    """
    chars = list(chars)
    if is_baicang_abyss_team(chars):
        from src.char.Baicang import Baicang

        main_dps = next(char for char in chars if isinstance(char, Baicang))
        return main_dps if current_char is not main_dps else None
    if is_chiz_abyss_team(chars):
        from src.char.Chiz import Chiz

        main_dps = next(char for char in chars if isinstance(char, Chiz))
        return main_dps if current_char is not main_dps else None
    return None


def should_use_default_arc(char, chars: Iterable) -> bool:
    chars = list(chars)
    if is_baicang_abyss_team(chars):
        from src.char.Baicang import Baicang
        from src.char.Daphneel import Daphneel

        return isinstance(char, (Baicang, Daphneel))
    if is_chiz_abyss_team(chars):
        return False
    return True


def is_999night_team(chars: Iterable) -> bool:
    """Detect the 999-night idle team: Iloy + Mint + Zero + Shinku."""
    from src.char.Iloy import Iloy
    from src.char.Mint import Mint
    from src.char.Shinku import Shinku
    from src.char.Zero import Zero

    return _exact_team(chars, (Iloy, Mint, Shinku, Zero))


def team_strategy_source(chars):
    chars = list(chars)
    if is_baicang_abyss_team(chars):
        from src.char.Baicang import Baicang

        return next(char for char in chars if isinstance(char, Baicang))
    if is_chiz_abyss_team(chars):
        from src.char.Chiz import Chiz

        return next(char for char in chars if isinstance(char, Chiz))
    if is_999night_team(chars):
        from src.char.Shinku import Shinku

        return next(char for char in chars if isinstance(char, Shinku))
    return None


def publish_team_strategy(context: CombatContext) -> None:
    if is_baicang_abyss_team(context.chars):
        request_baicang_opener(context)
    elif is_chiz_abyss_team(context.chars):
        request_chiz_route(context, opener=True)
    elif is_999night_team(context.chars):
        request_999night_opener(context)


def _timeout_after(seconds):
    started_at = time.monotonic()

    def expired():
        duration = seconds() if callable(seconds) else seconds
        return time.monotonic() - started_at >= duration

    return expired


def request_baicang_opener(context: CombatContext) -> None:
    if not is_baicang_abyss_team(context.chars):
        return

    from src.char.Baicang import Baicang
    from src.char.Daphneel import Daphneel
    from src.char.Hania import Hania
    from src.char.Sakiri import Sakiri

    sakiri = next(char for char in context.chars if isinstance(char, Sakiri))
    hania = next(char for char in context.chars if isinstance(char, Hania))
    daphneel = next(char for char in context.chars if isinstance(char, Daphneel))
    baicang = next(char for char in context.chars if isinstance(char, Baicang))

    context.request_route(
        [
            FollowupStep.for_action(
                sakiri,
                Planner.ActionSlot.SKILL,
                reason="Sakiri holds skill to group enemies",
                optional=True,
            ),
            FollowupStep.for_action(
                sakiri,
                Planner.ActionSlot.ULTIMATE,
                reason="Sakiri suppresses grouped enemies and buffs team ATK",
                optional=True,
            ),
            FollowupStep.for_action(
                hania,
                Planner.ActionSlot.ULTIMATE,
                reason="Hania opens the damage window",
                optional=True,
            ),
            FollowupStep.for_action(
                hania,
                Planner.ActionSlot.SKILL,
                reason="Hania deploys off-field damage",
                optional=True,
            ),
            FollowupStep.for_action(
                daphneel,
                Planner.ActionSlot.SKILL,
                reason="Daphneel primes dark damage",
                optional=True,
            ),
            FollowupStep.for_action(
                daphneel,
                Planner.ActionSlot.ULTIMATE,
                reason="Daphneel spends the burst before Baicang",
                optional=True,
            ),
        ],
        reason="Baicang abyss opener",
        until=_timeout_after(lambda: baicang.ABYSS_OPENER_TIMEOUT),
        return_to_source=False,
    )


def request_chiz_route(context: CombatContext, opener: bool) -> None:
    if not is_chiz_abyss_team(context.chars):
        return

    from src.char.Chiz import Chiz
    from src.char.Iloy import Iloy
    from src.char.Yi import Yi
    from src.char.Zero import Zero

    chiz = next(char for char in context.chars if isinstance(char, Chiz))
    iloy = next(char for char in context.chars if isinstance(char, Iloy))
    yi = next(char for char in context.chars if isinstance(char, Yi))
    zero = next(char for char in context.chars if isinstance(char, Zero))

    if opener:
        steps = [
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.SKILL,
                reason="Iloy gathers enemies and heals team",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.ULTIMATE,
                reason="Zero adds light setup",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.SKILL,
                reason="Zero primes the first element ring",
            ),
        ]
    else:
        steps = [
            FollowupStep.for_entry_reaction(
                iloy,
                reason="Iloy enters after Chiz field time",
            ),
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.SKILL,
                reason="Iloy gathers enemies and heals",
                optional=True,
            ),
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.ULTIMATE,
                reason="Iloy dream state for damage",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.ULTIMATE,
                reason="Zero refreshes light setup",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.SKILL,
                reason="Zero primes the aspect reaction",
            ),
            FollowupStep.for_entry_reaction(
                yi,
                reason="Yi triggers Delay",
            ),
            FollowupStep.for_action(
                yi,
                Planner.ActionSlot.ULTIMATE,
                reason="Yi applies ultimate setup",
                optional=True,
            ),
            FollowupStep.for_action(
                yi,
                Planner.ActionSlot.SKILL,
                reason="Yi applies aspect setup",
            ),
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.SKILL,
                reason="Iloy regroups before Chiz returns",
                optional=True,
            ),
        ]
    route_name = "opener" if opener else "cycle"
    context.request_route(
        steps,
        reason=f"Chiz Yingxu abyss {route_name}",
        until=_timeout_after(lambda: chiz.ABYSS_ROUTE_TIMEOUT),
        return_to_source=True,
    )


def request_999night_opener(context: CombatContext) -> None:
    """999-night idle team opener route.

    Design principle: stable > speed. The opener ensures a consistent rotation
    order so the team does not deadlock during long idle sessions.

    Rotation:
      1. Iloy E (gather + heal + ATK buff) -> optional
      2. Iloy Q (dream state) -> optional
      3. Mint Q (enhanced domain) -> optional
      4. Mint E (deploy off-field) -> optional
      5. Zero Q (light setup) -> optional
      6. Zero E (prime element ring) -> optional
      7. Shinku E -> optional
      8. Shinku Q (burst window) -> optional

    After the opener, each character's entry calls request_switch to the next
    in the chain: Iloy -> Mint -> Zero -> Shinku -> Iloy, so the cycle repeats.
    """
    if not is_999night_team(context.chars):
        return

    from src.char.Iloy import Iloy
    from src.char.Mint import Mint
    from src.char.Shinku import Shinku
    from src.char.Zero import Zero

    iloy = next(char for char in context.chars if isinstance(char, Iloy))
    mint = next(char for char in context.chars if isinstance(char, Mint))
    zero = next(char for char in context.chars if isinstance(char, Zero))
    shinku = next(char for char in context.chars if isinstance(char, Shinku))

    context.request_route(
        [
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.SKILL,
                reason="Iloy gathers enemies and heals team",
                optional=True,
            ),
            FollowupStep.for_action(
                iloy,
                Planner.ActionSlot.ULTIMATE,
                reason="Iloy enters dream state for heavy attack",
                optional=True,
            ),
            FollowupStep.for_action(
                mint,
                Planner.ActionSlot.ULTIMATE,
                reason="Mint enhances domain",
                optional=True,
            ),
            FollowupStep.for_action(
                mint,
                Planner.ActionSlot.SKILL,
                reason="Mint deploys off-field damage",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.ULTIMATE,
                reason="Zero adds light setup",
                optional=True,
            ),
            FollowupStep.for_action(
                zero,
                Planner.ActionSlot.SKILL,
                reason="Zero primes element ring",
                optional=True,
            ),
            FollowupStep.for_action(
                shinku,
                Planner.ActionSlot.SKILL,
                reason="Shinku primes burst",
                optional=True,
            ),
            FollowupStep.for_action(
                shinku,
                Planner.ActionSlot.ULTIMATE,
                reason="Shinku burst window",
                optional=True,
            ),
        ],
        reason="999-night idle opener",
        until=_timeout_after(lambda: iloy.ABYSS_OPENER_TIMEOUT),
        return_to_source=False,
    )
