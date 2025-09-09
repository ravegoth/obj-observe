"""Core observable primitives for obj-observe.

Public API:
    - ObservableDict: dict subclass that notifies observers on key changes.
    - observe(obj, attr, callback=None): register an observer on attr/key.
    - remove_observers(obj, attr=None): detach observers.

Implementation notes:
    * Attribute observation works by monkey-patching the owning class's __setattr__
      exactly once and keeping a per-class reference count so removing observers
      from one instance does not break remaining observers on other instances.
    * ObservableDict handles its own recursion guard per key.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, Iterable, Optional, Union, overload, TypedDict, cast
import threading
import weakref

Observer = Callable[[Any, Any], None]
ObserverRef = Union[Observer, weakref.WeakMethod]


class _StorageBucket(TypedDict, total=False):
    __observers__: Dict[str, list[ObserverRef]]
    __is_observing__: Dict[str, bool]
    finalizer: weakref.finalize


def _weak_or_id_key(obj: Any) -> tuple[Dict[Any, _StorageBucket], Any, bool]:
    """Return (map, key, is_weak) for slotted instances without __dict__.

    Uses WeakKeyDictionary when the instance supports weakrefs; otherwise a
    normal dict keyed by id(obj) with no GC-based auto-clean.
    """
    # Ensure class containers exist
    storage_map: Optional[Dict[Any, _StorageBucket]] = getattr(
        obj.__class__, '__allow_observe_storage__', None
    )
    storage_map_id: Optional[Dict[Any, _StorageBucket]] = getattr(
        obj.__class__, '__allow_observe_storage_by_id__', None
    )

    # Try weakref first
    supports_weak = True
    try:
        weakref.ref(obj)
    except TypeError:
        supports_weak = False

    if supports_weak:
        if storage_map is None:
            storage_map = weakref.WeakKeyDictionary()  # type: ignore[assignment]
            setattr(obj.__class__, '__allow_observe_storage__', storage_map)
        storage_map_typed: Dict[Any, _StorageBucket] = cast(Dict[Any, _StorageBucket], storage_map)
        return storage_map_typed, obj, True

    # Fallback to id(obj) keyed storage
    if storage_map_id is None:
        storage_map_id = {}
        setattr(obj.__class__, '__allow_observe_storage_by_id__', storage_map_id)
    storage_map_id_typed: Dict[Any, _StorageBucket] = cast(Dict[Any, _StorageBucket], storage_map_id)
    return storage_map_id_typed, id(obj), False


def _normalize_callback(callback: Observer) -> ObserverRef:
    """Store bound methods as WeakMethod to avoid keeping instances alive."""
    self_obj = getattr(callback, '__self__', None)
    func = getattr(callback, '__func__', None)
    if self_obj is not None and func is not None:
        try:
            return weakref.WeakMethod(callback)  # type: ignore[arg-type]
        except TypeError:
            # Fallback if object cannot be weak-referenced
            return callback
    return callback


class ObservableDict(dict):
    """Dictionary that notifies registered observers when a key's value changes.

    Observers receive two arguments: (old_value, new_value).
    """

    # Type hints for private attributes (pre-declared so linters know they exist)
    __observers: Dict[Any, list[ObserverRef]]  # key -> list of callbacks (may be WeakMethod)
    __is_observing: Dict[Any, bool]         # recursion guard per key currently being set

    def __init__(self, *args: Iterable[Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Normal attribute assignment is fine (no custom __setattr__).
        self.__observers = {}
        self.__is_observing = {}

    def __setitem__(self, key: Any, value: Any) -> None:  # type: ignore[override]
        if key not in self.__is_observing:
            self.__is_observing[key] = False

        if self.__is_observing.get(key):
            super().__setitem__(key, value)
            return

        self.__is_observing[key] = True
        old_value = self.get(key)
        super().__setitem__(key, value)

        if key in self.__observers:
            for observer in list(self.__observers[key]):  # copy to allow mutation during iteration
                # Resolve WeakMethod if present
                if isinstance(observer, weakref.WeakMethod):
                    target = observer()
                    if target is None:
                        continue
                    target(old_value, value)
                else:
                    observer(old_value, value)
        self.__is_observing[key] = False

    # --- Internal observer management helpers (avoid external access to private attrs) ---
    def _add_observer(self, key: Any, callback: Observer) -> None:
        self.__observers.setdefault(key, []).append(_normalize_callback(callback))

    def _remove_observers(self, key: Optional[Any] = None) -> None:
        if key is None:
            self.__observers.clear()
        else:
            self.__observers.pop(key, None)


@overload
def observe(obj: dict, attr: str, callback: Observer) -> ObservableDict: ...  # noqa: D401

@overload
def observe(obj: object, attr: str, callback: Observer) -> object: ...

@overload
def observe(obj: dict, attr: str) -> Callable[[Observer], Observer]: ...

@overload
def observe(obj: object, attr: str) -> Callable[[Observer], Observer]: ...

def observe(obj: Any, attr: str, callback: Optional[Observer] = None):
    """Register an observer for an attribute (objects) or key (dicts).

    Usage:
        @observe(instance, 'field')
        def on_change(old, new): ...

        # Or
        observe(instance, 'field', on_change)

    When observing a plain dict, it is wrapped into an ObservableDict which is returned.
    """
    if isinstance(obj, dict) and not isinstance(obj, ObservableDict):
        obj = ObservableDict(obj)

    def decorator(func: Observer):
        add_observer(obj, attr, func)
        return func

    if callback:
        add_observer(obj, attr, callback)
        return obj
    return decorator


def add_observer(obj: Any, attr: str, callback: Observer) -> None:
    """Internal helper to append an observer callback."""
    if isinstance(obj, ObservableDict):
        obj._add_observer(attr, callback)
        return

    # Per-instance storage
    first_time_for_instance = False
    if not hasattr(obj, '__observers__'):
        first_time_for_instance = True
        # Slotted classes without __dict__ cannot accept new attributes; use fallback containers on class
        if hasattr(obj, '__dict__'):
            obj.__observers__ = {}  # type: ignore[attr-defined]
            obj.__is_observing__ = {}  # type: ignore[attr-defined]
        else:
            storage_map, key, is_weak = _weak_or_id_key(obj)
            storage_map[key] = {'__observers__': {}, '__is_observing__': {}}
            cls = obj.__class__

            def _finalizer(cls: type = cls) -> None:
                if hasattr(cls, '__observe_refcount__'):
                    cls.__observe_refcount__ -= 1  # type: ignore[attr-defined]
                    if cls.__observe_refcount__ <= 0 and hasattr(cls, '__original_setattr__'):
                        cls.__setattr__ = cls.__original_setattr__  # type: ignore[attr-defined, method-assign]
                        del cls.__original_setattr__  # type: ignore[attr-defined]
                        del cls.__observe_refcount__  # type: ignore[attr-defined]

            if is_weak:
                storage_map[key]['finalizer'] = weakref.finalize(obj, _finalizer)

    # Resolve storage (normal attribute vs slotted fallback)
    if not hasattr(obj, '__dict__'):
        # Resolve storage via weak or id map
        storage: Optional[_StorageBucket] = None
        storage_map_w = getattr(obj.__class__, '__allow_observe_storage__', None)
        if storage_map_w is not None and obj in storage_map_w:
            storage = storage_map_w[obj]
        else:
            storage_map_id = getattr(obj.__class__, '__allow_observe_storage_by_id__', None)
            if storage_map_id is not None:
                storage = storage_map_id.get(id(obj))
        if storage is None:
            # Ensure bucket exists if somehow missing
            smap, skey, _ = _weak_or_id_key(obj)
            storage = smap.setdefault(skey, {'__observers__': {}, '__is_observing__': {}})
        if attr not in storage['__observers__']:
            storage['__observers__'][attr] = []
        storage['__observers__'][attr].append(_normalize_callback(callback))
    else:
        if attr not in obj.__observers__:  # type: ignore[attr-defined]
            obj.__observers__[attr] = []  # type: ignore[index]
        obj.__observers__[attr].append(_normalize_callback(callback))  # type: ignore[index]

    # Install class-level patch if needed
    cls = obj.__class__
    if not hasattr(cls, '__original_setattr__'):
        cls.__original_setattr__ = cls.__setattr__  # type: ignore[attr-defined, assignment, method-assign]
        cls.__observe_refcount__ = 0  # type: ignore[attr-defined]
        cls.__observe_lock__ = threading.RLock()  # type: ignore[attr-defined]

        def new_setattr(self, name, value):  # type: ignore[no-untyped-def]
            lock = getattr(self.__class__, '__observe_lock__', None)
            if lock is None:
                return self.__class__.__original_setattr__(self, name, value)  # type: ignore[attr-defined]
            with lock:
                if not hasattr(self, '__dict__'):
                    storage_map = getattr(self.__class__, '__allow_observe_storage__', None)
                    storage = storage_map.get(self) if storage_map is not None else None
                    if storage is None:
                        storage_map_id = getattr(self.__class__, '__allow_observe_storage_by_id__', None)
                        if storage_map_id is not None:
                            storage = storage_map_id.get(id(self))
                    if storage is None:
                        self.__class__.__original_setattr__(self, name, value)  # type: ignore[attr-defined]
                        return
                    is_observing = storage['__is_observing__']
                    observers_map = storage['__observers__']
                else:
                    if not hasattr(self, '__is_observing__'):
                        object.__setattr__(self, '__is_observing__', {})
                    is_observing = self.__is_observing__  # type: ignore[attr-defined]
                    observers_map = getattr(self, '__observers__', {})  # type: ignore[attr-defined]

                if is_observing.get(name):  # recursion guard
                    self.__class__.__original_setattr__(self, name, value)  # type: ignore[attr-defined]
                    return

                is_observing[name] = True
                old_value = getattr(self, name, None)
                self.__class__.__original_setattr__(self, name, value)  # type: ignore[attr-defined]

                if name in observers_map:
                    for observer in list(observers_map[name]):
                        if isinstance(observer, weakref.WeakMethod):
                            target = observer()
                            if target is None:
                                continue
                            target(old_value, value)
                        else:
                            observer(old_value, value)
                is_observing[name] = False

        cls.__setattr__ = new_setattr  # type: ignore[assignment, method-assign]

    # Increment refcount only once per observed instance
    if first_time_for_instance:
        cls.__observe_refcount__ += 1  # type: ignore[attr-defined]


def remove_observers(obj: Any, attr: Optional[str] = None) -> bool:
    """Remove observers from an object or ObservableDict.

    If attr is None, all observers for the object are removed.
    For ObservableDict instances, class monkey-patching is not involved.
    """
    removed = False
    if isinstance(obj, ObservableDict):
        mapping = getattr(obj, '_ObservableDict__observers', {})
        if attr is None:
            removed = bool(mapping)
        else:
            removed = attr in mapping
        obj._remove_observers(attr)
        return removed

    if not hasattr(obj, '__observers__'):
        # Possibly slotted fallback storage
        storage_map = getattr(obj.__class__, '__allow_observe_storage__', None)
        storage_map_id = getattr(obj.__class__, '__allow_observe_storage_by_id__', None)
        storage: Optional[_StorageBucket] = None
        key_kind = None
        if storage_map is not None and obj in storage_map:
            storage = storage_map[obj]
            key_kind = 'weak'
        elif storage_map_id is not None and id(obj) in storage_map_id:
            storage = storage_map_id[id(obj)]
            key_kind = 'id'
        if storage is not None:
            if attr:
                removed = attr in storage['__observers__']
                storage['__observers__'].pop(attr, None)
            else:
                removed = bool(storage['__observers__'])
                storage['__observers__'].clear()
            if not storage['__observers__']:
                # Remove storage entry and maybe cleanup class patch
                finalizer = storage.get('finalizer')
                if finalizer:
                    finalizer.detach()
                if key_kind == 'weak':
                    assert storage_map is not None
                    del storage_map[obj]
                elif key_kind == 'id':
                    assert storage_map_id is not None
                    storage_map_id.pop(id(obj), None)
                cls = obj.__class__
                if hasattr(cls, '__observe_refcount__'):
                    cls.__observe_refcount__ -= 1  # type: ignore[attr-defined]
                    if cls.__observe_refcount__ <= 0 and hasattr(cls, '__original_setattr__'):
                        cls.__setattr__ = cls.__original_setattr__  # type: ignore[attr-defined]
                        del cls.__original_setattr__  # type: ignore[attr-defined]
                        del cls.__observe_refcount__  # type: ignore[attr-defined]
            return removed
        return False

    if attr:
        if attr in obj.__observers__:  # type: ignore[attr-defined]
            del obj.__observers__[attr]  # type: ignore[attr-defined]
            removed = True
    else:
        removed = removed or bool(obj.__observers__)  # type: ignore[attr-defined]
        obj.__observers__.clear()  # type: ignore[attr-defined]

    cls = obj.__class__
    # If this instance now has zero observers, potentially decrement refcount
    if (not obj.__observers__) and hasattr(cls, '__observe_refcount__'):  # type: ignore[attr-defined]
        cls.__observe_refcount__ -= 1  # type: ignore[attr-defined]
        if cls.__observe_refcount__ <= 0 and hasattr(cls, '__original_setattr__'):
            # Restore original setattr only when no instances remain observed.
            cls.__setattr__ = cls.__original_setattr__  # type: ignore[attr-defined]
            del cls.__original_setattr__  # type: ignore[attr-defined]
            del cls.__observe_refcount__  # type: ignore[attr-defined]
    return removed


def remove_observer(obj: Any, attr: str, callback: Observer) -> bool:
    """Remove a single observer callback for given attr/key if present.

    Returns True if a callback was removed; False otherwise.
    """
    removed = False
    if isinstance(obj, ObservableDict):
        # Access internal map safely
        # Using getattr with name mangling to satisfy linters
        mapping = getattr(obj, '_ObservableDict__observers', None)
        if mapping and attr in mapping:
            try:
                mapping[attr].remove(callback)
                removed = True
            except ValueError:
                norm = _normalize_callback(callback)
                try:
                    mapping[attr].remove(norm)
                    removed = True
                except ValueError:
                    pass
        return removed

    if not hasattr(obj, '__observers__'):
        storage_map = getattr(obj.__class__, '__allow_observe_storage__', None)
        storage_map_id = getattr(obj.__class__, '__allow_observe_storage_by_id__', None)
        storage: Optional[_StorageBucket] = None
        if storage_map is not None and obj in storage_map:
            storage = storage_map[obj]
        elif storage_map_id is not None and id(obj) in storage_map_id:
            storage = storage_map_id[id(obj)]
        if storage is None:
            return False
        lst = storage['__observers__'].get(attr)
        if not lst:
            return False
        try:
            lst.remove(callback)
            removed = True
        except ValueError:
            norm = _normalize_callback(callback)
            try:
                lst.remove(norm)
                removed = True
            except ValueError:
                return False
        if not lst:
            del storage['__observers__'][attr]
            if not storage['__observers__']:
                remove_observers(obj)
        return removed
    lst = obj.__observers__.get(attr)  # type: ignore[attr-defined]
    if not lst:
        return False
    try:
        lst.remove(callback)
        removed = True
    except ValueError:
        norm = _normalize_callback(callback)
        try:
            lst.remove(norm)
            removed = True
        except ValueError:
            return False
    if not lst:
        del obj.__observers__[attr]  # type: ignore[attr-defined]
        if not obj.__observers__:  # type: ignore[attr-defined]
            remove_observers(obj)
    return removed


def clear_all(obj: Any) -> bool:
    """Remove all observers for an object or ObservableDict.

    Returns True if any were removed.
    """
    return remove_observers(obj, None)


__all__ = [
    'ObservableDict',
    'observe',
    'remove_observers',
    'remove_observer',
    'clear_all',
]
