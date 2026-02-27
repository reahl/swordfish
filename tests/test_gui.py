import tkinter as tk
import types
from tkinter import ttk
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

from reahl.ptongue import GemstoneError
from reahl.tofu import Fixture
from reahl.tofu import NoException
from reahl.tofu import expected
from reahl.tofu import set_up
from reahl.tofu import tear_down
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.mcp.integration_state import IntegratedSessionState
from reahl.swordfish.main import BrowserWindow
from reahl.swordfish.main import DomainException
from reahl.swordfish.main import EventQueue
from reahl.swordfish.main import Explorer
from reahl.swordfish.main import FindDialog
from reahl.swordfish.main import GemstoneSessionRecord
from reahl.swordfish.main import InspectorTab
from reahl.swordfish.main import ObjectInspector
from reahl.swordfish.main import run_application
from reahl.swordfish.main import run_mcp_server
from reahl.swordfish.main import SendersDialog
from reahl.swordfish.main import Swordfish


class FakeApplication:
    """AI: Thin stand-in for Swordfish that supplies the two attributes BrowserWindow needs."""

    def __init__(self, event_queue, gemstone_session_record):
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record
        self.integrated_session_state = IntegratedSessionState()

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        if self.gemstone_session_record.gemstone_session is not None:
            self.gemstone_session_record.jump_to_method(
                class_name,
                show_instance_side,
                method_symbol,
            )
        else:
            selected_method_category = (
                self.gemstone_session_record.gemstone_browser_session.get_method_category(
                    class_name,
                    method_symbol,
                    show_instance_side,
                )
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(class_name)
            self.gemstone_session_record.select_method_category(
                selected_method_category
            )
            self.gemstone_session_record.select_method_symbol(method_symbol)
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')


class SwordfishGuiFixture(Fixture):
    @set_up
    def create_app(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        self.mock_browser.list_packages.return_value = ['Kernel', 'Collections']
        self.mock_browser.list_classes.return_value = ['OrderLine', 'Order']
        self.mock_browser.list_method_categories.return_value = ['accessing', 'testing']
        self.mock_browser.list_methods.return_value = ['total', 'description']
        self.mock_browser.get_method_category.return_value = 'accessing'
        class_definitions = {
            'OrderLine': {
                'class_name': 'OrderLine',
                'superclass_name': 'Order',
                'package_name': 'Kernel',
                'inst_var_names': ['amount', 'quantity'],
                'class_var_names': [],
                'class_inst_var_names': [],
                'pool_dictionary_names': [],
            },
            'Order': {
                'class_name': 'Order',
                'superclass_name': 'Object',
                'package_name': 'Kernel',
                'inst_var_names': ['lines'],
                'class_var_names': [],
                'class_inst_var_names': [],
                'pool_dictionary_names': [],
            },
            'Object': {
                'class_name': 'Object',
                'superclass_name': None,
                'package_name': 'Kernel',
                'inst_var_names': [],
                'class_var_names': [],
                'class_inst_var_names': [],
                'pool_dictionary_names': [],
            },
        }

        def get_class_definition(class_name):
            class_definition = class_definitions.get(class_name)
            if class_definition is None:
                raise GemstoneDomainException('Unknown class_name.')
            return class_definition

        self.mock_browser.get_class_definition.side_effect = get_class_definition

        # AI: get_compiled_method returns an object whose sourceString() method
        # returns an object with a .to_py attribute (the raw Smalltalk source string).
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = 'total\n    ^amount * quantity'
        self.mock_browser.get_compiled_method.return_value = mock_method

        # AI: Pass None for the gemstone session; GemstoneSessionRecord.__init__
        # wraps it in GemstoneBrowserSession which only stores it.  We then replace
        # gemstone_browser_session with the mock before any real calls are made.
        self.session_record = GemstoneSessionRecord(None)
        self.session_record.gemstone_browser_session = self.mock_browser

        self.event_queue = EventQueue(self.root)
        self.application = FakeApplication(self.event_queue, self.session_record)
        self.browser_window = BrowserWindow(self.root, self.application)
        self.root.update()

        # AI: Clear call counts accumulated during widget initialisation so that
        # individual tests start from a clean slate.
        self.mock_browser.reset_mock()

    @tear_down
    def destroy_app(self):
        self.root.destroy()

    def select_in_listbox(self, listbox, item):
        """AI: Simulate a user clicking on an item in a Listbox.

        Calls handle_selection directly on the InteractiveSelectionList
        (listbox.master) rather than using event_generate, because the
        two-level event cascade (<<ListboxSelect>> -> <<CustomEventsPublished>>)
        is not reliably flushed in a single root.update() under Xvfb.
        root.update() still drains the single-level custom-event queue that
        the selection handler itself enqueues.
        """
        items = listbox.get(0, 'end')
        idx = list(items).index(item)
        listbox.selection_clear(0, 'end')
        listbox.selection_set(idx)
        selection_list = listbox.master  # AI: listbox is a direct child of InteractiveSelectionList
        selection_list.handle_selection(types.SimpleNamespace(widget=listbox))
        self.root.update()

    def select_down_to_method(self, package, class_name, category, method):
        """AI: Navigate all four selection columns to open an editor tab for a method."""
        self.select_in_listbox(
            self.browser_window.packages_widget.selection_list.selection_listbox,
            package,
        )
        self.select_in_listbox(
            self.browser_window.classes_widget.selection_list.selection_listbox,
            class_name,
        )
        self.select_in_listbox(
            self.browser_window.categories_widget.selection_list.selection_listbox,
            category,
        )
        self.select_in_listbox(
            self.browser_window.methods_widget.selection_list.selection_listbox,
            method,
        )

    def open_text_context_menu_for_tab(self, tab):
        menu_event = types.SimpleNamespace(
            x=1,
            y=1,
            x_root=1,
            y_root=1,
        )
        tab.code_panel.open_text_menu(menu_event)
        self.root.update()
        return tab.code_panel.current_context_menu

    def invoke_menu_command(self, menu, label):
        entry_count = int(menu.index('end')) + 1
        for entry_index in range(entry_count):
            if menu.type(entry_index) != 'command':
                continue
            if menu.entrycget(entry_index, 'label') == label:
                menu.invoke(entry_index)
                self.root.update()
                return
        raise AssertionError(f'Menu command not found: {label}')

    def selected_listbox_entry(self, listbox):
        selected_index = listbox.curselection()[0]
        return listbox.get(selected_index)


def menu_command_labels(menu):
    labels = []
    entry_count = int(menu.index('end')) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) == 'command':
            labels.append(menu.entrycget(entry_index, 'label'))
    return labels


def invoke_menu_command_by_label(menu, label):
    entry_count = int(menu.index('end')) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) != 'command':
            continue
        if menu.entrycget(entry_index, 'label') == label:
            menu.invoke(entry_index)
            return
    raise AssertionError(f'Menu command not found: {label}')


@with_fixtures(SwordfishGuiFixture)
def test_selecting_package_fetches_and_shows_classes(fixture):
    """Selecting a package causes GemstoneBrowserSession to fetch classes
    for that package and populates the class listbox with the results."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )

    fixture.mock_browser.list_classes.assert_called_with('Kernel')
    class_listbox = fixture.browser_window.classes_widget.selection_list.selection_listbox
    assert list(class_listbox.get(0, 'end')) == ['OrderLine', 'Order']


@with_fixtures(SwordfishGuiFixture)
def test_add_package_creates_installs_and_selects_package(fixture):
    """AI: Adding a package from the package pane should create/install it and select it in the package list."""
    fixture.mock_browser.list_packages.return_value = [
        'Kernel',
        'Collections',
        'Stuff',
    ]

    with patch('reahl.swordfish.main.simpledialog.askstring', return_value='Stuff'):
        fixture.browser_window.packages_widget.add_package()
        fixture.root.update()

    fixture.mock_browser.create_and_install_package.assert_called_with('Stuff')
    assert fixture.session_record.selected_package == 'Stuff'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.packages_widget.selection_list.selection_listbox
    ) == 'Stuff'


@with_fixtures(SwordfishGuiFixture)
def test_delete_package_removes_selected_package_and_clears_selection(fixture):
    """AI: Deleting a selected package should invoke browser deletion and clear package/class/method selection."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.mock_browser.list_packages.return_value = ['Collections']

    with patch('reahl.swordfish.main.messagebox.askyesno', return_value=True):
        fixture.browser_window.packages_widget.delete_package()
        fixture.root.update()

    fixture.mock_browser.delete_package.assert_called_once_with('Kernel')
    assert fixture.session_record.selected_package is None
    assert fixture.session_record.selected_class is None
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.packages_widget.selection_list.selection_listbox.get(
            0,
            'end',
        )
    ) == ['Collections']


