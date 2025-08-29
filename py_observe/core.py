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
from typing import Any, Callable, Dict, Iterable, Optional, overload

Observer = Callable[[Any, Any], None]


class ObservableDict(dict):
    """Dictionary that notifies registered observers when a key's value changes.

    Observers receive two arguments: (old_value, new_value).
    """

    # Type hints for private attributes (pre-declared so linters know they exist)
    __observers: Dict[Any, list[Observer]]  # key -> list of callbacks
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
                observer(old_value, value)
        self.__is_observing[key] = False

    # --- Internal observer management helpers (avoid external access to private attrs) ---
    def _add_observer(self, key: Any, callback: Observer) -> None:
        self.__observers.setdefault(key, []).append(callback)

    def _remove_observers(self, key: Optional[Any] = None) -> None:
        if key is None:
            self.__observers.clear()
        else:
            self.__observers.pop(key, None)


@overload
def observe(obj: dict, attr: str, callback: Observer) -> ObservableDict: ...  # noqa: D401

@overload
def observe(obj: ObservableDict, attr: str, callback: Observer) -> ObservableDict: ...

@overload
def observe(obj: object, attr: str, callback: Observer) -> object: ...

@overload
def observe(obj: dict, attr: str) -> Callable[[Observer], Observer]: ...

@overload
def observe(obj: ObservableDict, attr: str) -> Callable[[Observer], Observer]: ...

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
        # Slotted classes without __dict__ cannot accept new attributes; use fallback container on class
        if not hasattr(obj, '__dict__') and not hasattr(obj.__class__, '__allow_observe_storage__'):
            obj.__class__.__allow_observe_storage__ = {}  # type: ignore[attr-defined]
        if hasattr(obj, '__dict__'):
            obj.__observers__ = {}  # type: ignore[attr-defined]
            obj.__is_observing__ = {}  # type: ignore[attr-defined]
        else:
            # Store per-instance maps inside class-level dict keyed by id
            storage = obj.__class__.__allow_observe_storage__  # type: ignore[attr-defined]
            storage[id(obj)] = {'__observers__': {}, '__is_observing__': {}}

    # Resolve storage (normal attribute vs slotted fallback)
    if not hasattr(obj, '__dict__'):
        storage = obj.__class__.__allow_observe_storage__[id(obj)]  # type: ignore[attr-defined]
        if attr not in storage['__observers__']:
            storage['__observers__'][attr] = []
        storage['__observers__'][attr].append(callback)
    else:
        if attr not in obj.__observers__:  # type: ignore[attr-defined]
            obj.__observers__[attr] = []  # type: ignore[index]
        obj.__observers__[attr].append(callback)  # type: ignore[index]

    # Install class-level patch if needed
    cls = obj.__class__
    if not hasattr(cls, '__original_setattr__'):
        cls.__original_setattr__ = cls.__setattr__  # type: ignore[attr-defined]
        cls.__observe_refcount__ = 0  # type: ignore[attr-defined]

        def new_setattr(self, name, value):  # type: ignore[no-untyped-def]
            if not hasattr(self, '__dict__'):
                storage = self.__class__.__allow_observe_storage__[id(self)]  # type: ignore[attr-defined]
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
                    observer(old_value, value)
            is_observing[name] = False

        cls.__setattr__ = new_setattr  # type: ignore[assignment]

    # Increment refcount only once per observed instance
    if first_time_for_instance:
        cls.__observe_refcount__ += 1  # type: ignore[attr-defined]


def remove_observers(obj: Any, attr: Optional[str] = None) -> None:
    """Remove observers from an object or ObservableDict.

    If attr is None, all observers for the object are removed.
    For ObservableDict instances, class monkey-patching is not involved.
    """
    if isinstance(obj, ObservableDict):
        obj._remove_observers(attr)
        return

    if not hasattr(obj, '__observers__'):
        # Possibly slotted fallback storage
        if hasattr(obj.__class__, '__allow_observe_storage__') and id(obj) in obj.__class__.__allow_observe_storage__:  # type: ignore[attr-defined]
            storage = obj.__class__.__allow_observe_storage__[id(obj)]  # type: ignore[attr-defined]
            if attr:
                storage['__observers__'].pop(attr, None)
            else:
                storage['__observers__'].clear()
            if not storage['__observers__']:
                # Remove storage entry and maybe cleanup class patch
                del obj.__class__.__allow_observe_storage__[id(obj)]  # type: ignore[attr-defined]
                cls = obj.__class__
                if hasattr(cls, '__observe_refcount__'):
                    cls.__observe_refcount__ -= 1  # type: ignore[attr-defined]
                    if cls.__observe_refcount__ <= 0 and hasattr(cls, '__original_setattr__'):
                        cls.__setattr__ = cls.__original_setattr__  # type: ignore[attr-defined]
                        del cls.__original_setattr__  # type: ignore[attr-defined]
                        del cls.__observe_refcount__  # type: ignore[attr-defined]
            return
        return

    if attr:
        if attr in obj.__observers__:  # type: ignore[attr-defined]
            del obj.__observers__[attr]  # type: ignore[attr-defined]
    else:
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


def remove_observer(obj: Any, attr: str, callback: Observer) -> None:
    """Remove a single observer callback for given attr/key if present."""
    if isinstance(obj, ObservableDict):
        # Access internal map safely
        # Using getattr with name mangling to satisfy linters
        mapping = getattr(obj, '_ObservableDict__observers', None)
        if mapping and attr in mapping:
            try:
                mapping[attr].remove(callback)
            except ValueError:
                pass
        return

    if not hasattr(obj, '__observers__'):
        if hasattr(obj.__class__, '__allow_observe_storage__') and id(obj) in obj.__class__.__allow_observe_storage__:  # type: ignore[attr-defined]
            storage = obj.__class__.__allow_observe_storage__[id(obj)]  # type: ignore[attr-defined]
            lst = storage['__observers__'].get(attr)
            if not lst:
                return
            try:
                lst.remove(callback)
            except ValueError:
                return
            if not lst:
                del storage['__observers__'][attr]
                if not storage['__observers__']:
                    remove_observers(obj)
        return
    lst = obj.__observers__.get(attr)  # type: ignore[attr-defined]
    if not lst:
        return
    try:
        lst.remove(callback)
    except ValueError:
        return
    if not lst:
        del obj.__observers__[attr]  # type: ignore[attr-defined]
        if not obj.__observers__:  # type: ignore[attr-defined]
            remove_observers(obj)


__all__ = [
    'ObservableDict',
    'observe',
    'remove_observers',
    'remove_observer',
]