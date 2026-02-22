import tkinter as tk
import types
from tkinter import ttk
from unittest.mock import Mock
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
from reahl.swordfish.main import BrowserWindow
from reahl.swordfish.main import DomainException
from reahl.swordfish.main import EventQueue
from reahl.swordfish.main import Explorer
from reahl.swordfish.main import FindDialog
from reahl.swordfish.main import GemstoneSessionRecord
from reahl.swordfish.main import ObjectInspector
from reahl.swordfish.main import RunDialog
from reahl.swordfish.main import SendersDialog
from reahl.swordfish.main import Swordfish


class FakeApplication:
    """AI: Thin stand-in for Swordfish that supplies the two attributes BrowserWindow needs."""

    def __init__(self, event_queue, gemstone_session_record):
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record

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
def test_selecting_method_opens_editor_tab(fixture):
    """Choosing a method from the method list opens a new editor tab
    containing that method's source code."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 1
    tab_text = notebook.tab(notebook.tabs()[0], 'text')
    assert tab_text == 'total'


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
    command_labels = []
    entry_count = int(menu.index('end')) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) == 'command':
            command_labels.append(menu.entrycget(entry_index, 'label'))

    assert 'Jump to Class' in command_labels
    assert 'Save' in command_labels
    assert 'Close' in command_labels
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
def test_run_dialog_shows_result_on_successful_eval(fixture):
    """Running code that completes without error populates the result area
    of the RunDialog with the printString of the returned object."""
    fixture.simulate_login()

    # AI: on_run_complete calls result.asString().to_py to render the result.
    mock_result = Mock()
    mock_result.asString.return_value.to_py = '7'
    fixture.mock_browser.run_code.return_value = mock_result

    dialog = RunDialog(fixture.app, source='3 + 4')
    fixture.app.update()

    result_content = dialog.result_text.get('1.0', 'end').strip()
    assert result_content == '7'
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_debug_button_when_code_raises_error(fixture):
    """If the evaluated code raises a GemstoneError, the RunDialog adds a
    Debug button so the user can open the debugger for that exception."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    dialog = RunDialog(fixture.app, source='1/0')
    fixture.app.update()

    assert hasattr(dialog, 'debug_button')
    assert dialog.debug_button.winfo_exists()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_debug_button_opens_debugger_tab_in_notebook(fixture):
    """Clicking the Debug button after a runtime error opens a Debugger tab
    in the main application notebook."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    dialog = RunDialog(fixture.app, source='1/0')
    fixture.app.update()

    dialog.debug_button.invoke()
    fixture.app.update()

    tab_labels = [fixture.app.notebook.tab(t, 'text') for t in fixture.app.notebook.tabs()]
    assert 'Debugger' in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_button_selects_debugger_tab_as_visible(fixture):
    """After the Debugger tab is opened it becomes the currently visible tab,
    so the user sees the debug view without having to click the tab manually."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    dialog = RunDialog(fixture.app, source='1/0')
    fixture.app.update()

    dialog.debug_button.invoke()
    fixture.app.update()

    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), 'text')
    assert selected_tab_text == 'Debugger'


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
    assert 'Inspector: self' in tab_labels
    assert fixture.explorer.tab(fixture.explorer.select(), 'text') == 'Inspector: self'


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
    assert tab_labels.count('Inspector: self') == 1
    assert fixture.explorer.tab(fixture.explorer.select(), 'text') == 'Inspector: self'


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
    runtime exception), the debugger tab opens — the same flow as the RunDialog."""
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
