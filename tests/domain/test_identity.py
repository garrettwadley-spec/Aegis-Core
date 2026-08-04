"""Unit tests for domain identity and core behaviors."""
from __future__ import annotations

import unittest
from aegis.domain import Identity, DomainObject, Entity, to_dict, from_dict

class TestIdentity(unittest.TestCase):
    def test_identity_uniqueness(self):
        a = Identity.new()
        b = Identity.new()
        self.assertNotEqual(a.id, b.id)

class TestVersion(unittest.TestCase):
    def test_version_preserved(self):
        d = DomainObject()
        self.assertEqual(d.version, 1)
        d2 = DomainObject(version=5)
        self.assertEqual(d2.version, 5)

class TestTrace(unittest.TestCase):
    def test_trace_and_correlation_present(self):
        d = DomainObject()
        self.assertIsNotNone(d.trace_id)
        self.assertIsNotNone(d.correlation_id)

class TestSerialization(unittest.TestCase):
    def test_roundtrip(self):
        d = DomainObject()
        data = d.to_dict()
        d2 = from_dict(data)
        self.assertEqual(d.object_id, d2.object_id)
        self.assertEqual(d.version, d2.version)
        self.assertEqual(d.trace_id, d2.trace_id)

class TestImmutability(unittest.TestCase):
    def test_immutable(self):
        d = DomainObject()
        with self.assertRaises(Exception):
            d.version = 2  # type: ignore[misc]

class TestEntity(unittest.TestCase):
    def test_entity_equality_by_id(self):
        e1 = Entity(object_id="same-id")
        e2 = Entity(object_id="same-id")
        self.assertEqual(e1, e2)
        self.assertEqual(hash(e1), hash(e2))

if __name__ == "__main__":
    unittest.main()
