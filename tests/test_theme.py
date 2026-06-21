import tkinter as tk
from tkinter import ttk

from reahl.tofu import Fixture, expected, scenario, with_fixtures
from reahl.stubble import stubclass

from reahl.swordfish.theme import (
    ActiveTheme,
    DARK_THEME,
    LIGHT_THEME,
    OperatingSystemAppearance,
    Theme,
    ThemeApplication,
    ThemeSelection,
    UnknownColorRole,
)


def test_a_theme_answers_the_colour_for_a_known_role():
    """AI: A theme maps a semantic colour role (what a colour means, e.g. the editor's keyword
    colour) onto a concrete colour. Widgets ask for the role, never the literal colour, so the
    same screen renders differently under different themes without the widget knowing which."""
    theme = Theme('demo', {'editor_keyword': '#112233'})

    assert theme.color_for('editor_keyword') == '#112233'


def test_asking_a_theme_for_an_unknown_role_is_an_error():
    """AI: Roles are a closed vocabulary shared by every palette. Asking for a role the palette
    does not define is a programming mistake (a typo or a role added to one palette only), so it
    fails loudly rather than silently rendering a wrong or default colour."""
    theme = Theme('demo', {'editor_keyword': '#112233'})

    with expected(UnknownColorRole):
        theme.color_for('editor_string')


def test_light_and_dark_palettes_define_exactly_the_same_roles():
    """AI: The whole point of semantic roles is that a screen is fully themeable in either palette.
    If a role existed in only one palette, switching themes would leave part of the UI unthemed
    (or crash on lookup), so the two shipped palettes must cover identical role vocabularies."""
    assert set(LIGHT_THEME.role_names()) == set(DARK_THEME.role_names())


class ColorSchemeScenarios(Fixture):
    """AI: The desktop's reported colour-scheme text is the only signal the OS probe parses;
    these scenarios pin how each recognised (and unrecognised) value is classified."""

    @scenario
    def gnome_prefers_dark(self):
        self.color_scheme_text = "'prefer-dark'"
        self.expected_preference = True

    @scenario
    def gnome_default_is_light(self):
        self.color_scheme_text = "'default'"
        self.expected_preference = False

    @scenario
    def gnome_explicitly_prefers_light(self):
        self.color_scheme_text = "'prefer-light'"
        self.expected_preference = False

    @scenario
    def probe_produced_nothing(self):
        """AI: No desktop setting available (non-GNOME, no gsettings, command failed) - the OS
        expresses no opinion, which is distinct from preferring light."""
        self.color_scheme_text = ''
        self.expected_preference = None


@with_fixtures(ColorSchemeScenarios)
def test_operating_system_appearance_classifies_the_desktop_colour_scheme(scenario):
    @stubclass(OperatingSystemAppearance)
    class AppearanceReportingScheme(OperatingSystemAppearance):
        reported_scheme = scenario.color_scheme_text

        def read_color_scheme(self):
            return self.reported_scheme

    assert AppearanceReportingScheme().prefers_dark() is scenario.expected_preference


@stubclass(OperatingSystemAppearance)
class AppearanceWithFixedPreference(OperatingSystemAppearance):
    fixed_preference = None

    def prefers_dark(self):
        return self.fixed_preference


class ThemeSelectionScenarios(Fixture):
    """AI: How the session's theme is resolved: an explicit configured name always wins, and only
    when there is none does the OS preference (then a light default) decide."""

    @scenario
    def explicit_dark_wins_over_the_operating_system(self):
        self.configured_name = 'dark'
        self.operating_system_prefers = False
        self.expected_theme = DARK_THEME

    @scenario
    def explicit_light_wins_over_the_operating_system(self):
        self.configured_name = 'light'
        self.operating_system_prefers = True
        self.expected_theme = LIGHT_THEME

    @scenario
    def with_no_configured_name_the_operating_system_dark_preference_decides(self):
        self.configured_name = None
        self.operating_system_prefers = True
        self.expected_theme = DARK_THEME

    @scenario
    def with_no_configured_name_an_operating_system_light_preference_decides(self):
        self.configured_name = None
        self.operating_system_prefers = False
        self.expected_theme = LIGHT_THEME

    @scenario
    def with_no_configured_name_and_no_operating_system_opinion_light_is_the_default(self):
        self.configured_name = None
        self.operating_system_prefers = None
        self.expected_theme = LIGHT_THEME


@with_fixtures(ThemeSelectionScenarios)
def test_theme_selection_resolves_config_then_operating_system_then_default(scenario):
    appearance = AppearanceWithFixedPreference()
    appearance.fixed_preference = scenario.operating_system_prefers
    selection = ThemeSelection(scenario.configured_name, appearance)

    assert selection.chosen_theme() is scenario.expected_theme


def test_the_active_theme_holds_the_session_theme_once_activated():
    """AI: The chosen theme is fixed for the session and read by every widget at construction
    time, so it lives in one place the whole UI consults rather than being threaded through every
    constructor. It defaults to light until a theme is activated at startup."""
    active = ActiveTheme()
    assert active.current() is LIGHT_THEME

    active.activate(DARK_THEME)
    assert active.current() is DARK_THEME


def test_a_restyling_theme_applies_its_colours_to_a_tk_root():
    """AI: A theme that departs from the host's native look (dark) actually reaches the widgets:
    applying it switches the ttk base to the colour-honouring 'clam' theme and configures the root
    style with the palette's window colours, so ttk widgets built afterwards render in the theme."""
    root = tk.Tk()
    root.withdraw()
    try:
        ThemeApplication(root).apply(DARK_THEME)
        style = ttk.Style(root)
        assert style.theme_use() == 'clam'
        assert style.lookup('.', 'background') == DARK_THEME.color_for('window_background')
    finally:
        root.destroy()


def test_a_native_look_theme_leaves_the_widget_styling_untouched():
    """AI: Light matches the host's native widget look, so applying it must not switch the ttk base
    theme - the IDE's established appearance is preserved with no global restyling, only the
    per-site semantic colours (whose light values equal the original hardcoded ones) apply."""
    root = tk.Tk()
    root.withdraw()
    try:
        original_theme = ttk.Style(root).theme_use()
        ThemeApplication(root).apply(LIGHT_THEME)
        assert ttk.Style(root).theme_use() == original_theme
    finally:
        root.destroy()
