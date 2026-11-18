from .database import DATABASE, Database, Message, Signal
from .virtual_bus import CanFrame, VirtualBus


def create_bus(backend: str = "memory", clock=None) -> VirtualBus:
    """backend : "memory" (par défaut) ou "python-can"."""
    if backend == "memory":
        return VirtualBus(clock=clock)
    if backend == "python-can":
        from .python_can_bus import PythonCanBus

        return PythonCanBus(clock=clock)
    raise ValueError(f"Backend de bus inconnu : {backend}")


__all__ = ["DATABASE", "Database", "Message", "Signal", "CanFrame", "VirtualBus", "create_bus"]
