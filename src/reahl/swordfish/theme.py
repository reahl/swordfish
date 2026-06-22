"""The colour language of the IDE.

Every colour shown in Swordfish is named by a semantic *role* - what the colour means
(the editor's keyword colour, a class node's outline, the safe-risk indicator) rather than
a literal value. A Theme maps the shared vocabulary of roles onto concrete colours, so the
whole UI can render light or dark without any widget knowing which palette is in force.

The active theme is resolved once, at startup, from configuration and the operating system's
colour-scheme preference, and then held by the single ActiveTheme registry that widgets read
from while they build themselves. It does not change on the fly; changing themes means
restarting. See DESIGN.md for the colour-and-theming conventions.
"""

import subprocess
from tkinter import ttk


class UnknownColorRole(Exception):
    """AI: Raised when a colour is requested for a role the palette does not define - a typo or a
    role added to one palette but not the other. Roles are a closed, shared vocabulary, so an
    unknown role is a programming error, not a missing-colour-to-default-away situation."""


class Theme:
    """AI: A named palette: a mapping from semantic colour roles to concrete colours."""

    def __init__(self, name, colors, restyles_widgets=False):
        self.name = name
        self.colors = colors
        # AI: Whether this theme departs from the host's native widget look and so must push
        # global colours into the Tk option database and restyle the ttk widgets. Light leaves
        # this False: native light defaults already match the IDE's established appearance, so
        # only the per-site semantic colours apply and there is no visual regression. Dark sets
        # it True because it must actively override the native (light) widget colours.
        self.restyles_widgets = restyles_widgets

    def role_names(self):
        return self.colors.keys()

    def color_for(self, role):
        if role not in self.colors:
            raise UnknownColorRole(
                'No colour defined for role %r in the %r theme.' % (role, self.name)
            )
        return self.colors[role]


# AI: The shared role vocabulary lives implicitly in these two dictionaries: both palettes must
# define identical keys (a test enforces this) so any screen is fully themeable in either.
LIGHT_THEME = Theme(
    'light',
    {
        # AI: Global defaults pushed into the Tk option database for classic-tk widgets.
        'window_background': '#ececec',
        'window_foreground': '#000000',
        'select_background': '#3366cc',
        'select_foreground': '#ffffff',
        'control_background': '#e0e0e0',
        'border': '#a0a0a0',
        # AI: The code editor and its syntax highlighting.
        'editor_background': '#ffffff',
        'editor_foreground': '#000000',
        'editor_cursor': '#000000',
        'line_number_background': '#f2f2f2',
        'line_number_foreground': '#666666',
        'syntax_keyword': 'blue',
        'syntax_comment': 'green',
        'syntax_string': 'orange',
        'syntax_symbol': '#008b8b',
        'syntax_number': '#800080',
        'syntax_selector': '#008080',
        'syntax_character': '#8b4513',
        'selection_highlight': 'darkgrey',
        'breakpoint_background': '#ff6b6b',
        'breakpoint_foreground': '#000000',
        'compile_error_background': '#ffe4e4',
        'disabled_list_item': 'gray50',
        # AI: The closable-tab close glyph in its three interaction states.
        'close_glyph': '#666666',
        'close_glyph_hover': '#222222',
        'close_glyph_pressed': '#000000',
        'tooltip_background': '#ffffe0',
        'tooltip_foreground': '#000000',
        # AI: Status-bar and risk semantics.
        'risk_safe': '#006600',
        'risk_unsafe': '#aa4400',
        'status_busy': 'darkorange',
        'status_muted': 'gray',
        'status_error': 'red',
        # AI: Class- and object-diagram canvas drawing.
        'diagram_canvas_background': '#ffffff',
        'class_node_fill': '#fff9e6',
        'class_node_outline': '#8a6d1f',
        'class_name_text': '#533f05',
        'method_text': '#222222',
        'relationship_line': '#444444',
        'inheritance_direct': '#2266aa',
        'inheritance_inferred': '#9aa4b2',
        'relationship_label': '#222288',
        'object_node_fill': '#e8f0fe',
        'object_node_outline': '#3366cc',
        'object_oop_text': '#3366cc',
        'object_class_text': '#222222',
    },
)


