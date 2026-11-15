"""The interface every engine implements.

Implements LLD section 6 (Engines). The pipeline and the tests talk only to this interface,
so they work the same whichever engine is behind it. Adding an engine means writing one class
like the ones beside this file, plus an implementation of each transformation.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from retail_profit_stack.transform.contracts import TransformationSpec, conform

IMPLEMENTATIONS_DIR = Path(__file__).resolve().parent.parent / "implementations"


@dataclass(frozen=True)
class Implementation:
    """One transformation's code for one engine: a SQL query, or a function."""

    engine: str
    name: str
    code: str = ""
    function: Callable | None = None


class Engine(ABC):
    """Runs implementations and returns results in the standard table format."""

    name: str

    @abstractmethod
    def register(self, name: str, table: pa.Table) -> None:
        """Make a table available to implementations under this name."""

    @abstractmethod
    def load_implementation(self, spec: TransformationSpec) -> Implementation:
        """Find this engine's implementation of a transformation."""

    @abstractmethod
    def execute(self, implementation: Implementation, spec: TransformationSpec) -> pa.Table:
        """Run the implementation and return its result as an Arrow table."""

    def run(
        self, spec: TransformationSpec, implementation: Implementation | None = None
    ) -> pa.Table:
        """Run a transformation and return its output in the standard form.

        Uses this engine's own implementation unless another one is passed in.
        """
        implementation = implementation or self.load_implementation(spec)
        return conform(self.execute(implementation, spec), spec.output)
