from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Generic, TypeVar

from langchain_core.runnables import RunnableConfig

_State = TypeVar("_State")
_Update = TypeVar("_Update")
START: str
END: str

class CompiledGraph(Generic[_State, _Update]):
    async def ainvoke(self, value: _State, /, config: RunnableConfig | None = None) -> _State: ...
    def astream(
        self,
        value: _State,
        /,
        config: RunnableConfig | None = None,
        *,
        stream_mode: str = "updates",
    ) -> AsyncIterator[dict[str, _Update]]: ...

class StateGraph(Generic[_State, _Update]):
    def __init__(self, state_schema: type[_State]) -> None: ...
    def add_node(
        self, node: str, action: Callable[[_State], Awaitable[_Update]]
    ) -> StateGraph[_State, _Update]: ...
    def add_edge(self, start_key: str, end_key: str) -> StateGraph[_State, _Update]: ...
    def add_conditional_edges(
        self, source: str, path: Callable[[_State], str], path_map: dict[str, str]
    ) -> StateGraph[_State, _Update]: ...
    def compile(self) -> CompiledGraph[_State, _Update]: ...