@with_fixtures(SwordfishGuiFixture)
def test_add_class_creates_in_selected_package_and_selects_it(fixture):
    """AI: Adding a class from the class pane should create it in the selected package and make it the selected class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.mock_browser.list_classes.return_value = ['OrderLine', 'Order', 'Invoice']

    with patch(
        'reahl.swordfish.main.simpledialog.askstring',
        side_effect=['Invoice', 'Object'],
    ):
        fixture.browser_window.classes_widget.add_class()
        fixture.root.update()

    fixture.mock_browser.create_class.assert_called_with(
        class_name='Invoice',
        superclass_name='Object',
        in_dictionary='Kernel',
    )
    assert fixture.session_record.selected_class == 'Invoice'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    ) == 'Invoice'


@with_fixtures(SwordfishGuiFixture)
def test_delete_class_removes_selected_class_and_clears_method_selection(fixture):
    """AI: Deleting a selected class should remove it from the package and clear class/method selection state."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'OrderLine',
    )
    fixture.mock_browser.list_classes.return_value = ['Order']

    with patch('reahl.swordfish.main.messagebox.askyesno', return_value=True):
        fixture.browser_window.classes_widget.delete_class()
        fixture.root.update()

    fixture.mock_browser.delete_class.assert_called_once_with(
        'OrderLine',
        in_dictionary='Kernel',
    )
    assert fixture.session_record.selected_class is None
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.classes_widget.selection_list.selection_listbox.get(
            0,
            'end',
        )
    ) == ['Order']


@with_fixtures(SwordfishGuiFixture)
def test_add_method_compiles_template_in_as_yet_unclassified_and_opens_tab(fixture):
    """AI: Adding a method compiles a starter template in as yet unclassified and opens that method in the editor."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'OrderLine',
    )
    fixture.mock_browser.list_method_categories.return_value = [
        'accessing',
        'testing',
        'as yet unclassified',
    ]

    with patch(
        'reahl.swordfish.main.simpledialog.askstring',
        return_value='calculateTotal',
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        'OrderLine',
        True,
        'calculateTotal\n    ^self',
        method_category='as yet unclassified',
    )
    assert fixture.session_record.selected_method_category == 'as yet unclassified'
    assert fixture.session_record.selected_method_symbol == 'calculateTotal'
    assert (
        'OrderLine',
        True,
        'calculateTotal',
    ) in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_add_method_generates_keyword_template_argument_names(fixture):
    """AI: Keyword selectors are prepopulated with argument placeholders so the generated method source compiles."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'OrderLine',
    )
    fixture.mock_browser.list_method_categories.return_value = [
        'accessing',
        'testing',
        'as yet unclassified',
    ]

    with patch(
        'reahl.swordfish.main.simpledialog.askstring',
        return_value='copyFrom:to:',
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        'OrderLine',
        True,
        'copyFrom: argument1 to: argument2\n    ^self',
        method_category='as yet unclassified',
    )


@with_fixtures(SwordfishGuiFixture)
def test_delete_method_removes_selected_method_from_class(fixture):
    """AI: Deleting a selected method should remove it from the class and clear selected method state."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.list_methods.return_value = ['description']

    with patch('reahl.swordfish.main.messagebox.askyesno', return_value=True):
        fixture.browser_window.methods_widget.delete_method()
        fixture.root.update()

    fixture.mock_browser.delete_method.assert_called_once_with(
        'OrderLine',
        'total',
        True,
    )
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            'end',
        )
    ) == ['description']


@with_fixtures(SwordfishGuiFixture)
def test_selecting_method_opens_editor_tab(fixture):
    """Choosing a method from the method list opens a new editor tab
    containing that method's source code."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 1
    tab_text = notebook.tab(notebook.tabs()[0], 'text')
    assert tab_text == 'total'


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_source_shows_line_numbers(fixture):
    """AI: Method source editors display a synchronized line-number column."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        '1.0',
        'end-1c',
    ).splitlines()
    assert line_numbers[:2] == ['1', '2']

    tab.code_panel.text_editor.insert('end', '\n    ^42')
    fixture.root.update()

    updated_line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        '1.0',
        'end-1c',
    ).splitlines()
    assert updated_line_numbers[:3] == ['1', '2', '3']
    tab.code_panel.text_editor.mark_set(tk.INSERT, '2.4')
    tab.code_panel.cursor_position_indicator.update_position()
    assert tab.code_panel.cursor_position_label.cget('text') == 'Ln 2, Col 5'


@with_fixtures(SwordfishGuiFixture)
def test_selecting_already_open_method_brings_its_tab_to_fore(fixture):
    """Re-selecting a method that already has an open tab switches to that
    tab rather than opening a duplicate."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'description')
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 2
    selected_tab = notebook.select()
    assert notebook.tab(selected_tab, 'text') == 'total'


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_back_and_forward_navigate_method_history(fixture):
    """AI: Back and Forward should move through the selected-method trail like browser navigation."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'description')

    editor = fixture.browser_window.editor_area_widget
    editor.back_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == 'total'
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, 'text') == 'total'

    editor.forward_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == 'description'
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, 'text') == 'description'


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_history_list_jumps_to_selected_entry(fixture):
    """AI: Choosing an entry in method history should jump directly to that earlier method."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'description')

    editor = fixture.browser_window.editor_area_widget
    history_values = editor.history_combobox.cget('values')
    matching_indices = [
        index
        for index, value in enumerate(history_values)
        if 'OrderLine>>total' in value
    ]
    target_index = matching_indices[0]

    editor.history_combobox.current(target_index)
    editor.history_combobox.event_generate('<<ComboboxSelected>>')
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == 'total'
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, 'text') == 'total'


@with_fixtures(SwordfishGuiFixture)
def test_saving_method_compiles_to_gemstone(fixture):
    """Saving an open editor tab sends the current source to GemstoneBrowserSession
    for compilation."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.delete('1.0', 'end')
    tab.code_panel.text_editor.insert('1.0', 'total\n    ^42')
    tab.save()

    fixture.mock_browser.compile_method.assert_called_with('OrderLine', True, 'total\n    ^42')


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_save_and_close_for_open_tab(fixture):
    """AI: Right-clicking in an editor text area exposes Save and Close actions for the current tab."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert 'Jump to Class' in command_labels
    assert 'Save' in command_labels
    assert 'Close' in command_labels
    assert 'Select All' in command_labels
    assert 'Copy' in command_labels
    assert 'Paste' in command_labels
    assert 'Undo' in command_labels
    assert 'Preview Rename Method' not in command_labels
    assert 'Preview Move Method' not in command_labels
    assert 'Preview Add Parameter' not in command_labels
    assert 'Preview Remove Parameter' not in command_labels
    assert 'Preview Extract Method' not in command_labels
    assert 'Preview Inline Method' not in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_save_command_from_text_context_menu_compiles_to_gemstone(fixture):
    """AI: Choosing Save from text context menu compiles the current editor contents."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.delete('1.0', 'end')
    tab.code_panel.text_editor.insert('1.0', 'total\n    ^99')

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, 'Save')

    fixture.mock_browser.compile_method.assert_called_with('OrderLine', True, 'total\n    ^99')


@with_fixtures(SwordfishGuiFixture)
def test_close_command_from_text_context_menu_closes_the_tab(fixture):
    """AI: Choosing Close from text context menu removes the current method tab."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, 'Close')

    assert ('OrderLine', True, 'total') not in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_jump_to_class_command_from_text_context_menu_syncs_browser_selection(
    fixture,
):
    """AI: Choosing Jump to Class from a method tab synchronizes package/class/side/category/method browser selections to that method context."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    fixture.browser_window.classes_widget.selection_var.set('class')
    fixture.root.update()
    assert fixture.browser_window.classes_widget.selection_var.get() == 'class'

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, 'Jump to Class')

    assert fixture.session_record.selected_package == 'Kernel'
    assert fixture.session_record.selected_class == 'OrderLine'
    assert fixture.session_record.show_instance_side is True
    assert fixture.session_record.selected_method_category == 'accessing'
    assert fixture.session_record.selected_method_symbol == 'total'
    assert fixture.browser_window.classes_widget.selection_var.get() == 'instance'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.packages_widget.selection_list.selection_listbox
    ) == 'Kernel'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    ) == 'OrderLine'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.categories_widget.selection_list.selection_listbox
    ) == 'accessing'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.methods_widget.selection_list.selection_listbox
    ) == 'total'


@with_fixtures(SwordfishGuiFixture)
def test_text_editor_context_menu_paste_replaces_selected_text_and_undo_restores_it(
    fixture,
):
    """Pasting from the editor context menu replaces selected text and Undo restores the previous source."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.delete('1.0', 'end')
    tab.code_panel.text_editor.insert('1.0', 'alpha beta')
    tab.code_panel.text_editor.tag_add(tk.SEL, '1.6', '1.10')

    fixture.root.clipboard_clear()
    fixture.root.clipboard_append('gamma')

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, 'Paste')
    assert tab.code_panel.text_editor.get('1.0', 'end-1c') == 'alpha gamma'

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, 'Undo')
    assert tab.code_panel.text_editor.get('1.0', 'end-1c') == 'alpha beta'

    tab.code_panel.text_editor.tag_add(tk.SEL, '1.6', '1.10')
    tab.code_panel.replace_selected_text_editor_before_typing(
        types.SimpleNamespace(state=0, char='q', keysym='q'),
    )
    tab.code_panel.text_editor.insert(tk.INSERT, 'q')
    assert tab.code_panel.text_editor.get('1.0', 'end-1c') == 'alpha q'


