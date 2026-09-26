from .base import Agent, NullAgent
from .replay import ReplayAgent

AGENTS = {"null": NullAgent, "replay": ReplayAgent}


def make_agent(name, **kw):
    if name == "anthropic":
        from .anthropic_agent import AnthropicAgent
        return AnthropicAgent(**kw)
    if name not in AGENTS:
        raise SystemExit(f"unknown agent '{name}'. Choose from {sorted(AGENTS) + ['anthropic']}")
    return AGENTS[name]()
