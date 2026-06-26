import types
from unittest.mock import Mock, patch

import tkinter as tk
from reahl.tofu import Fixture, NoException, expected, scenario, with_fixtures

from reahl.swordfish.gemstone.smalltalk_method_parser import SmalltalkMethodFormat
from reahl.swordfish.main import McpConfigurationStore
from reahl.swordfish.text_editing import EditorTab


class FormatterScenarios(Fixture):
    """AI: Each scenario maps a method source to the expected canonical AST-formatted output.

    The formatter is AST-based: it parses the method to a full recursive AST and
    pretty-prints it in the canonical GemStone/Wonka tab style.  Hand-placed
    alignment and blank lines are not preserved; the output is always the canonical form.
    Key rules: body at 1 tab; 2+ keyword sends always multi-line (receiver on opener
    line, each keyword:arg at depth+1); short blocks inline; ^ followed by a space."""

    @scenario
    def unary_method(self):
        """AI: A unary method body is formatted to 1 tab with a space after ^."""
        self.source = 'myMethod\n    ^42'
        self.expected = 'myMethod\n\t^ 42'

    @scenario
    def binary_method(self):
        """AI: A binary method header is normalised; body uses ^ with a space."""
        self.source = '+  aValue\n    ^self total + aValue'
        self.expected = '+ aValue\n\t^ self total + aValue'

    @scenario
    def keyword_method_single(self):
        """AI: A 1-keyword body send with no long-block arg stays on one line."""
        self.source = 'addValue: aValue\n    total := total + aValue.\n    ^self'
        self.expected = 'addValue: aValue\n\ttotal := total + aValue.\n\t^ self'

    @scenario
    def keyword_method_multi(self):
        """AI: A 2-keyword body send is always multi-line: receiver on opener line,
        each keyword:arg on the next line at depth+1."""
        self.source = 'at:   key   put: aValue\n    dict at: key put: aValue'
        self.expected = 'at: key put: aValue\n\tdict\n\t\tat: key\n\t\tput: aValue'

    @scenario
    def method_with_temporaries(self):
        """AI: Temp declaration at 1 tab; each statement at 1 tab."""
        self.source = 'compute\n    | x y |\n    x := 3.\n    y := 4.\n    ^x + y'
        self.expected = 'compute\n\t| x y |\n\tx := 3.\n\ty := 4.\n\t^ x + y'

    @scenario
    def tabs_replace_spaces(self):
        """AI: Space-indented body is normalised to 1 tab."""
        self.source = 'getValue\n    ^value'
        self.expected = 'getValue\n\t^ value'

    @scenario
    def zero_indent_normalised_to_one_tab(self):
        """AI: Source with no body indentation gets 1 tab regardless of what was present."""
        self.source = 'getValue\n^value'
        self.expected = 'getValue\n\t^ value'

    @scenario
    def already_canonical(self):
        """AI: A method already in canonical 1-tab style with spaced ^ passes through unchanged."""
        self.source = 'getValue\n\t^ value'
        self.expected = 'getValue\n\t^ value'

    @scenario
    def comment_at_method_top(self):
        """AI: A comment before the first statement is placed at 1 tab followed by a blank
        separator line — matching the Wonka leading-comment convention."""
        self.source = 'getValue\n    "Returns the stored value."\n    ^value'
        self.expected = 'getValue\n\t"Returns the stored value."\n\n\t^ value'

    @scenario
    def dot_terminated_statements(self):
        """AI: All statements except the last carry a period separator."""
        self.source = 'run\n    self prepare.\n    ^self'
        self.expected = 'run\n\tself prepare.\n\t^ self'

    @scenario
    def multi_keyword_with_comment_and_temps(self):
        """AI: A method with a leading comment, temps, and 2-keyword sends is formatted
        in canonical Wonka style: comment→blank→temps→receiver-at-L, keyword:arg-at-L+1."""
        self.source = (
            'add: newObject after: targetObject\n'
            '\n'
            '"Adds newObject after targetObject."\n'
            '\n'
            '| index |\n'
            '\n'
            "index := self indexOf: targetObject\n"
            "             ifAbsent: [^ self error: 'not found'].\n"
            '\n'
            "^ self insertObject: newObject at: (index + 1).\n"
        )
        self.expected = (
            'add: newObject after: targetObject\n'
            '\t"Adds newObject after targetObject."\n'
            '\n'
            '\t| index |\n'
            '\tindex := self\n'
            '\t\tindexOf: targetObject\n'
            "\t\tifAbsent: [ ^ self error: 'not found' ].\n"
            '\t^ self\n'
            '\t\tinsertObject: newObject\n'
            '\t\tat: index + 1'
        )

    @scenario
    def hand_placed_alignment_normalised(self):
        """AI: Hand-placed continuation alignment is not preserved — the formatter
        re-indents to canonical receiver-at-L, keywords-at-L+1 style."""
        self.source = (
            'findPattern: aPattern startingAt: anIndex\n'
            '\n'
            '"Searches the receiver."\n'
            '\n'
            '^self\n'
            '    indexOf: aPattern\n'
            '    matchCase: true\n'
            '    startingAt: anIndex\n'
        )
        self.expected = (
            'findPattern: aPattern startingAt: anIndex\n'
            '\t"Searches the receiver."\n'
            '\n'
            '\t^ self\n'
            '\t\tindexOf: aPattern\n'
            '\t\tmatchCase: true\n'
            '\t\tstartingAt: anIndex'
        )

    @scenario
    def block_with_arg_is_inline_when_short(self):
        """AI: A block with one argument and one simple unary statement is short and
        is formatted inline as [ :arg | body ] on the keyword send line."""
        self.source = 'doAll\n    aCollection do: [:each |\n        each process].\n    ^self'
        self.expected = 'doAll\n\taCollection do: [ :each | each process ].\n\t^ self'

    @scenario
    def trailing_comment_has_no_blank_line_before_it(self):
        """AI: A comment after the last statement (trailing, e.g. commented-out code)
        sits flush against that statement — no blank line is inserted before it."""
        self.source = 'checkValue\n\tself validate.\n\t^ self isValid\n\t"TODO: verify invariants"'
        self.expected = 'checkValue\n\tself validate.\n\t^ self isValid\n\t"TODO: verify invariants"'

    @scenario
    def keyword_receiver_forces_multiline_for_single_keyword_send(self):
        """AI: A 1-keyword send whose receiver is itself a keyword send is always formatted
        multi-line (parenthesised receiver at depth, keyword at depth+1).
        This is the canonical Wonka pattern for guard conditions: (a or: [b]) ifTrue: [c]."""
        self.source = (
            'guarded\n'
            '    (fromAccount isSupplierAccount or: [ toAccount isSupplierAccount ]) ifTrue: [ self signalError ]'
        )
        self.expected = (
            'guarded\n'
            '\t(fromAccount isSupplierAccount or: [ toAccount isSupplierAccount ])\n'
            '\t\tifTrue: [ self signalError ]'
        )