@with_fixtures(SwordfishGuiFixture)
def test_selector_for_navigation_uses_full_keyword_selector_from_selected_send_fragment(
    fixture,
):
    """AI: Selecting a keyword send fragment with arguments should resolve to the full keyword selector token sequence."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.delete('1.0', 'end')
    tab.code_panel.text_editor.insert(
        '1.0',
        'total\n'
        '    ^self _twoArgInstPrim: 4 with: srcByteObj with: destByteObj',
    )
    selection_start = tab.code_panel.text_editor.search(
        '_twoArgInstPrim:',
        '1.0',
        stopindex='end',
    )
    selection_end = tab.code_panel.text_editor.search(
        'destByteObj',
        '1.0',
        stopindex='end',
    )
    tab.code_panel.text_editor.tag_add(
        tk.SEL,
        selection_start,
        selection_end,
    )

    resolved_selector = tab.code_panel.selector_for_navigation()

    assert resolved_selector == '_twoArgInstPrim:with:with:'


@with_fixtures(SwordfishGuiFixture)
def test_opening_hierarchy_tab_builds_and_expands_tree_for_selected_class(fixture):
    """AI: Switching to hierarchy view should show superclass/child structure and expand to the selected class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'OrderLine',
    )

    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, 'text') == expected_text:
                return child_item_id
        raise AssertionError(
            f'Could not find {expected_text} under {parent_item}.',
        )

    object_item = child_with_text('', 'Object')
    order_item = child_with_text(object_item, 'Order')
    order_line_item = child_with_text(order_item, 'OrderLine')

    assert tree.selection() == (order_line_item,)
    assert tree.item(object_item, 'open')
    assert tree.item(order_item, 'open')
    assert tree.set(order_line_item, 'class_category') == 'Kernel'


