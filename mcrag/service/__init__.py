"""Phase 5: the product backend. `answer(question, history) -> Iterator[Event]`
(Task 24) lives here, importable with no web framework anywhere in the chain --
that is what keeps the API a thin shell over it (Task 25) and the UI genuinely
optional. `events.py` (Task 23) is this package's public contract, defined and
frozen before the callable that emits it."""