@with_fixtures(FormatterScenarios)
def test_formatter_normalises_body_indentation(scenario):
    """AI: The formatter normalises all source to canonical GemStone/Wonka 1-tab style,
    splitting multi-keyword sends, inlining short blocks, and placing ^ with a space."""
    result = SmalltalkMethodFormat().format_method(scenario.source)
    assert result == scenario.expected


def test_formatter_returns_original_source_on_parse_error():
    """AI: If the source does not parse as a valid method, the formatter returns it unchanged
    so that a save with auto_format on does not destroy content the user is still editing."""
    invalid_source = 'not valid smalltalk ??? [['
    result = SmalltalkMethodFormat().format_method(invalid_source)
    assert result == invalid_source


def test_formatter_is_idempotent():
    """AI: Running the formatter twice produces the same result — a user who saves
    repeatedly does not accumulate more whitespace changes on each save."""
    source = 'compute\n    | x |\n    x := 3.\n    ^x + 1'
    first_pass = SmalltalkMethodFormat().format_method(source)
    second_pass = SmalltalkMethodFormat().format_method(first_pass)
    assert first_pass == second_pass


def test_formatter_is_idempotent_on_canonical_source():
    """AI: A method already written in canonical Wonka style — cascade with mixed
    unary/keyword messages, receiver on opener line — passes through the formatter unchanged."""
    source = (
        'checkHistoricalInvariantsWithCurrent: current\n'
        '\tself\n'
        '\t\tassert: self class == current class;\n'
        '\t\tcheckReferencedObject.\n'
        '\t^ self isValid'
    )
    result = SmalltalkMethodFormat().format_method(source)
    assert result == source