@with_fixtures(SwordfishGuiFixture)
def test_selecting_class_in_hierarchy_selects_default_category_and_refreshes_methods(
    fixture,
):
    """AI: Selecting a class in hierarchy view should auto-select a method category and refresh method views."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, 'text') == expected_text:
                return child_item_id
        raise AssertionError(
            f'Could not find {expected_text} under {parent_item}.',
        )

    object_item = child_with_text('', 'Object')
    order_item = child_with_text(object_item, 'Order')
    child_with_text(order_item, 'OrderLine')
    classes_widget.select_class(
        'OrderLine',
        selection_source='hierarchy',
        class_category='Kernel',
    )
    fixture.root.update()

    assert fixture.session_record.selected_class == 'OrderLine'
    assert fixture.session_record.selected_method_category == 'all'
    assert fixture.selected_listbox_entry(
        fixture.browser_window.categories_widget.selection_list.selection_listbox,
    ) == 'all'
    method_entries = list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            'end',
        )
    )
    assert method_entries == ['total', 'description']


@with_fixtures(SwordfishGuiFixture)
def test_show_class_definition_displays_and_updates_for_selected_class(fixture):
    """AI: Enabling class definition view should render the selected class definition and refresh when selection changes."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'OrderLine',
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.show_class_definition_var.set(True)
    classes_widget.toggle_class_definition()
    fixture.root.update()

    rendered_definition = classes_widget.class_definition_text.get(
        '1.0',
        'end',
    ).strip()
    rendered_line_numbers = (
        classes_widget.class_definition_line_number_column.line_numbers_text.get(
            '1.0',
            'end-1c',
        ).splitlines()
    )
    assert rendered_line_numbers[:3] == ['1', '2', '3']
    classes_widget.class_definition_text.mark_set(tk.INSERT, '2.3')
    classes_widget.class_definition_cursor_position_indicator.update_position()
    assert (
        classes_widget.class_definition_cursor_position_label.cget('text')
        == 'Ln 2, Col 4'
    )
    assert "Order subclass: 'OrderLine'" in rendered_definition
    assert 'instVarNames: #(amount quantity)' in rendered_definition
    assert 'inDictionary: Kernel' in rendered_definition

    fixture.browser_window.classes_widget.selection_list.selection_listbox.selection_clear(
        0,
        'end',
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        'Order',
    )
    fixture.root.update()
    updated_definition = classes_widget.class_definition_text.get(
        '1.0',
        'end',
    ).strip()
    assert "Object subclass: 'Order'" in updated_definition
    assert 'instVarNames: #(lines)' in updated_definition


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_checkbox_shows_class_hierarchy(fixture):
    """AI: Enabling method inheritance view should show the selected method's superclass chain as class names only."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    assert fixture.session_record.selected_method_symbol == 'total'
    method_hierarchy_tree = methods_widget.method_hierarchy_tree
    root_item_ids = method_hierarchy_tree.get_children('')
    assert len(root_item_ids) == 1
    assert method_hierarchy_tree.item(root_item_ids[0], 'text') == 'Object'
    fixture.root.update()

    tree = methods_widget.method_hierarchy_tree
    root_item_ids = tree.get_children('')
    assert len(root_item_ids) == 1
    object_item = root_item_ids[0]
    order_item_ids = tree.get_children(object_item)
    assert len(order_item_ids) == 1
    order_item = order_item_ids[0]
    order_line_item_ids = tree.get_children(order_item)
    assert len(order_line_item_ids) == 1
    order_line_item = order_line_item_ids[0]

    assert tree.item(object_item, 'text') == 'Object'
    assert tree.item(order_item, 'text') == 'Order'
    assert tree.item(order_line_item, 'text') == 'OrderLine'
    assert tree.selection() == (order_line_item,)


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_hierarchy_refreshes_on_method_selection_change(fixture):
    """AI: Selecting a different method in the methods list should immediately refresh inheritance analysis for the new selector."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.mock_browser.get_compiled_method.reset_mock()

    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, 'end')
    fixture.select_in_listbox(
        methods_listbox,
        'description',
    )

    expected_calls = [
        call('Object', 'description', True),
        call('Order', 'description', True),
        call('OrderLine', 'description', True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_updates_after_explicit_method_click_from_hierarchy_class_view(
    fixture,
):
    """AI: With class selected from hierarchy view and no method selected, clicking a method should refresh method inheritance for that method."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        'Kernel',
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    classes_widget.select_class(
        'OrderLine',
        selection_source='hierarchy',
        class_category='Kernel',
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol is None
    assert fixture.session_record.selected_method_category == 'all'

    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    assert not methods_widget.method_hierarchy_tree.get_children('')

    fixture.mock_browser.get_compiled_method.reset_mock()
    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, 'end')
    fixture.select_in_listbox(
        methods_listbox,
        'total',
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == 'total'
    expected_calls = [
        call('Object', 'total', True),
        call('Order', 'total', True),
        call('OrderLine', 'total', True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)
    assert methods_widget.method_hierarchy_tree.get_children('')


@with_fixtures(SwordfishGuiFixture)
def test_browser_window_has_four_selection_columns(fixture):
    """The browser window contains exactly four selection column widgets:
    packages, classes, categories, and methods."""
    children = fixture.browser_window.top_frame.winfo_children()
    assert len(children) == 4


@with_fixtures(SwordfishGuiFixture)
def test_switching_side_clears_selected_category(fixture):
    """Switching between Instance and Class side resets the selected category
    so the method list does not try to fetch methods for a category that only
    exists on the old side."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    assert fixture.session_record.selected_method_category == 'accessing'

    fixture.browser_window.classes_widget.switch_side()
    fixture.root.update()

    assert fixture.session_record.selected_method_category is None


class FakeGemstoneError(GemstoneError):
    """AI: Minimal GemstoneError for testing — bypasses the real constructor
    which requires an active session and a C error structure."""

    def __init__(self):
        pass

    def __str__(self):
        return 'AI: Simulated Smalltalk error'

    @property
    def context(self):
        return None


class FakeCompileGemstoneError(GemstoneError):
    """AI: Minimal compile error carrying GemStone-like structured arguments."""

    def __init__(self, source_text, source_offset):
        self.source_text = source_text
        self.source_offset = source_offset

    def __str__(self):
        return 'a CompileError occurred (error 1001), unexpected token'

    @property
    def number(self):
        return 1001

    @property
    def args(self):
        return ([[1034, self.source_offset, 'unexpected token']], self.source_text)

    @property
    def context(self):
        return None


class SwordfishAppFixture(Fixture):
    @set_up
    def create_app(self):
        self.mock_gemstone_session = Mock()
        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        self.mock_browser.list_packages.return_value = ['Kernel', 'Collections']
        self.mock_browser.list_classes.return_value = ['OrderLine', 'Order']
        self.mock_browser.list_method_categories.return_value = ['accessing']
        self.mock_browser.list_methods.return_value = ['total']
        self.mock_browser.get_method_category.return_value = 'accessing'

        # AI: Chained mock for EditorTab.repopulate() which calls
        # get_compiled_method().sourceString().to_py
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = 'total\n    ^1'
        self.mock_browser.get_compiled_method.return_value = mock_method

        # AI: Bypass GemstoneSessionRecord.__init__ (which opens a live GemStone
        # connection) by using __new__ and manually setting all instance variables.
        self.session_record = GemstoneSessionRecord.__new__(GemstoneSessionRecord)
        self.session_record.gemstone_session = self.mock_gemstone_session
        self.session_record.gemstone_browser_session = self.mock_browser
        self.session_record.selected_package = None
        self.session_record.selected_class = None
        self.session_record.selected_method_category = None
        self.session_record.selected_method_symbol = None
        self.session_record.show_instance_side = True

        self.app = Swordfish()
        self.app.withdraw()
        self.app.update()

    @tear_down
    def destroy_app(self):
        self.app.destroy()

    def simulate_login(self):
        """AI: Publish LoggedInSuccessfully to transition the app to the
        browser interface without going through the real login dialog."""
        self.app.event_queue.publish('LoggedInSuccessfully', self.session_record)
        self.app.update()
        self.mock_browser.reset_mock()


@with_fixtures(SwordfishAppFixture)
def test_successful_login_switches_to_browser_interface(fixture):
    """Providing valid credentials causes the app to transition from the
    login screen to the main browser interface with a notebook visible."""
    with patch.object(GemstoneSessionRecord, 'log_in_linked', return_value=fixture.session_record):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert fixture.app.is_logged_in
    assert fixture.app.notebook is not None


@with_fixtures(SwordfishAppFixture)
def test_login_screen_defaults_stone_name_to_gs64stone(fixture):
    """AI: The login screen should prefill stone name with gs64stone when no CLI argument is supplied."""
    assert fixture.app.login_frame.stone_name_entry.get() == 'gs64stone'


@with_fixtures(SwordfishAppFixture)
def test_swordfish_custom_default_stone_name_prefills_login_field(fixture):
    """AI: A configured default stone name should be shown in the login screen stone field."""
    custom_app = Swordfish(default_stone_name='customStone')
    custom_app.withdraw()
    custom_app.update()
    assert custom_app.login_frame.stone_name_entry.get() == 'customStone'
    custom_app.destroy()


def test_run_application_uses_default_stone_name_when_arg_not_given():
    """AI: run_application should construct Swordfish with gs64stone by default and start embedded MCP."""
    with patch('reahl.swordfish.main.Swordfish') as mock_swordfish:
        app_instance = Mock()
        mock_swordfish.return_value = app_instance
        with patch('sys.argv', ['swordfish']):
            run_application()
        mock_swordfish.assert_called_once()
        swordfish_call_arguments = mock_swordfish.call_args.kwargs
        assert swordfish_call_arguments['default_stone_name'] == 'gs64stone'
        assert swordfish_call_arguments['start_embedded_mcp']
        assert swordfish_call_arguments['mcp_runtime_config'].mcp_host == '127.0.0.1'
        app_instance.mainloop.assert_called_once()


def test_run_application_uses_cli_stone_name_when_given():
    """AI: run_application should pass an explicitly provided stone name into Swordfish with embedded MCP enabled."""
    with patch('reahl.swordfish.main.Swordfish') as mock_swordfish:
        app_instance = Mock()
        mock_swordfish.return_value = app_instance
        with patch('sys.argv', ['swordfish', 'myStone']):
            run_application()
        mock_swordfish.assert_called_once()
        swordfish_call_arguments = mock_swordfish.call_args.kwargs
        assert swordfish_call_arguments['default_stone_name'] == 'myStone'
        assert swordfish_call_arguments['start_embedded_mcp']
        app_instance.mainloop.assert_called_once()


def test_run_application_starts_headless_mcp_when_headless_flag_is_set():
    """AI: --headless-mcp should run only the MCP server and not construct the GUI."""
    with patch('reahl.swordfish.main.Swordfish') as mock_swordfish:
        with patch('reahl.swordfish.main.run_mcp_server') as mock_run_mcp_server:
            with patch('sys.argv', ['swordfish', '--headless-mcp']):
                run_application()
    mock_swordfish.assert_not_called()
    mock_run_mcp_server.assert_called_once()


def test_run_application_passes_streamable_http_configuration_to_mcp():
    """AI: headless mode should pass streamable-http host/port/path options into MCP startup arguments."""
    with patch('reahl.swordfish.main.Swordfish') as mock_swordfish:
        with patch('reahl.swordfish.main.run_mcp_server') as mock_run_mcp_server:
            with patch(
                'sys.argv',
                [
                    'swordfish',
                    '--headless-mcp',
                    '--transport',
                    'streamable-http',
                    '--mcp-host',
                    '127.0.0.1',
                    '--mcp-port',
                    '9177',
                    '--mcp-http-path',
                    '/running-ide',
                ],
            ):
                run_application()
    mock_swordfish.assert_not_called()
    application_arguments = mock_run_mcp_server.call_args.args[0]
    assert application_arguments.transport == 'streamable-http'
    assert application_arguments.mcp_host == '127.0.0.1'
    assert application_arguments.mcp_port == 9177
    assert application_arguments.mcp_http_path == '/running-ide'


def test_run_application_supports_legacy_headless_mode_argument():
    """AI: Legacy --mode mcp-headless still maps to headless MCP startup."""
    with patch('reahl.swordfish.main.Swordfish') as mock_swordfish:
        with patch('reahl.swordfish.main.run_mcp_server') as mock_run_mcp_server:
            with patch('sys.argv', ['swordfish', '--mode', 'mcp-headless']):
                run_application()
    mock_swordfish.assert_not_called()
    mock_run_mcp_server.assert_called_once()


def test_run_mcp_server_passes_streamable_http_options_to_create_server():
    """AI: MCP startup should forward host/port/path options to create_server and run with the requested transport."""
    arguments = types.SimpleNamespace(
        allow_eval=False,
        allow_compile=True,
        allow_commit=False,
        allow_tracing=True,
        allow_mcp_commit_when_gui=False,
        require_gemstone_ast=False,
        mcp_host='127.0.0.1',
        mcp_port=9177,
        mcp_http_path='/running-ide',
        transport='streamable-http',
    )
    with patch('reahl.swordfish.main.create_server') as create_server:
        mock_server = Mock()
        create_server.return_value = mock_server
        run_mcp_server(arguments)
    create_server.assert_called_once_with(
        allow_eval=False,
        allow_compile=True,
        allow_commit=False,
        allow_tracing=True,
        allow_commit_when_gui=False,
        integrated_session_state=None,
        require_gemstone_ast=False,
        mcp_host='127.0.0.1',
        mcp_port=9177,
        mcp_streamable_http_path='/running-ide',
    )
    mock_server.run.assert_called_once_with(transport='streamable-http')


@with_fixtures(SwordfishAppFixture)
def test_failed_login_shows_error_label(fixture):
    """If login credentials are rejected, the login frame stays visible and
    shows a red error label describing the failure instead of the browser."""
    with patch.object(GemstoneSessionRecord, 'log_in_linked',
                      side_effect=DomainException('Bad credentials')):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame.error_label is not None
    assert 'Bad credentials' in fixture.app.login_frame.error_label.cget('text')


@with_fixtures(SwordfishAppFixture)
def test_logout_returns_to_login_screen(fixture):
    """After a successful login, calling logout clears the browser interface
    and returns the user to the login screen."""
    fixture.simulate_login()

    fixture.app.logout()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame is not None
    assert fixture.app.login_frame.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_commit_sends_commit_to_gemstone(fixture):
    """Committing via the app delegates to the underlying GemStone session,
    persisting any pending changes in the repository."""
    fixture.simulate_login()

    fixture.app.commit()

    fixture.mock_gemstone_session.commit.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_abort_sends_abort_to_gemstone(fixture):
    """Aborting via the app delegates to the underlying GemStone session,
    discarding any uncommitted changes in the repository."""
    fixture.simulate_login()

    fixture.app.abort()

    fixture.mock_gemstone_session.abort.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_mcp_busy_state_publishes_events_for_listeners(fixture):
    """AI: MCP busy/idle transitions are published as events so subscribers can update UI behavior."""
    fixture.simulate_login()

    class BusyListener:
        def __init__(self):
            self.events = []

        def on_busy_state_changed(self, is_busy=False, operation_name=''):
            self.events.append((is_busy, operation_name))

    listener = BusyListener()
    fixture.app.event_queue.subscribe(
        'McpBusyStateChanged',
        listener.on_busy_state_changed,
    )

    fixture.app.last_mcp_busy_state = (
        fixture.app.integrated_session_state.is_mcp_busy()
    )
    fixture.app.integrated_session_state.begin_mcp_operation('gs_eval')
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (True, 'gs_eval')

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (False, '')


@with_fixtures(SwordfishAppFixture)
def test_mcp_busy_state_disables_run_and_session_controls(fixture):
    """AI: When MCP is busy, Run and Session controls are visually disabled and re-enabled when idle."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()

    fixture.app.integrated_session_state.begin_mcp_operation('gs_apply_rename_method')
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget('state')) == tk.DISABLED
    assert str(fixture.app.run_tab.debug_button.cget('state')) == tk.DISABLED
    assert fixture.app.run_tab.source_text.cget('state') == tk.DISABLED
    assert fixture.app.menu_bar.session_menu.entrycget(0, 'state') == tk.DISABLED

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget('state')) == tk.NORMAL
    assert str(fixture.app.run_tab.debug_button.cget('state')) == tk.NORMAL
    assert fixture.app.run_tab.source_text.cget('state') == tk.NORMAL
    assert fixture.app.menu_bar.session_menu.entrycget(0, 'state') == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_contains_start_stop_and_config_commands(fixture):
    """AI: MCP menu should expose start/stop/configure commands for runtime control."""
    mcp_menu = fixture.app.menu_bar.mcp_menu
    labels = menu_command_labels(mcp_menu)
    assert labels == ['Start MCP', 'Stop MCP', 'Configure MCP']
    assert mcp_menu.entrycget(0, 'state') == tk.NORMAL
    assert mcp_menu.entrycget(1, 'state') == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_commands_delegate_to_swordfish_handlers(fixture):
    """AI: Selecting MCP menu actions should call corresponding Swordfish command handlers."""
    mcp_menu = fixture.app.menu_bar.mcp_menu
    with patch.object(fixture.app, 'start_mcp_server_from_menu') as start_mcp:
        invoke_menu_command_by_label(mcp_menu, 'Start MCP')
    start_mcp.assert_called_once()
    with patch.object(fixture.app, 'stop_mcp_server_from_menu') as stop_mcp:
        with fixture.app.embedded_mcp_server_controller.lock:
            fixture.app.embedded_mcp_server_controller.running = True
        fixture.app.menu_bar.update_menus()
        invoke_menu_command_by_label(mcp_menu, 'Stop MCP')
    stop_mcp.assert_called_once()
    with patch.object(fixture.app, 'configure_mcp_server_from_menu') as configure_mcp:
        invoke_menu_command_by_label(mcp_menu, 'Configure MCP')
    configure_mcp.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_reflects_embedded_server_running_state(fixture):
    """AI: MCP menu should disable start and enable stop while embedded MCP is running."""
    with fixture.app.embedded_mcp_server_controller.lock:
        fixture.app.embedded_mcp_server_controller.running = True
    fixture.app.menu_bar.update_menus()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    assert mcp_menu.entrycget(0, 'state') == tk.DISABLED
    assert mcp_menu.entrycget(1, 'state') == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_result_on_successful_eval(fixture):
    """Running code in the Run tab should populate the result area with the evaluated object's printString."""
    fixture.simulate_login()

    # AI: on_run_complete calls result.asString().to_py to render the result.
    mock_result = Mock()
    mock_result.asString.return_value.to_py = '7'
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code('3 + 4')
    fixture.app.update()
    run_tab = fixture.app.run_tab

    result_content = run_tab.result_text.get('1.0', 'end').strip()
    assert result_content == '7'


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_always_shows_enabled_debug_button(fixture):
    """The Run tab should always show an enabled Debug button, even before any run error occurs."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, 'debug_button')
    assert run_tab.debug_button.winfo_exists()
    assert not run_tab.debug_button.instate(['disabled'])


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_debug_button_when_code_raises_error(fixture):
    """If run code raises a GemstoneError, the Run tab should still show the Debug button for opening the debugger."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, 'debug_button')
    assert run_tab.debug_button.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_run_source_text_shortcuts_replace_selection_and_support_undo(fixture):
    """Run source text supports select/copy/paste/undo shortcuts, and typed input replaces selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.source_text.bind('<Control-a>')
    assert run_tab.source_text.bind('<Control-c>')
    assert run_tab.source_text.bind('<Control-v>')
    assert run_tab.source_text.bind('<Control-z>')

    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', 'alpha beta')
    run_tab.source_text.tag_add(tk.SEL, '1.6', '1.10')

    fixture.app.clipboard_clear()
    fixture.app.clipboard_append('gamma')
    run_tab.paste_into_source_text()
    assert run_tab.source_text.get('1.0', 'end-1c') == 'alpha gamma'

    run_tab.undo_source_text()
    assert run_tab.source_text.get('1.0', 'end-1c') == 'alpha beta'

    run_tab.source_text.tag_add(tk.SEL, '1.0', '1.5')
    run_tab.replace_selected_source_text_before_typing(
        types.SimpleNamespace(state=0, char='z', keysym='z'),
    )
    run_tab.source_text.insert(tk.INSERT, 'z')
    assert run_tab.source_text.get('1.0', 'end-1c') == 'z beta'

    run_tab.select_all_source_text()
    run_tab.copy_source_selection()
    assert fixture.app.clipboard_get() == 'z beta'


@with_fixtures(SwordfishAppFixture)
def test_run_source_editor_shows_line_numbers(fixture):
    """AI: Run source editor displays line numbers that track visible source lines."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert(
        '1.0',
        'alpha\nbeta\ngamma',
    )
    fixture.app.update()

    line_numbers = run_tab.source_line_number_column.line_numbers_text.get(
        '1.0',
        'end-1c',
    ).splitlines()
    assert line_numbers[:3] == ['1', '2', '3']
    run_tab.source_text.mark_set(tk.INSERT, '3.2')
    run_tab.source_cursor_position_indicator.update_position()
    assert run_tab.source_cursor_position_label.cget('text') == 'Ln 3, Col 3'


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_run_and_inspect_for_selected_text(fixture):
    """Run source context menu exposes Run and Inspect commands that target selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', '3 + 4\n5 + 6')
    run_tab.source_text.tag_add(tk.SEL, '1.0', '1.5')

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert 'Run' in labels
    assert 'Inspect' in labels


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_run_executes_selected_text_only(fixture):
    """Run command in Run source context menu evaluates only the selected source fragment."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', '3 + 4\nthisWillNotRun')
    run_tab.source_text.tag_add(tk.SEL, '1.0', '1.5')

    mock_result = Mock()
    mock_result.asString.return_value.to_py = '7'
    fixture.mock_browser.run_code.return_value = mock_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, 'Run')
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with('3 + 4')
    assert run_tab.result_text.get('1.0', 'end').strip() == '7'


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_inspect_opens_inspector_for_selected_result(fixture):
    """Inspect command in Run source context menu evaluates selected source and opens Inspector on the result object."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', '3 + 4\nthisWillNotRun')
    run_tab.source_text.tag_add(tk.SEL, '1.0', '1.5')

    inspected_result = make_mock_gemstone_object('Integer', '7')
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, 'Inspect')
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with('3 + 4')
    assert fixture.app.inspector_tab is not None
    assert isinstance(fixture.app.inspector_tab, InspectorTab)
    assert isinstance(fixture.app.inspector_tab.explorer, Explorer)
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), 'text')
    assert selected_tab_text == 'Inspect'


@with_fixtures(SwordfishAppFixture)
def test_run_inspector_tab_can_be_closed_with_close_button(fixture):
    """The inspector tab opened from Run can be dismissed using its Close Inspector button."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', '3 + 4')
    run_tab.source_text.tag_add(tk.SEL, '1.0', '1.5')

    inspected_result = make_mock_gemstone_object('Integer', '7')
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, 'Inspect')
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    inspector_tab.close_button.invoke()
    fixture.app.update()

    assert fixture.app.inspector_tab is None
    tab_labels = [fixture.app.notebook.tab(tab_id, 'text') for tab_id in fixture.app.notebook.tabs()]
    assert 'Inspect' not in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_result_text_supports_copy_and_has_result_context_menu(fixture):
    """Run result text supports selecting/copying output via shortcuts and context menu actions."""
    fixture.simulate_login()
    mock_result = Mock()
    mock_result.asString.return_value.to_py = '42'
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code('40 + 2')
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.result_text.bind('<Control-a>')
    assert run_tab.result_text.bind('<Control-c>')

    run_tab.select_all_result_text()
    run_tab.copy_result_selection()
    assert fixture.app.clipboard_get() == '42'

    run_tab.open_result_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert 'Select All' in labels
    assert 'Copy' in labels
    assert 'Paste' not in labels
    assert 'Undo' not in labels


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_compile_error_location_and_highlights_source(fixture):
    """Compile errors show line/column details and visually mark the source position that failed to parse."""
    fixture.simulate_login()
    source_text = (
        '| a b |\n'
        'b := (Set new) add: 123; add: 457; add 1122; yourself.\n'
        'a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n'
        '\n'
        'a halt at: 5\n'
    )
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(source_text, 48)

    fixture.app.run_code(source_text)
    fixture.app.update()
    run_tab = fixture.app.run_tab

    status_text = run_tab.status_label.cget('text')
    assert 'line 2, column 40' in status_text

    result_text = run_tab.result_text.get('1.0', 'end')
    assert 'Line 2, column 40' in result_text
    assert 'b := (Set new) add: 123; add: 457; add 1122; yourself.' in result_text
    assert '\n                                       ^\n' in result_text

    highlight_range = run_tab.source_text.tag_ranges('compile_error_location')
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == '2.39'
    assert str(highlight_range[1]) == '2.40'


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_preserves_leading_blank_lines_for_compile_error_location(
    fixture,
):
    """Compile error location mapping keeps the source exactly as shown in the Run editor."""
    fixture.simulate_login()
    source_text = (
        '\n'
        '| a |\n'
        '\n'
        'a := set new.\n'
        'a\n'
    )

    def raise_compile_error(executed_source):
        offset = executed_source.index('set') + 1
        raise FakeCompileGemstoneError(executed_source, offset)

    fixture.mock_browser.run_code.side_effect = raise_compile_error

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', source_text)

    run_tab.run_button.invoke()
    fixture.app.update()

    status_text = run_tab.status_label.cget('text')
    assert 'line 4, column 6' in status_text
    expected_source = run_tab.source_text.get('1.0', 'end-1c')
    assert fixture.mock_browser.run_code.call_args_list[-1] == call(expected_source)

    highlight_range = run_tab.source_text.tag_ranges('compile_error_location')
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == '4.5'
    assert str(highlight_range[1]) == '4.6'


