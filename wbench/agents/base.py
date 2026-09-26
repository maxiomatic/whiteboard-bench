"""Agent interface.

An agent receives a briefing once per task, then one message per turn.
During a turn it calls env.call(tool_name, args) as often as it likes (within
budget) and should end with env.call("finish_turn", {...}).

    class MyAgent(Agent):
        def start(self, briefing): ...
        def run_turn(self, message, env): ...

`env.call` returns a dict with "ok" plus tool results. It may also carry
"board_activity": a list of things humans just did while the agent was working.
"""


class Agent:
    name = "base"

    def start(self, briefing):
        self.briefing = briefing

    def run_turn(self, message, env):
        raise NotImplementedError


class NullAgent(Agent):
    """Does nothing. Establishes the floor for every task."""
    name = "null"

    def run_turn(self, message, env):
        env.call("finish_turn", {"summary": "No changes."})
