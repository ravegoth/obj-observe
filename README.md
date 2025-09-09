# obj-observe

`obj-observe` is a simple, zero-dependency Python library for observing changes on object attributes and dictionary keys.

[![PyPI version](https://img.shields.io/pypi/v/obj-observe.svg)](https://pypi.org/project/obj-observe/)
[![Python versions](https://img.shields.io/pypi/pyversions/obj-observe.svg)](https://pypi.org/project/obj-observe/)

## Installation

```bash
pip install obj-observe
```

---

## Example

```python
from obj_observe import observe

class Player:
    def __init__(self):
        self.hp = 100

p = Player()

@observe(p, "hp")
def on_hp_change(old, new):
    print(f"HP changed: {old} -> {new}")

p.hp = 50
```

## Core Functions

### `observe(obj, attr, callback=None)`

This is the main function for attaching an observer to an attribute or key.

*   **As a Decorator:**

    ```python
    from obj_observe import observe

    class Player:
        def __init__(self, hp):
            self.hp = hp

    p = Player(100)

    @observe(p, 'hp')
    def on_hp_change(old_value, new_value):
        print(f"HP changed from {old_value} to {new_value}")

    p.hp = 150  # Prints: HP changed from 100 to 150
    ```

*   **With a Callback Function:**

    ```python
    def hp_watcher(old, new):
        print(f"HP was {old}, now it is {new}")

    observe(p, 'hp', hp_watcher)

    p.hp = 50 # Prints: HP was 150, now it is 50
    ```

*   **Observing Dictionary Keys:**

    When observing a dictionary, `observe` returns an `ObservableDict`. You must use this new object to track changes.

    ```python
    my_dict = {'status': 'idle'}

    def on_status_change(old, new):
        print(f"Status changed from '{old}' to '{new}'")

    my_dict = observe(my_dict, 'status', on_status_change)

    my_dict['status'] = 'running' # Prints: Status changed from 'idle' to 'running'
    ```

### `remove_observers(obj, attr=None)`

Detaches observers from an object.

*   **Remove Observers from a Specific Attribute:**

    ```python
    remove_observers(p, 'hp')
    p.hp = 0 # No notification will be sent
    ```

*   **Remove All Observers from an Object:**

    ```python
    remove_observers(p)
    ```

---

## License

MIT