@with_fixtures(SwordfishAppFixture)
def test_debug_button_opens_debugger_tab_in_notebook(fixture):
    """Clicking Debug from the Run tab after a runtime error should open a Debugger tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_button_uses_current_source_text_not_stale_prior_error(fixture):
    """Debug always evaluates the code currently visible in the Run source editor."""
    fixture.simulate_login()
    successful_result = Mock()
    successful_result.asString.return_value.to_py = '4'
    fixture.mock_browser.run_code.side_effect = [
        FakeGemstoneError(),
        successful_result,
    ]

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', '2 + 2')

    run_tab.debug_button.invoke()
    fixture.app.update()

    assert fixture.mock_browser.run_code.call_args_list[-1] == call('2 + 2')
    assert fixture.app.debugger_tab is None
    assert run_tab.status_label.cget('text') == 'Completed successfully; no debugger context'


@with_fixtures(SwordfishAppFixture)
def test_debug_button_does_not_open_debugger_for_compile_error(fixture):
    """Debug does not open a debugger tab when current source has a compile error."""
    fixture.simulate_login()
    source_text = (
        '| a b |\n'
        'b := (Set new) add: 123; add: 457; add 1122; yourself.\n'
        'a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n'
        '\n'
        'a halt at: 5\n'
    )
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete('1.0', 'end')
    run_tab.source_text.insert('1.0', source_text)
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(source_text, 48)

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' not in tab_labels
    expected_source = run_tab.source_text.get('1.0', 'end-1c')
    assert fixture.mock_browser.run_code.call_args_list[-1] == call(expected_source)
    assert 'line 2, column 40' in run_tab.status_label.cget('text')


@with_fixtures(SwordfishAppFixture)
def test_debug_button_selects_debugger_tab_as_visible(fixture):
    """After Debug is clicked from the Run tab, the Debugger tab should become the selected notebook tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), 'text')
    assert selected_tab_text == 'Debugger'