class AutoFormatConfigScenarios(Fixture):
    """AI: Maps config payloads to the boolean the loader should produce."""

    @scenario
    def no_config(self):
        """AI: When there is no config file, auto_format defaults to False — formatting is opt-in."""
        self.config_payload = None
        self.expected = False

    @scenario
    def enabled(self):
        """AI: appearance.auto_format: true explicitly enables auto-formatting."""
        self.config_payload = {'appearance': {'auto_format': True}}
        self.expected = True

    @scenario
    def disabled(self):
        """AI: appearance.auto_format: false keeps auto-formatting off (same as default)."""
        self.config_payload = {'appearance': {'auto_format': False}}
        self.expected = False

    @scenario
    def no_auto_format_key(self):
        """AI: An appearance section without auto_format defaults to False."""
        self.config_payload = {'appearance': {'theme': 'dark'}}
        self.expected = False

    @scenario
    def invalid_integer(self):
        """AI: A JSON integer (1 or 0) is not a Python bool and falls back to False."""
        self.config_payload = {'appearance': {'auto_format': 1}}
        self.expected = False

    @scenario
    def invalid_string(self):
        """AI: A string like 'true' is not a bool and falls back to False."""
        self.config_payload = {'appearance': {'auto_format': 'true'}}
        self.expected = False


@with_fixtures(AutoFormatConfigScenarios)
def test_auto_format_loaded_from_appearance_config(scenario):
    """AI: appearance.auto_format is read as a strict bool; any other type falls back to False
    so a misconfigured value never silently forces auto-formatting on."""
    store = McpConfigurationStore()
    with patch.object(
        McpConfigurationStore, 'config_payload', return_value=scenario.config_payload
    ):
        assert store.load_auto_format() == scenario.expected


def test_save_with_auto_format_on_passes_formatted_source_to_gemstone():
    """AI: When auto_format is enabled, EditorTab.save() formats the method source before
    passing it to update_method_source, so GemStone stores the normalised version."""
    root = tk.Tk()
    root.withdraw()
    try:
        session_record = Mock()
        session_record.get_method.return_value = None
        app = types.SimpleNamespace(
            auto_format=True,
            tab_spacing=4,
            integrated_session_state=types.SimpleNamespace(is_mcp_busy=lambda: False),
            debugger_tab=None,
            experimental_features_enabled=False,
            event_queue=Mock(),
            gemstone_session_record=session_record,
        )
        tab_key = ('MyClass', True, 'myMethod')
        editor_tab = EditorTab(root, app, Mock(), tab_key)
        editor_tab.code_panel.text_editor.insert('1.0', 'myMethod\n    ^42')

        editor_tab.save()

        source_saved = session_record.update_method_source.call_args[0][3]
        assert source_saved == 'myMethod\n\t^ 42'
    finally:
        root.destroy()


def test_save_with_auto_format_off_passes_source_unchanged():
    """AI: When auto_format is disabled, save() passes the source to GemStone exactly as typed —
    the checkbox is purely opt-in and never silently modifies user input."""
    root = tk.Tk()
    root.withdraw()
    try:
        session_record = Mock()
        session_record.get_method.return_value = None
        app = types.SimpleNamespace(
            auto_format=False,
            tab_spacing=4,
            integrated_session_state=types.SimpleNamespace(is_mcp_busy=lambda: False),
            debugger_tab=None,
            experimental_features_enabled=False,
            event_queue=Mock(),
            gemstone_session_record=session_record,
        )
        tab_key = ('MyClass', True, 'myMethod')
        unformatted_source = 'myMethod\n    ^42'
        editor_tab = EditorTab(root, app, Mock(), tab_key)
        editor_tab.code_panel.text_editor.insert('1.0', unformatted_source)

        editor_tab.save()

        source_saved = session_record.update_method_source.call_args[0][3]
        assert source_saved == unformatted_source
    finally:
        root.destroy()
