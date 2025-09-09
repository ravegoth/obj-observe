Changelog

## v0.1.3

- Observer storage rewrite with weak+fallback strategy:
  - Weak-key storage for slotted instances supporting weakrefs; id(obj) fallback otherwise.
  - Added per-class RLock and idempotent `__setattr__` patching for thread safety.
  - Use `weakref.WeakMethod` for bound method callbacks to avoid keeping instances alive.
  - Finalizers clean up weak storage and decrement class refcount safely.
  - `remove_observers` and `remove_observer` now return `bool` to signal changes.
  - Added `clear_all(obj)` convenience helper.
  - Improved internal typing for storage buckets and observer refs.

- Tests: added coverage for slotted classes (with/without `__weakref__`), WeakMethod behavior, and basic concurrency.


## v0.1.4

- Broaden Python support to 3.8+ (was 3.9+).
- Add Python 3.8 classifier in packaging metadata.