@with_fixtures(SwordfishAppFixture)
def test_completed_debugger_can_be_dismissed_with_close_button(fixture):
    """AI: Once debugger execution completes, the UI should expose a close action that exits debugger mode."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    completed_result = Mock()
    completed_result.asString.return_value.to_py = '42'
    debugger_tab.finish(completed_result)
    fixture.app.update()

    assert debugger_tab.close_button.winfo_exists()
    debugger_tab.close_button.invoke()
    fixture.app.update()

    assert fixture.app.debugger_tab is None
    tab_labels = [
        fixture.app.notebook.tab(tab_id, 'text')
        for tab_id in fixture.app.notebook.tabs()
    ]
    assert 'Debugger' not in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_navigates_to_selected_stack_frame_method(fixture):
    """AI: Browse Method on debugger should navigate the browser to the selected stack frame method."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name='OrderLine',
        method_name='total',
    )

    with patch.object(
        debugger_tab,
        'get_selected_stack_frame',
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            'handle_sender_selection',
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        'OrderLine',
        True,
        'total',
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_maps_class_side_frames_to_class_side_selection(fixture):
    """AI: Class-side stack frames should browse to the class side in the browser."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name='OrderLine class',
        method_name='buildForDemo',
    )

    with patch.object(
        debugger_tab,
        'get_selected_stack_frame',
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            'handle_sender_selection',
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        'OrderLine',
        False,
        'buildForDemo',
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_button_dispatches_to_browse_selected_frame_method(fixture):
    """AI: Browse Method debugger control should invoke debugger frame browsing action."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab

    with patch.object(
        debugger_tab,
        'open_selected_frame_method',
    ) as open_selected_frame_method:
        debugger_tab.debugger_controls.browse_button.invoke()

    open_selected_frame_method.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_file_run_command_opens_run_tab_in_notebook(fixture):
    """Choosing File > Run should open and select a Run tab in the main notebook."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(tab_id, 'text') for tab_id in fixture.app.notebook.tabs()]
    assert 'Run' in tab_labels
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), 'text')
    assert selected_tab_text == 'Run'


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_search_populates_result_list(fixture):
    """Searching for a class name in the FindDialog calls GemStone and
    populates the results listbox with the matching class names."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ['OrderLine', 'OrderHistory']

    with patch.object(FindDialog, 'wait_visibility'):
        dialog = FindDialog(fixture.app)

    dialog.find_entry.insert(0, 'Order')
    dialog.find_text()

    results = list(dialog.results_listbox.get(0, 'end'))
    assert 'OrderLine' in results
    assert 'OrderHistory' in results
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_navigates_browser_to_selected_class(fixture):
    """Double-clicking a class name in the FindDialog results navigates the
    browser to that class by selecting its package and class in the columns."""
    fixture.simulate_login()
    # AI: jump_to_class resolves the class symbol to find its package via
    # gemstone_session.resolve_symbol(name).category().to_py
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = 'Kernel'

    with patch.object(FindDialog, 'wait_visibility'):
        dialog = FindDialog(fixture.app)

    dialog.results_listbox.insert(tk.END, 'OrderLine')
    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == 'OrderLine'
    assert fixture.session_record.selected_package == 'Kernel'


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_method_search_populates_result_list(fixture):
    """Searching for senders in the SendersDialog shows sender methods with class/side labels."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
            {
                'class_name': 'Order',
                'show_instance_side': False,
                'method_selector': 'default',
            },
        ],
        'total_count': 2,
        'returned_count': 2,
    }

    with patch.object(SendersDialog, 'wait_visibility'):
        dialog = SendersDialog(fixture.app, method_name='total')

    results = list(dialog.results_listbox.get(0, 'end'))
    assert results == ['OrderLine>>recalculateTotal', 'Order class>>default']
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_double_click_navigates_browser_to_selected_sender(fixture):
    """Double-clicking a sender result jumps the browser to that sender method context."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = 'Kernel'
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
        ],
        'total_count': 1,
        'returned_count': 1,
    }

    with patch.object(SendersDialog, 'wait_visibility'):
        dialog = SendersDialog(fixture.app, method_name='total')

    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == 'OrderLine'
    assert fixture.session_record.selected_package == 'Kernel'
    assert fixture.session_record.show_instance_side is True
    assert fixture.session_record.selected_method_symbol == 'recalculateTotal'


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_filters_to_observed_senders(fixture):
    """AI: Narrowing sender results with tracing should keep only observed runtime callers."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
            {
                'class_name': 'Order',
                'show_instance_side': False,
                'method_selector': 'default',
            },
        ],
        'total_count': 2,
        'returned_count': 2,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        'candidate_test_count': 1,
        'candidate_tests': [
            {
                'test_case_class_name': 'OrderLineTest',
                'test_method_selector': 'testRecalculateTotal',
                'depth': 1,
                'reached_from_selector': 'recalculateTotal',
            },
        ],
        'visited_selector_count': 3,
        'sender_search_truncated': False,
        'selector_limit_reached': False,
        'elapsed_limit_reached': False,
    }
    fixture.mock_browser.run_test_method.return_value = {
        'run_count': 1,
        'failure_count': 0,
        'error_count': 0,
        'has_passed': True,
        'failures': [],
        'errors': [],
    }
    fixture.mock_browser.trace_selector.return_value = {
        'method_name': 'total',
        'total_sender_count': 2,
        'targeted_sender_count': 2,
        'traced_sender_count': 2,
        'skipped_sender_count': 0,
        'traced_senders': [],
        'skipped_senders': [],
    }
    fixture.mock_browser.observed_senders_for_selector.return_value = {
        'total_count': 1,
        'returned_count': 1,
        'total_observed_calls': 2,
        'observed_senders': [
            {
                'caller_class_name': 'OrderLine',
                'caller_show_instance_side': True,
                'caller_method_selector': 'recalculateTotal',
                'method_selector': 'total',
                'observed_count': 2,
            },
        ],
    }
    selected_tests = [
        {
            'test_case_class_name': 'OrderLineTest',
            'test_method_selector': 'testRecalculateTotal',
            'depth': 1,
            'reached_from_selector': 'recalculateTotal',
        },
    ]

    with patch.object(SendersDialog, 'wait_visibility'):
        with patch.object(
            SendersDialog,
            'choose_tests_for_tracing',
            return_value=selected_tests,
        ):
            dialog = SendersDialog(fixture.app, method_name='total')
            dialog.narrow_senders_with_tracing()

    results = list(dialog.results_listbox.get(0, 'end'))
    assert results == ['OrderLine>>recalculateTotal']
    fixture.mock_browser.sender_test_plan_for_selector.assert_called_once_with(
        'total',
        2,
        500,
        200,
        200,
        max_elapsed_ms=1500,
    )
    fixture.mock_browser.trace_selector.assert_called_once_with(
        'total',
        max_results=250,
    )
    fixture.mock_browser.run_test_method.assert_called_once_with(
        'OrderLineTest',
        'testRecalculateTotal',
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_stops_when_no_candidate_tests(
    fixture,
):
    """AI: Narrowing should inform the user and skip tracing when no candidate tests are found."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
        ],
        'total_count': 1,
        'returned_count': 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        'candidate_test_count': 0,
        'candidate_tests': [],
        'visited_selector_count': 1,
        'elapsed_limit_reached': True,
        'sender_search_truncated': True,
    }

    with patch.object(SendersDialog, 'wait_visibility'):
        with patch('reahl.swordfish.main.messagebox.showinfo') as showinfo:
            dialog = SendersDialog(fixture.app, method_name='total')
            dialog.narrow_senders_with_tracing()

    assert showinfo.called
    fixture.mock_browser.trace_selector.assert_not_called()
    dialog.destroy()


