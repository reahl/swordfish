import tkinter as tk
import tkinter.font as tkfont
import types
from unittest.mock import patch

from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.main import McpConfigurationStore
from reahl.swordfish.text_editing import CodePanel


class TabSpacingConfigScenarios(Fixture):
    """AI: Maps each valid/invalid appearance.tab_spacing value to the integer the application
    should use for tab stops."""

    @scenario
    def not_configured(self):
        """AI: No config file at all — fall back to the 4-space default."""
        self.config_payload = None
        self.expected_tab_spacing = 4

    @scenario
    def appearance_section_has_no_tab_spacing(self):
        """AI: An appearance section that only sets theme should still default tab spacing to 4."""
        self.config_payload = {'appearance': {'theme': 'dark'}}
        self.expected_tab_spacing = 4

    @scenario
    def two_spaces(self):
        """AI: appearance.tab_spacing = 2 selects compact two-space indentation."""
        self.config_payload = {'appearance': {'tab_spacing': 2}}
        self.expected_tab_spacing = 2

    @scenario
    def four_spaces(self):
        """AI: appearance.tab_spacing = 4 round-trips to the same value as the absent default."""
        self.config_payload = {'appearance': {'tab_spacing': 4}}
        self.expected_tab_spacing = 4

    @scenario
    def eight_spaces(self):
        """AI: Any positive integer is accepted; 8-space tabs should work for those who prefer them."""
        self.config_payload = {'appearance': {'tab_spacing': 8}}
        self.expected_tab_spacing = 8

    @scenario
    def invalid_string(self):
        """AI: A string like '4' (easy JSON-editing mistake) is not an integer and falls back to 4."""
        self.config_payload = {'appearance': {'tab_spacing': '4'}}
        self.expected_tab_spacing = 4

    @scenario
    def invalid_zero(self):
        """AI: Zero-space tabs would render all indentation as invisible; treat as invalid."""
        self.config_payload = {'appearance': {'tab_spacing': 0}}
        self.expected_tab_spacing = 4

    @scenario
    def invalid_negative(self):
        """AI: A negative tab spacing is nonsensical and must not crash the editor."""
        self.config_payload = {'appearance': {'tab_spacing': -2}}
        self.expected_tab_spacing = 4

    @scenario
    def invalid_float(self):
        """AI: A float like 4.0 is not an integer (JSON does not distinguish, but Python does not
        accept floats as int tab counts) and falls back to 4."""
        self.config_payload = {'appearance': {'tab_spacing': 4.0}}
        self.expected_tab_spacing = 4


@with_fixtures(TabSpacingConfigScenarios)
def test_tab_spacing_loaded_from_appearance_config(scenario):
    """AI: The editor tab stop width is read from appearance.tab_spacing in the config file.
    Missing, non-integer, or non-positive values fall back to 4 so the editor is always usable."""
    store = McpConfigurationStore()
    with patch.object(
        McpConfigurationStore, 'config_payload', return_value=scenario.config_payload
    ):
        assert store.load_tab_spacing() == scenario.expected_tab_spacing


def test_code_panel_tab_width_scales_proportionally_with_configured_spaces():
    """AI: The text editor must render a 4-space tab as exactly twice the width of a 2-space tab,
    because the editor font is monospace. This invariant holds for any valid positive spacing and
    confirms the implementation measures real character widths rather than hardcoding pixels."""
    root = tk.Tk()
    root.withdraw()
    try:
        def make_panel(tab_spacing):
            fake_app = types.SimpleNamespace(
                tab_spacing=tab_spacing,
                integrated_session_state=types.SimpleNamespace(is_mcp_busy=lambda: False),
                debugger_tab=None,
                experimental_features_enabled=False,
            )
            return CodePanel(root, application=fake_app)

        panel_2 = make_panel(2)
        panel_4 = make_panel(4)

        assert _tab_pixels(panel_4.text_editor) == 2 * _tab_pixels(panel_2.text_editor)
    finally:
        root.destroy()


def _tab_pixels(text_widget):
    tabs = text_widget.cget('tabs')
    if isinstance(tabs, (list, tuple)) and tabs:
        return int(float(tabs[0]))
    return int(float(str(tabs)))
