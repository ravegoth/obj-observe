
import unittest
from obj_observe import observe, remove_observers, remove_observer, ObservableDict

class Player:
    def __init__(self, hp):
        self.hp = hp

class TestObserve(unittest.TestCase):

    def test_observe_attribute(self):
        p = Player(100)
        self.hp_changed = False

        def hp_observer(old, new):
            self.hp_changed = True
            self.assertEqual(old, 100)
            self.assertEqual(new, 150)

        observe(p, 'hp', hp_observer)
        p.hp = 150
        self.assertTrue(self.hp_changed)

    def test_observe_dict(self):
        d = {'a': 1}
        self.a_changed = False

        def a_observer(old, new):
            self.a_changed = True
            self.assertEqual(old, 1)
            self.assertEqual(new, 2)

        d = observe(d, 'a', a_observer)
        d['a'] = 2
        self.assertTrue(self.a_changed)
        self.assertIsInstance(d, ObservableDict)

    def test_multiple_observers(self):
        p = Player(100)
        self.observer1_called = False
        self.observer2_called = False

        def observer1(old, new):
            self.observer1_called = True

        def observer2(old, new):
            self.observer2_called = True

        observe(p, 'hp', observer1)
        observe(p, 'hp', observer2)
        p.hp = 200
        self.assertTrue(self.observer1_called)
        self.assertTrue(self.observer2_called)

    def test_remove_observers(self):
        p = Player(100)
        self.hp_changed = False

        def hp_observer(old, new):
            self.hp_changed = True

        observe(p, 'hp', hp_observer)
        remove_observers(p, 'hp')
        p.hp = 150
        self.assertFalse(self.hp_changed)

    def test_decorator(self):
        p = Player(100)
        self.decorated_called = False

        @observe(p, 'hp')
        def decorated_observer(old, new):
            self.decorated_called = True

        p.hp = 150
        self.assertTrue(self.decorated_called)

    # --- Additional tests ---
    def test_same_value_assignment_triggers(self):
        p = Player(10)
        calls = []
        observe(p, 'hp', lambda o, n: calls.append((o, n)))
        p.hp = 10
        self.assertEqual(calls, [(10, 10)])

    def test_multiple_instances_independent(self):
        p1, p2 = Player(1), Player(2)
        c1, c2 = [], []
        observe(p1, 'hp', lambda o, n: c1.append(n))
        observe(p2, 'hp', lambda o, n: c2.append(n))
        p1.hp = 3
        p2.hp = 4
        self.assertEqual(c1, [3])
        self.assertEqual(c2, [4])

    def test_remove_all_then_set(self):
        p = Player(5)
        called = []
        observe(p, 'hp', lambda o, n: called.append(n))
        remove_observers(p)
        p.hp = 6
        self.assertFalse(called)

    def test_remove_single_observer(self):
        p = Player(5)
        a, b = [], []
        def oa(o, n): a.append(n)
        def ob(o, n): b.append(n)
        observe(p, 'hp', oa)
        observe(p, 'hp', ob)
        remove_observer(p, 'hp', oa)
        p.hp = 9
        self.assertEqual(a, [])
        self.assertEqual(b, [9])

    def test_remove_single_observer_missing(self):
        p = Player(5)
        def oa(o, n): pass
        remove_observer(p, 'hp', oa)  # should not raise
        self.assertTrue(True)

    def test_observe_plain_dict_returns_observable(self):
        d = {'x': 1}
        d2 = observe(d, 'x', lambda o, n: None)
        self.assertIsInstance(d2, ObservableDict)

    def test_observable_dict_set_twice(self):
        d = observe({'x': 1}, 'x', lambda o, n: None)
        d['x'] = 2
        d['x'] = 3
        self.assertEqual(d['x'], 3)

    def test_observable_dict_remove_observers_specific(self):
        d = observe({'x': 1}, 'x', lambda o, n: None)
        remove_observers(d, 'x')
        d['x'] = 2  # should not error
        self.assertEqual(d['x'], 2)

    def test_observable_dict_remove_all(self):
        d = observe({'x': 1, 'y': 2}, 'x', lambda o, n: None)
        remove_observers(d)
        d['x'] = 9
        self.assertEqual(d['x'], 9)

    def test_chained_observer_adds(self):
        p = Player(1)
        vals = []
        observe(p, 'hp', lambda o, n: vals.append(n))
        observe(p, 'hp', lambda o, n: vals.append(n*2))
        p.hp = 2
        self.assertEqual(vals, [2, 4])

    def test_observer_mutates_same_attr(self):
        p = Player(1)
        def obs(o, n):
            if n < 5:
                p.hp = n + 5  # Should not infinite recurse
        observe(p, 'hp', obs)
        p.hp = 2
        self.assertEqual(p.hp, 7)

    def test_attribute_added_later(self):
        class X:
            __slots__ = ('foo', '__weakref__')

        x = X()
        observe(x, 'foo', lambda o, n: None)
        x.foo = 3
        self.assertEqual(x.foo, 3)

        # Allow x to be garbage collected without explicit cleanup
        import gc
        import weakref

        ref = weakref.ref(x)
        del x
        gc.collect()
        self.assertIsNone(ref())

        # After GC, class-level storage should be cleared and new instances work
        y = X()
        y.foo = 1  # should not raise
        observe(y, 'foo', lambda o, n: None)
        y.foo = 2
        self.assertEqual(y.foo, 2)

    def test_attribute_removed_remaining_instance(self):
        p1, p2 = Player(1), Player(2)
        observe(p1, 'hp', lambda o, n: None)
        observe(p2, 'hp', lambda o, n: None)
        remove_observers(p1)
        p2.hp = 4
        self.assertEqual(p2.hp, 4)

    def test_remove_all_instances_restores_setattr(self):
        p1 = Player(1)
        observe(p1, 'hp', lambda o, n: None)
        remove_observers(p1)
        # After removal, setattr should still work normally
        p1.hp = 10
        self.assertEqual(p1.hp, 10)

    def test_remove_single_then_other_still_active(self):
        p1, p2 = Player(1), Player(2)
        c = []
        observe(p1, 'hp', lambda o, n: c.append(('p1', n)))
        observe(p2, 'hp', lambda o, n: c.append(('p2', n)))
        remove_observers(p1)
        p2.hp = 5
        self.assertIn(('p2', 5), c)

    def test_no_observers_do_nothing(self):
        p = Player(1)
        p.hp = 2  # no errors
        self.assertEqual(p.hp, 2)

    def test_remove_observers_on_plain_unobserved(self):
        p = Player(1)
        remove_observers(p)  # should not raise
        self.assertTrue(True)

    def test_remove_observer_on_plain_unobserved(self):
        p = Player(1)
        remove_observer(p, 'hp', lambda o, n: None)  # should not raise
        self.assertTrue(True)

    def test_observer_list_mutation_during_callback(self):
        p = Player(1)
        calls = []

        def obs1(o, n):
            calls.append('a')
            remove_observers(p, 'hp')

        observe(p, 'hp', obs1)
        # Add another after first; because iteration copies the list, second still fires once
        observe(p, 'hp', lambda o, n: calls.append('b'))
        p.hp = 3
        self.assertEqual(calls, ['a', 'b'])

    def test_slotted_without_weakref_fallback(self):
        class S:
            __slots__ = ('v',)
            def __init__(self):
                self.v = 0
        s = S()
        seen = []
        observe(s, 'v', lambda o, n: seen.append(n))
        s.v = 1
        self.assertEqual(seen, [1])

    def test_slotted_with_weakref_gc_cleanup(self):
        import gc
        import weakref as _wr
        class W:
            __slots__ = ('v', '__weakref__')
            def __init__(self):
                self.v = 0
        w = W()
        observe(w, 'v', lambda o, n: None)
        wref = _wr.ref(w)
        # Drop strong ref and collect
        del w
        gc.collect()
        self.assertIsNone(wref())
        # Class should eventually restore original setattr when no instances observed
        self.assertFalse(hasattr(W, '__original_setattr__') and hasattr(W, '__observe_refcount__'))

    def test_bound_method_observer_does_not_keep_instance_alive(self):
        import gc
        import weakref as _wr
        class Emitter:
            def __init__(self):
                self.x = 0
            def on_x(self, o, n):
                pass
        em = Emitter()
        # Bound method should be wrapped via WeakMethod and not keep 'em' alive
        observe(em, 'x', em.on_x)
        wref = _wr.ref(em)
        del em
        gc.collect()
        self.assertIsNone(wref())

    def test_thread_safety_concurrent_sets(self):
        import threading
        class T:
            def __init__(self):
                self.v = 0
        t = T()
        vals = []
        lock = threading.Lock()
        observe(t, 'v', lambda o, n: (lock.acquire(), vals.append(n), lock.release()))

        def worker(n):
            for _ in range(100):
                t.v = n

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        # We should have recorded many values and not deadlocked
        self.assertGreater(len(vals), 0)

if __name__ == '__main__':
    unittest.main()