def make_mock_gemstone_object(class_name='OrderLine', string_repr='anObject'):
    """AI: Minimal GemStone object mock satisfying ObjectInspector's full protocol.
    allInstVarNames() returns [] so sub-inspectors are created empty (no recursion needed).
    isBehavior() returns False so instances are inspected via inspect_instance, not inspect_class."""
    obj = Mock()
    obj.gemstone_class.return_value.asString.return_value.to_py = class_name
    obj.asString.return_value.to_py = string_repr
    obj.gemstone_class.return_value.allInstVarNames.return_value = []
    obj.isBehavior.return_value.to_py = False
    return obj


def make_mock_dictionary(entries):
    dictionary = make_mock_gemstone_object('Dictionary', f'a Dictionary({len(entries)})')
    keys = []
    values_by_key = {}
    for key_name, value in entries:
        key = make_mock_gemstone_object('Symbol', key_name)
        keys.append(key)
        values_by_key[key] = value

    dictionary.keys.return_value = keys
    dictionary.size.return_value.to_py = len(keys)

    def at_key(key):
        return values_by_key[key]

    dictionary.at.side_effect = at_key
    return dictionary


def make_mock_array(values):
    array = make_mock_gemstone_object('Array', f'an Array({len(values)})')
    array.size.return_value.to_py = len(values)
    values_by_index = {
        index + 1: value
        for index, value in enumerate(values)
    }

    def at_index(index):
        return values_by_index[index]

    array.at.side_effect = at_index
    return array


class ObjectInspectorFixture(Fixture):
    @set_up
    def create_explorer(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_self = make_mock_gemstone_object('OrderLine', 'anOrderLine')
        self.mock_x = make_mock_gemstone_object('Integer', '42')

        # AI: Pass values= directly so ObjectInspector skips the live GemStone
        # instVar-fetching path, while still populating the treeview rows.
        self.explorer = Explorer(
            self.root, values={'self': self.mock_self, 'x': self.mock_x}
        )
        self.explorer.pack()
        self.root.update()

        # AI: The Context tab (index 0) is an ObjectInspector added by Explorer.__init__
        self.context_inspector = self.root.nametowidget(self.explorer.tabs()[0])

    @tear_down
    def destroy_explorer(self):
        self.root.destroy()

    def focus_item(self, variable_name):
        """AI: Focus the treeview row whose first column matches variable_name."""
        for item in self.context_inspector.treeview.get_children():
            if self.context_inspector.treeview.item(item, 'values')[0] == variable_name:
                self.context_inspector.treeview.focus(item)
                return
        raise ValueError(f'{variable_name!r} not found in treeview')


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_value_opens_new_inspector_tab_and_selects_it(fixture):
    """Double-clicking an object in the inspector opens a new tab in the
    Explorer notebook for that object and immediately makes it the visible tab."""
    fixture.focus_item('self')
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, 'text') for t in fixture.explorer.tabs()]
    assert 'OrderLine' in tab_labels
    assert fixture.explorer.tab(fixture.explorer.select(), 'text') == 'OrderLine'


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_same_value_again_reuses_existing_tab(fixture):
    """Re-opening an inspector for an object that already has a tab switches
    to that tab rather than adding a duplicate."""
    fixture.focus_item('self')
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    # AI: Switch to Context so the 'self' tab is no longer selected,
    # then double-click 'self' a second time to verify deduplication.
    fixture.explorer.select(fixture.explorer.tabs()[0])
    fixture.focus_item('self')
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, 'text') for t in fixture.explorer.tabs()]
    assert tab_labels.count('OrderLine') == 1
    assert fixture.explorer.tab(fixture.explorer.select(), 'text') == 'OrderLine'


@with_fixtures(ObjectInspectorFixture)
def test_dictionary_inspector_shows_key_value_rows_and_drills_into_value(fixture):
    """Dictionary-like objects are shown as key/value rows and double-clicking a row opens an inspector for the value."""
    first_value = make_mock_gemstone_object('Integer', '1')
    second_value = make_mock_gemstone_object('OrderLine', 'anOrderLine')
    dictionary = make_mock_dictionary([
        ('first', first_value),
        ('second', second_value),
    ])

    dictionary_inspector = ObjectInspector(fixture.explorer, an_object=dictionary)
    fixture.explorer.add(dictionary_inspector, text='Dictionary')
    fixture.explorer.select(dictionary_inspector)
    fixture.root.update()

    rows = dictionary_inspector.treeview.get_children()
    assert dictionary_inspector.treeview.heading('Name', 'text') == 'Key'
    assert len(rows) == 2
    assert dictionary_inspector.status_label.cget('text') == '2 items'

    dictionary_inspector.treeview.focus(rows[0])
    dictionary_inspector.on_item_double_click(None)
    fixture.root.update()

    assert fixture.explorer.tab(fixture.explorer.select(), 'text') == 'Integer'


