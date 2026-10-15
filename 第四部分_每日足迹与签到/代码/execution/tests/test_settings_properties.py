import io
import json
from unittest.mock import patch

from django.test import SimpleTestCase
from hypothesis import given, settings
from hypothesis import strategies as st

from execution.settings_service import verify_connection
from tasks.services import ApiError


class SettingsProperties(SimpleTestCase):
    @settings(max_examples=30, deadline=None)
    @given(
        st.lists(st.text(alphabet="abcdef012345", min_size=1, max_size=20), max_size=15),
        st.booleans(),
    )
    def test_model_list_order_duplicates_and_unrelated_models(self, other_models, available):
        names = other_models + (["deepseek-flash"] * 2 if available else [])
        for ordered in [names, list(reversed(names))]:
            raw = json.dumps({"data": [{"id": name} for name in ordered]}).encode()
            with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as network:
                if available:
                    self.assertIsNone(verify_connection("private-property-key", "deepseek-flash"))
                else:
                    with self.assertRaises(ApiError) as error:
                        verify_connection("private-property-key", "deepseek-flash")
                    self.assertNotIn("private-property-key", error.exception.message)
                self.assertEqual(network.call_count, 1)
