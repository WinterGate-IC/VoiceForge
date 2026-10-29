# Test fixtures

The `.license` files here are **already expired** signed tokens used by the test
suite. They grant nothing in practice:

- `expired.license` - unbound, expires `2020-01-01`
- `expired-bound.license` - bound to the fake id `test-machine-0001`
- `other-product.license` - signed for the other product, so it must be rejected

The tests pass an earlier ``today`` to exercise the valid-signature path, and
the real current date to exercise expiry. Do not replace these with live
licences.