@with_fixtures(ObjectInspectorFixture)
def test_array_inspector_shows_size_and_pages_through_values(fixture):
    """Array-like objects show indexed rows, report total size, and allow paging through large collections."""
    values = [
        make_mock_gemstone_object('Integer', str(index))
        for index in range(105)
    ]
    array = make_mock_array(values)
    array_inspector = ObjectInspector(fixture.root, an_object=array)
    array_inspector.pack()
    fixture.root.update()

    rows = array_inspector.treeview.get_children()
    assert array_inspector.treeview.heading('Name', 'text') == 'Index'
    assert len(rows) == 100
    assert array_inspector.status_label.cget('text') == 'Items 1-100 of 105'

    array_inspector.on_next_page()
    fixture.root.update()

    next_rows = array_inspector.treeview.get_children()
    assert len(next_rows) == 5
    assert array_inspector.status_label.cget('text') == 'Items 101-105 of 105'
    assert array_inspector.treeview.item(next_rows[0], 'values')[0] == '[101]'


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_runs_test_and_shows_pass_result(fixture):
    """Right-clicking a method and choosing Run Test calls run_test_method on
    the session and shows a passing info dialog when all assertions pass."""
    # AI: Navigate to the method so the method listbox has a live selection,
    # matching what show_context_menu does before invoking run_test.
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    passing_result = {'run_count': 1, 'failure_count': 0, 'error_count': 0,
                      'has_passed': True, 'failures': [], 'errors': []}
    fixture.mock_browser.run_test_method = Mock(return_value=passing_result)

    with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    fixture.mock_browser.run_test_method.assert_called_once_with('OrderLine', 'total')
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_calls_browser_preview(fixture):
    """Preview Add Parameter from the method editor forwards all prompt inputs to the browser preview API."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.method_add_parameter_preview.return_value = {'preview': 'ok'}
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    with patch('reahl.swordfish.main.simpledialog.askstring',
               side_effect=['with:', 'extraValue', 'nil']):
        with patch('reahl.swordfish.main.JsonResultDialog') as mock_result_dialog:
            tab.code_panel.preview_method_add_parameter()

    fixture.mock_browser.method_add_parameter_preview.assert_called_once_with(
        'OrderLine',
        True,
        'total',
        'with:',
        'extraValue',
        'nil',
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_calls_browser_preview(fixture):
    """Preview Extract Method uses selected statements and calls browser extract preview with inferred statement indexes."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.method_ast.return_value = {
        'statements': [
            {
                'statement_index': 1,
                'start_offset': 6,
                'end_offset': 24,
                'source': '^amount * quantity',
                'sends': [],
            },
        ],
        'temporaries': [],
        'header_source': 'total',
    }
    fixture.mock_browser.method_extract_preview.return_value = {'preview': 'ok'}
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.tag_add(tk.SEL, '2.0', '2.end')

    with patch('reahl.swordfish.main.simpledialog.askstring',
               return_value='extractedPart'):
        with patch('reahl.swordfish.main.JsonResultDialog') as mock_result_dialog:
            tab.code_panel.preview_method_extract()

    fixture.mock_browser.method_ast.assert_called_once_with(
        'OrderLine',
        'total',
        True,
    )
    fixture.mock_browser.method_extract_preview.assert_called_once_with(
        'OrderLine',
        True,
        'total',
        'extractedPart',
        [1],
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_requires_selection(fixture):
    """Preview Extract Method reports a user-facing error when no statement is selected."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
        tab.code_panel.preview_method_extract()

    mock_msgbox.showerror.assert_called_once()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_partial_return_selection_reports_selection_error(
    fixture,
):
    """Partially selecting a return statement should report selection coverage guidance, not a return-extraction error."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.method_ast.return_value = {
        'statements': [
            {
                'statement_index': 1,
                'start_offset': 10,
                'end_offset': 27,
                'source': '^amount * quantity',
                'sends': [],
            },
        ],
        'temporaries': [],
        'header_source': 'total',
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]
    tab.code_panel.text_editor.tag_add(tk.SEL, '2.14', '2.end')

    with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
        with patch('reahl.swordfish.main.simpledialog.askstring') as mock_askstring:
            tab.code_panel.preview_method_extract()

    mock_askstring.assert_not_called()
    mock_msgbox.showerror.assert_called_once()
    error_message = mock_msgbox.showerror.call_args[0][1]
    assert 'fully cover' in error_message
    assert 'return' not in error_message.lower()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_suggests_keyword_selector_when_arguments_are_needed(
    fixture,
):
    """Extract suggestion should default to a keyword selector when selected statements depend on caller-scoped variables."""
    fixture.mock_browser.list_methods.return_value = ['buildFrom:']
    mock_method = Mock()
    mock_method.sourceString.return_value.to_py = (
        'buildFrom: input\n'
        '    | tmp |\n'
        '    tmp := input + 1.\n'
        '    ^tmp'
    )
    fixture.mock_browser.get_compiled_method.return_value = mock_method
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'buildFrom:')
    fixture.mock_browser.method_ast.return_value = {
        'statements': [
            {
                'statement_index': 1,
                'start_offset': 33,
                'end_offset': 49,
                'source': 'tmp := input + 1',
                'sends': [],
            },
        ],
        'temporaries': ['tmp'],
        'header_source': 'buildFrom: input',
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'buildFrom:')]
    tab.code_panel.text_editor.tag_add(tk.SEL, '3.0', '3.end')

    captured_initial_values = []

    def fake_askstring(*args, **kwargs):
        captured_initial_values.append(kwargs.get('initialvalue'))
        return None

    with patch('reahl.swordfish.main.simpledialog.askstring', side_effect=fake_askstring):
        tab.code_panel.preview_method_extract()

    assert captured_initial_values == ['extractedComputeTmp:']
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_shows_error_for_browser_domain_exception(
    fixture,
):
    """Add-parameter preview failures from browser domain rules should surface as dialog errors, not Tk callback crashes."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.method_add_parameter_preview.side_effect = GemstoneDomainException(
        'Could not parse keyword method header.'
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    with patch('reahl.swordfish.main.simpledialog.askstring',
               side_effect=['with:', 'extraValue', 'nil']):
        with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
            tab.code_panel.preview_method_add_parameter()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_inline_shows_error_for_browser_domain_exception(
    fixture,
):
    """Inline preview validation failures should be caught and shown as an error dialog."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    fixture.mock_browser.method_inline_preview.side_effect = GemstoneDomainException(
        'inline_selector must be a unary selector.'
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[('OrderLine', True, 'total')]

    with patch('reahl.swordfish.main.simpledialog.askstring',
               return_value='ifTrue:'):
        with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
            tab.code_panel.preview_method_inline()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_shows_error_dialog_when_test_fails(fixture):
    """When a test method has failures or errors, Run Test shows an error
    dialog rather than an info dialog, surfacing the failure messages."""
    # AI: Navigate all the way to the method so the method listbox has a live
    # selection, matching what show_context_menu sets before invoking run_test.
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    failing_result = {'run_count': 1, 'failure_count': 1, 'error_count': 0,
                      'has_passed': False, 'failures': ['total: expected true'], 'errors': []}
    fixture.mock_browser.run_test_method = Mock(return_value=failing_result)

    with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_class_runs_all_tests_and_shows_result(fixture):
    """Right-clicking a class and choosing Run All Tests calls run_gemstone_tests
    for that class and shows the result summary in a dialog."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox, 'Kernel')
    # AI: Also select a class in the classes listbox so run_all_tests() reads a
    # live curselection(), matching what show_context_menu sets before invoking it.
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox, 'OrderLine')

    passing_result = {'run_count': 3, 'failure_count': 0, 'error_count': 0,
                      'has_passed': True, 'failures': [], 'errors': []}
    fixture.mock_browser.run_gemstone_tests = Mock(return_value=passing_result)

    with patch('reahl.swordfish.main.messagebox') as mock_msgbox:
        fixture.browser_window.classes_widget.run_all_tests()

    fixture.mock_browser.run_gemstone_tests.assert_called_once_with('OrderLine')
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_run_test_method_opens_debugger_on_gemstone_error(fixture):
    """If running a test method raises a GemstoneError (e.g. an unhandled
    runtime exception), the debugger tab opens — the same flow as the Run tab."""
    fixture.simulate_login()

    # AI: Pre-load the method listbox and set selected_class directly;
    # no column-cascade navigation is needed to test the error-catching path.
    methods_listbox = fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    methods_listbox.insert(tk.END, 'testDivideByZero')
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = 'SwordfishDebuggerDemoTest'

    fixture.mock_browser.run_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.run_test()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_all_tests_opens_debugger_on_gemstone_error(fixture):
    """If running all tests for a class raises a GemstoneError, the debugger
    tab opens so the user can inspect the error context and stack."""
    fixture.simulate_login()

    # AI: Pre-load the classes listbox; no full cascade needed for the error path.
    classes_listbox = fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    classes_listbox.insert(tk.END, 'SwordfishDebuggerDemoTest')
    classes_listbox.selection_set(0)

    fixture.mock_browser.run_gemstone_tests = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.classes_widget.run_all_tests()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_test_opens_debugger_even_for_assertion_failures(fixture):
    """Choosing Debug Test runs the test via runCase (no SUnit error trapping),
    so both assertion failures and runtime errors open the debugger rather than
    returning a pass/fail summary."""
    fixture.simulate_login()

    methods_listbox = fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    methods_listbox.insert(tk.END, 'testSomethingBroken')
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = 'MyTestCase'

    # AI: debug_test_method always raises GemstoneError when the test fails
    # because runCase has no error handling — assertion failures propagate too.
    fixture.mock_browser.debug_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.debug_test()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' in tab_labels
