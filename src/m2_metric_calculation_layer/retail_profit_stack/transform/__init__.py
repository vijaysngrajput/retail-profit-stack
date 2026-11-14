"""The transformation layer: rules as contracts, engines as adapters.

A transformation is described once, with no engine in it (contracts.py, specs.py). Each engine
(engines/) runs its own implementation of that description (implementations/) and returns the
result in one standard format. The design is in docs/HLD.md section 6 and docs/LLD.md
sections 3 to 6.
"""
