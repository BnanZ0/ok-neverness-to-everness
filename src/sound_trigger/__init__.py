# Lazy re-exports: importing a submodule (e.g. the fingerprint package) must not
# eagerly pull in the legacy SoundListener and its heavy deps (librosa, soundcard).
__all__ = ["SoundListener", "DodgeCounterTrigger", "SoundCombatContext", "FingerprintSoundListener"]


def __getattr__(name):
    if name == "SoundListener":
        from .SoundListener import SoundListener

        return SoundListener
    if name == "DodgeCounterTrigger":
        from .DodgeCounterTrigger import DodgeCounterTrigger

        return DodgeCounterTrigger
    if name == "SoundCombatContext":
        from .SoundCombatContext import SoundCombatContext

        return SoundCombatContext
    if name == "FingerprintSoundListener":
        from .FingerprintSoundListener import FingerprintSoundListener

        return FingerprintSoundListener
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