DARK_THEME = Theme(
    'dark',
    {
        'window_background': '#2b2b2b',
        'window_foreground': '#e0e0e0',
        'select_background': '#4a6da7',
        'select_foreground': '#ffffff',
        'control_background': '#3c3c3c',
        'border': '#555555',
        'editor_background': '#1e1e1e',
        'editor_foreground': '#e0e0e0',
        'editor_cursor': '#e0e0e0',
        'line_number_background': '#252526',
        'line_number_foreground': '#858585',
        'syntax_keyword': '#569cd6',
        'syntax_comment': '#6a9955',
        'syntax_string': '#ce9178',
        'syntax_symbol': '#4ec9b0',
        'syntax_number': '#b5cea8',
        'syntax_selector': '#dcdcaa',
        'syntax_character': '#d7ba7d',
        'selection_highlight': '#3a3d41',
        'breakpoint_background': '#aa3333',
        'breakpoint_foreground': '#ffffff',
        'compile_error_background': '#5a2d2d',
        'disabled_list_item': '#777777',
        'close_glyph': '#aaaaaa',
        'close_glyph_hover': '#ffffff',
        'close_glyph_pressed': '#dddddd',
        'tooltip_background': '#3c3c3c',
        'tooltip_foreground': '#e0e0e0',
        'risk_safe': '#6abf69',
        'risk_unsafe': '#e0913a',
        'status_busy': '#e0913a',
        'status_muted': '#999999',
        'status_error': '#f47067',
        'diagram_canvas_background': '#1e1e1e',
        'class_node_fill': '#3a3a2a',
        'class_node_outline': '#c9b070',
        'class_name_text': '#e6d8a8',
        'method_text': '#d0d0d0',
        'relationship_line': '#9aa4b2',
        'inheritance_direct': '#6fa8dc',
        'inheritance_inferred': '#5a6b80',
        'relationship_label': '#aab4e8',
        'object_node_fill': '#22344a',
        'object_node_outline': '#6fa8dc',
        'object_oop_text': '#9ec9f0',
        'object_class_text': '#d0d0d0',
    },
    restyles_widgets=True,
)


class OperatingSystemAppearance:
    """AI: The host desktop's light/dark preference, as far as it can be discovered. On Linux/GNOME
    this reads the freedesktop colour-scheme via gsettings; there is no portable Tk API for it, so
    the probe is best-effort and reports None when it cannot tell. read_color_scheme is the single
    I/O leaf, kept separate so it can be stubbed in tests."""

    def read_color_scheme(self):
        try:
            completed = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ''

    def prefers_dark(self):
        scheme = self.read_color_scheme()
        if 'prefer-dark' in scheme:
            return True
        elif 'prefer-light' in scheme or 'default' in scheme:
            return False
        else:
            return None


class ThemeSelection:
    """AI: Resolves which theme a session runs under: an explicitly configured name wins outright,
    otherwise the operating system's preference decides, and failing that light is the default."""

    def __init__(
        self,
        configured_theme_name,
        operating_system_appearance,
        light_theme=LIGHT_THEME,
        dark_theme=DARK_THEME,
    ):
        self.configured_theme_name = configured_theme_name
        self.operating_system_appearance = operating_system_appearance
        self.light_theme = light_theme
        self.dark_theme = dark_theme

    def chosen_theme(self):
        if self.configured_theme_name == self.dark_theme.name:
            chosen = self.dark_theme
        elif self.configured_theme_name == self.light_theme.name:
            chosen = self.light_theme
        elif self.operating_system_appearance.prefers_dark() is True:
            chosen = self.dark_theme
        else:
            chosen = self.light_theme
        return chosen


