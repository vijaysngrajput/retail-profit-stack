"""The PySpark engine: a reserved slot. Suited to large data across many machines.

Implements LLD section 6 (Engines). It is not built in this milestone. The class exists so
the place for it in the design is concrete: to build it, fill in the three methods below, add
implementations/spark/<name>.py for each transformation, and pass the same conformance tests
the other engines pass. Nothing else in the project needs to change.
"""

import pyarrow as pa

from retail_profit_stack.transform.contracts import TransformationSpec
from retail_profit_stack.transform.engines.base import Engine, Implementation

NOT_BUILT = (
    "The PySpark engine is not built yet. It is a reserved slot in the design. To build it: "
    "install Java and pyspark, implement register (create a Spark DataFrame from the Arrow "
    "table), load_implementation (import implementations/spark/<name>.py), and execute (call "
    "the function and return the result as an Arrow table), then run the conformance tests."
)


class SparkEngine(Engine):
    name = "spark"

    def register(self, name: str, table: pa.Table) -> None:
        raise NotImplementedError(NOT_BUILT)

    def load_implementation(self, spec: TransformationSpec) -> Implementation:
        raise NotImplementedError(NOT_BUILT)

    def execute(self, implementation: Implementation, spec: TransformationSpec) -> pa.Table:
        raise NotImplementedError(NOT_BUILT)
