"""Property tests for cache integrity round trip.

# Feature: design-gap-completion, Property 10: Cache Integrity Round Trip

Validates: Requirements 18.1, 18.2, 18.3, 18.4
"""

import os
import json
import tempfile

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.cache import DiskCache, CACHE_VERSION, META_KEY, _compute_data_checksum


# --- Strategies ---

# Generate namespace strings
namespaces = st.sampled_from(["tvmaze", "wikidata", "wikipedia", "test"])

# Generate cache key strings
cache_keys = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789:+-_",
    min_size=1, max_size=30,
)

# Generate cache values (various JSON-serializable types)
cache_values = st.one_of(
    st.text(min_size=0, max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
    st.dictionaries(
        keys=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
        values=st.one_of(st.text(min_size=0, max_size=20), st.integers()),
        min_size=0, max_size=5,
    ),
    st.lists(st.one_of(st.text(min_size=0, max_size=10), st.integers()), max_size=5),
)

# Generate cache entries (namespace, key, value triples)
cache_entries = st.lists(
    st.tuples(namespaces, cache_keys, cache_values),
    min_size=0, max_size=20,
)


class TestCacheIntegrityRoundTrip:
    """Property 10: For any cache state, persisting to disk and reloading SHALL
    produce an identical data set, verified by the SHA-256 checksum. If the checksum
    does not match on load, the cache is discarded (empty state).
    """

    @settings(max_examples=100)
    @given(entries=cache_entries)
    def test_persist_and_reload_preserves_data(self, entries):
        """Any set of entries persisted and reloaded produces identical values."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            # Populate cache
            for ns, key, value in entries:
                cache.set(ns, key, value)

            # Build expected state (last write wins for duplicate keys)
            expected = {}
            for ns, key, value in entries:
                expected[(ns, key)] = value

            # Reload from disk
            cache2 = DiskCache(path, ttl=999999)

            # Verify all entries are present with correct values
            for (ns, key), value in expected.items():
                result = cache2._data.get(f"{ns}:{key}")
                assert result is not None, (
                    f"Entry {ns}:{key} missing after reload"
                )
                assert result["value"] == value, (
                    f"Value mismatch for {ns}:{key}: {result['value']} != {value}"
                )

    @settings(max_examples=100)
    @given(entries=cache_entries)
    def test_checksum_validates_integrity(self, entries):
        """The checksum in _meta matches recomputed checksum on reload."""
        assume(len(entries) > 0)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            for ns, key, value in entries:
                cache.set(ns, key, value)

            # Read raw file and verify checksum
            with open(path) as f:
                raw = json.load(f)

            assert META_KEY in raw
            stored_checksum = raw[META_KEY]["checksum"]

            # Recompute checksum
            data_without_meta = {k: v for k, v in raw.items() if k != META_KEY}
            recomputed = _compute_data_checksum(raw)
            assert stored_checksum == recomputed

    @settings(max_examples=50)
    @given(entries=cache_entries)
    def test_corrupt_checksum_discards_data(self, entries):
        """If checksum is corrupted, reload produces an empty cache."""
        assume(len(entries) > 0)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            for ns, key, value in entries:
                cache.set(ns, key, value)

            # Corrupt the checksum
            with open(path) as f:
                raw = json.load(f)
            raw[META_KEY]["checksum"] = "0000000000000000000000000000000000000000000000000000000000000000"
            with open(path, "w") as f:
                json.dump(raw, f)

            # Reload — should discard everything
            cache2 = DiskCache(path, ttl=999999)
            assert len(cache2._data) == 0

            # Verify corrupt file was created
            files = os.listdir(d)
            corrupt_files = [f for f in files if ".corrupt." in f]
            assert len(corrupt_files) == 1

    @settings(max_examples=50)
    @given(entries=cache_entries)
    def test_outdated_version_discards_data(self, entries):
        """If version is lower than current, reload produces an empty cache."""
        assume(len(entries) > 0)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            for ns, key, value in entries:
                cache.set(ns, key, value)

            # Set version to 0 (outdated)
            with open(path) as f:
                raw = json.load(f)
            raw[META_KEY]["version"] = 0
            with open(path, "w") as f:
                json.dump(raw, f)

            # Reload — should discard due to version mismatch
            cache2 = DiskCache(path, ttl=999999)
            assert len(cache2._data) == 0

    @settings(max_examples=50)
    @given(entries=cache_entries)
    def test_version_field_is_current(self, entries):
        """Persisted cache always has current version number."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            for ns, key, value in entries:
                cache.set(ns, key, value)

            if os.path.exists(path):
                with open(path) as f:
                    raw = json.load(f)
                assert raw[META_KEY]["version"] == CACHE_VERSION

    @settings(max_examples=50)
    @given(entries=cache_entries)
    def test_checksum_deterministic(self, entries):
        """Same data always produces same checksum."""
        with tempfile.TemporaryDirectory() as d:
            path1 = os.path.join(d, "c1.json")
            path2 = os.path.join(d, "c2.json")

            cache1 = DiskCache(path1, ttl=999999)
            cache2 = DiskCache(path2, ttl=999999)

            for ns, key, value in entries:
                cache1.set(ns, key, value)
                cache2.set(ns, key, value)

            if entries:
                with open(path1) as f:
                    raw1 = json.load(f)
                with open(path2) as f:
                    raw2 = json.load(f)
                assert raw1[META_KEY]["checksum"] == raw2[META_KEY]["checksum"]

    @settings(max_examples=50)
    @given(
        entries=cache_entries,
        extra_ns=namespaces,
        extra_key=cache_keys,
        extra_val=cache_values,
    )
    def test_data_modification_changes_checksum(self, entries, extra_ns, extra_key, extra_val):
        """Adding data changes the checksum."""
        assume(len(entries) > 0)
        # Ensure extra entry isn't already in the set
        existing_keys = {(ns, key) for ns, key, _ in entries}
        assume((extra_ns, extra_key) not in existing_keys)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path, ttl=999999)

            for ns, key, value in entries:
                cache.set(ns, key, value)

            with open(path) as f:
                raw1 = json.load(f)
            checksum_before = raw1[META_KEY]["checksum"]

            # Add extra entry
            cache.set(extra_ns, extra_key, extra_val)

            with open(path) as f:
                raw2 = json.load(f)
            checksum_after = raw2[META_KEY]["checksum"]

            assert checksum_before != checksum_after, (
                "Checksum should change when data changes"
            )

    def test_empty_cache_persists_valid_meta(self):
        """An empty cache still persists valid _meta on first write."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            cache = DiskCache(path)
            cache.set("ns", "k", "v")
            cache.clear()

            if os.path.exists(path):
                with open(path) as f:
                    raw = json.load(f)
                assert META_KEY in raw
                assert raw[META_KEY]["version"] == CACHE_VERSION
                assert "checksum" in raw[META_KEY]

    def test_corrupt_json_rotates_file(self):
        """A file that isn't valid JSON gets rotated."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cache.json")
            with open(path, "w") as f:
                f.write("not valid json {{{")

            cache = DiskCache(path)
            assert len(cache._data) == 0
            corrupt_files = [f for f in os.listdir(d) if ".corrupt." in f]
            assert len(corrupt_files) == 1