class ActiveTheme:
    """AI: The single place the whole UI reads its colours from. The startup code activates the
    resolved theme here; every widget then asks the current theme for the roles it needs as it
    builds itself. Defaults to light so colour lookups are always answerable, even before startup
    has run (e.g. in isolated widget tests)."""

    def __init__(self, theme=LIGHT_THEME):
        self.theme = theme

    def activate(self, theme):
        self.theme = theme

    def current(self):
        return self.theme


class ThemeApplication:
    """AI: Applies a theme to a Tk root window. A theme that matches the host's native widget look
    (light) needs nothing applied globally - its per-site semantic colours already match the
    established appearance. A theme that departs from it (dark) seeds the Tk option database so
    classic-tk widgets follow, and restyles the ttk widgets (which ignore the option database)."""

    def __init__(self, tk_root):
        self.tk_root = tk_root

    def apply(self, theme):
        if theme.restyles_widgets:
            self.install_option_defaults(theme)
            self.install_ttk_styles(theme)

    def install_option_defaults(self, theme):
        # AI: Classic-tk widgets (Frame/Label/Button/Menu/Text/Listbox/Entry) ignore ttk styling
        # and read any unset option from the Tk option database. Seeding it themes every such
        # widget created afterwards without editing each construction site.
        window_background = theme.color_for('window_background')
        window_foreground = theme.color_for('window_foreground')
        select_background = theme.color_for('select_background')
        select_foreground = theme.color_for('select_foreground')
        editor_background = theme.color_for('editor_background')
        editor_foreground = theme.color_for('editor_foreground')
        editor_cursor = theme.color_for('editor_cursor')
        defaults = {
            '*background': window_background,
            '*foreground': window_foreground,
            '*activeBackground': select_background,
            '*activeForeground': select_foreground,
            '*selectBackground': select_background,
            '*selectForeground': select_foreground,
            '*highlightBackground': window_background,
            '*disabledForeground': theme.color_for('status_muted'),
            '*troughColor': window_background,
            '*Text.background': editor_background,
            '*Text.foreground': editor_foreground,
            '*Text.insertBackground': editor_cursor,
            '*Entry.background': editor_background,
            '*Entry.foreground': editor_foreground,
            '*Entry.insertBackground': editor_cursor,
            '*Listbox.background': editor_background,
            '*Listbox.foreground': editor_foreground,
            # AI: A ttk.Combobox's dropdown is a classic tk.Listbox in a separate popdown window,
            # styled only through these option-DB resources (not the TCombobox ttk style).
            '*TCombobox*Listbox.background': editor_background,
            '*TCombobox*Listbox.foreground': editor_foreground,
            '*TCombobox*Listbox.selectBackground': select_background,
            '*TCombobox*Listbox.selectForeground': select_foreground,
            '*Menu.background': window_background,
            '*Menu.foreground': window_foreground,
            '*Menu.activeBackground': select_background,
            '*Menu.activeForeground': select_foreground,
        }
        for option_pattern, color in defaults.items():
            self.tk_root.option_add(option_pattern, color)
        # AI: The root window is created before the option database is seeded (the option DB only
        # themes widgets born after it), so it keeps its default light background and shows through
        # the padding around gridded children as a pale border. Colour it imperatively.
        self.tk_root.configure(background=window_background)

    def install_ttk_styles(self, theme):
        # AI: Native/aqua ttk themes ignore most colour options; 'clam' honours them. clam draws a
        # widget's relief from its lightcolor (top bevel) and darkcolor (bottom bevel): containers
        # stay flat (both = window background), but *controls* (buttons, tabs, scrollbars) get a
        # distinct control_background face and a real bevel so they remain visible against the
        # window. The root '.' style cascades; per-widget styles add selected/active mappings.
        window_background = theme.color_for('window_background')
        window_foreground = theme.color_for('window_foreground')
        select_background = theme.color_for('select_background')
        select_foreground = theme.color_for('select_foreground')
        editor_background = theme.color_for('editor_background')
        editor_foreground = theme.color_for('editor_foreground')
        control_background = theme.color_for('control_background')
        border = theme.color_for('border')
        editor_cursor = theme.color_for('editor_cursor')
        style = ttk.Style(self.tk_root)
        style.theme_use('clam')
        style.configure(
            '.',
            background=window_background,
            foreground=window_foreground,
            fieldbackground=editor_background,
            bordercolor=border,
            troughcolor=window_background,
            arrowcolor=window_foreground,
            insertcolor=editor_cursor,
            lightcolor=window_background,
            darkcolor=window_background,
        )
        style.configure(
            'TButton',
            background=control_background,
            foreground=window_foreground,
            bordercolor=border,
            lightcolor=control_background,
            darkcolor=editor_background,
            relief='raised',
            focuscolor=select_background,
            padding=(8, 3),
        )
        style.map(
            'TButton',
            background=[('pressed', select_background), ('active', select_background)],
            foreground=[('active', select_foreground), ('pressed', select_foreground)],
            relief=[('pressed', 'sunken')],
        )
        style.configure(
            'TCheckbutton', background=window_background, foreground=window_foreground
        )
        style.map(
            'TCheckbutton',
            indicatorcolor=[
                ('selected', select_background),
                ('!selected', editor_background),
            ],
        )
        style.configure(
            'TRadiobutton', background=window_background, foreground=window_foreground
        )
        style.map(
            'TRadiobutton',
            indicatorcolor=[
                ('selected', select_background),
                ('!selected', editor_background),
            ],
        )
        style.configure(
            'Treeview',
            background=editor_background,
            foreground=editor_foreground,
            fieldbackground=editor_background,
        )
        style.map(
            'Treeview',
            background=[('selected', select_background)],
            foreground=[('selected', select_foreground)],
        )
        style.configure(
            'Treeview.Heading',
            background=control_background,
            foreground=window_foreground,
            bordercolor=border,
            relief='flat',
        )
        style.map(
            'Treeview.Heading',
            background=[('pressed', select_background), ('active', control_background)],
            foreground=[('pressed', select_foreground), ('active', window_foreground)],
        )
        style.configure(
            'TEntry',
            fieldbackground=editor_background,
            foreground=editor_foreground,
            bordercolor=border,
            insertcolor=editor_cursor,
        )
        style.configure(
            'TCombobox',
            fieldbackground=editor_background,
            foreground=editor_foreground,
            bordercolor=border,
            arrowcolor=window_foreground,
        )
        # AI: clam paints a readonly combobox field light by default; map its readonly/disabled
        # states explicitly so the field stays dark and its text legible.
        style.map(
            'TCombobox',
            fieldbackground=[
                ('readonly', control_background),
                ('disabled', window_background),
            ],
            foreground=[('readonly', window_foreground), ('disabled', border)],
            selectbackground=[('readonly', control_background)],
            selectforeground=[('readonly', window_foreground)],
            arrowcolor=[('disabled', border)],
        )
        style.configure('TNotebook', background=window_background, bordercolor=border)
        style.configure(
            'TNotebook.Tab',
            background=control_background,
            foreground=window_foreground,
            bordercolor=border,
            lightcolor=control_background,
            padding=(8, 3),
        )
        style.map(
            'TNotebook.Tab',
            background=[('selected', select_background)],
            foreground=[('selected', select_foreground)],
        )
        style.configure(
            'TScrollbar',
            background=control_background,
            troughcolor=window_background,
            bordercolor=border,
            arrowcolor=window_foreground,
        )
        style.map('TScrollbar', background=[('active', select_background)])
        style.configure(
            'TLabelframe', background=window_background, bordercolor=border
        )
        style.configure(
            'TLabelframe.Label',
            background=window_background,
            foreground=window_foreground,
        )
        style.configure(
            'TProgressbar',
            background=select_background,
            troughcolor=window_background,
            bordercolor=border,
        )


# AI: The process-wide active theme. A single shared instance (not a function) so widgets in any
# module read the same session theme; startup calls activate() on it once.
active_theme = ActiveTheme()
