import os
import tempfile
import tkinter as tk
import types
from tkinter import ttk
from unittest.mock import ANY, Mock, call, patch

from reahl.ptongue import GemstoneError
from reahl.tofu import (
    Fixture,
    NoException,
    expected,
    scenario,
    set_up,
    tear_down,
    with_fixtures,
)

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.main import (
    BreakpointsDialog,
    BrowserWindow,
    CoveringTestsBrowseDialog,
    CoveringTestsSearchDialog,
    DomainException,
    EventQueue,
    Explorer,
    FindDialog,
    GemstoneSessionRecord,
    GraphNode,
    GraphObjectRegistry,
    InspectorTab,
    McpConfigurationStore,
    McpRuntimeConfig,
    McpServerController,
    ObjectInspector,
    Swordfish,
    UmlClassNode,
    UmlDiagramRegistry,
    UmlMethodChooserDialog,
)
from reahl.swordfish.mcp.integration_state import IntegratedSessionState


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
            selected_method_category = self.gemstone_session_record.gemstone_browser_session.get_method_category(
                class_name,
                method_symbol,
                show_instance_side,
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(class_name)
            self.gemstone_session_record.select_method_category(
                selected_method_category
            )
            self.gemstone_session_record.select_method_symbol(method_symbol)
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish("MethodSelected")

    def begin_foreground_activity(self, message):
        pass

    def end_foreground_activity(self):
        pass

    def open_uml_for_class(self, class_name):
        pass

    def pin_method_in_uml(self, class_name, show_instance_side, method_selector):
        pass


class SwordfishGuiFixture(Fixture):
    @set_up
    def create_app(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        self.mock_browser.list_categories.return_value = ["Kernel", "Collections"]
        self.mock_browser.list_dictionaries.return_value = [
            "Kernel",
            "Collections",
        ]
        self.mock_browser.list_classes_in_category.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.list_classes_in_dictionary.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.rowan_installed.return_value = False
        self.mock_browser.list_rowan_packages.return_value = []
        self.mock_browser.list_classes_in_rowan_package.return_value = []
        self.mock_browser.list_method_categories.return_value = ["accessing", "testing"]
        self.mock_browser.list_methods.return_value = ["total", "description"]
        self.mock_browser.list_breakpoints.return_value = []
        self.mock_browser.get_method_category.return_value = "accessing"
        class_definitions = {
            "OrderLine": {
                "class_name": "OrderLine",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["amount", "quantity"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Order": {
                "class_name": "Order",
                "superclass_name": "Object",
                "package_name": "Kernel",
                "inst_var_names": ["lines"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Object": {
                "class_name": "Object",
                "superclass_name": None,
                "package_name": "Kernel",
                "inst_var_names": [],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
        }

        def get_class_definition(class_name):
            class_definition = class_definitions.get(class_name)
            if class_definition is None:
                raise GemstoneDomainException("Unknown class_name.")
            return class_definition

        self.mock_browser.get_class_definition.side_effect = get_class_definition

        # AI: get_compiled_method returns an object whose sourceString() method
        # returns an object with a .to_py attribute (the raw Smalltalk source string).
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = "total\n    ^amount * quantity"
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
        items = listbox.get(0, "end")
        idx = list(items).index(item)
        listbox.selection_clear(0, "end")
        listbox.selection_set(idx)
        selection_list = (
            listbox.master
        )  # AI: listbox is a direct child of InteractiveSelectionList
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
        entry_count = int(menu.index("end")) + 1
        for entry_index in range(entry_count):
            if menu.type(entry_index) != "command":
                continue
            if menu.entrycget(entry_index, "label") == label:
                menu.invoke(entry_index)
                self.root.update()
                return
        raise AssertionError(f"Menu command not found: {label}")

    def selected_listbox_entry(self, listbox):
        selected_index = listbox.curselection()[0]
        return listbox.get(selected_index)


def menu_command_labels(menu):
    labels = []
    entry_count = int(menu.index("end")) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) == "command":
            labels.append(menu.entrycget(entry_index, "label"))
    return labels


def invoke_menu_command_by_label(menu, label):
    entry_count = int(menu.index("end")) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) != "command":
            continue
        if menu.entrycget(entry_index, "label") == label:
            menu.invoke(entry_index)
            return
    raise AssertionError(f"Menu command not found: {label}")


@with_fixtures(SwordfishGuiFixture)
def test_selecting_group_fetches_and_shows_classes(fixture):
    """AI: Selecting a left-pane group should fetch classes for the active browse mode."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )

    fixture.mock_browser.list_classes_in_dictionary.assert_called_with("Kernel")
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "Order"]


@with_fixtures(SwordfishGuiFixture)
def test_switching_left_pane_to_dictionaries_shows_dictionary_names(fixture):
    """AI: Switching the left pane to dictionaries should repopulate it from symbolList dictionary names."""
    fixture.mock_browser.list_dictionaries.return_value = [
        "SessionGlobals",
        "UserGlobals",
    ]

    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()

    assert fixture.session_record.browse_mode == "dictionaries"
    left_pane_entries = list(
        fixture.browser_window.packages_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert left_pane_entries == ["SessionGlobals", "UserGlobals"]


@with_fixtures(SwordfishGuiFixture)
def test_selecting_dictionary_fetches_and_shows_classes_in_dictionary(fixture):
    """AI: In dictionary browse mode, selecting a dictionary should populate classes from that dictionary."""
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals"]
    fixture.mock_browser.list_classes_in_dictionary.return_value = [
        "OrderLine",
    ]

    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "UserGlobals",
    )

    fixture.mock_browser.list_classes_in_dictionary.assert_called_with(
        "UserGlobals",
    )
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine"]


@with_fixtures(SwordfishGuiFixture)
def test_switching_left_pane_to_categories_shows_category_names(fixture):
    """AI: Switching to categories mode should repopulate the left pane from ClassOrganizer categories."""
    fixture.mock_browser.list_categories.return_value = [
        "Kernel",
        "Collections",
        "Stuff",
    ]
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()

    assert fixture.session_record.browse_mode == "categories"
    left_pane_entries = list(
        fixture.browser_window.packages_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert left_pane_entries == ["Kernel", "Collections", "Stuff"]


@with_fixtures(SwordfishGuiFixture)
def test_rowan_mode_button_is_disabled_when_rowan_is_not_installed(fixture):
    """AI: Rowan mode should be unavailable when Rowan is not installed on the connected stone."""
    fixture.mock_browser.rowan_installed.return_value = False
    fixture.browser_window.packages_widget.handle_browse_mode_changed()
    fixture.root.update()

    rowan_state = fixture.browser_window.packages_widget.rowan_radiobutton.cget("state")
    assert rowan_state == tk.DISABLED


@with_fixtures(SwordfishGuiFixture)
def test_selecting_category_fetches_and_shows_classes_in_category(fixture):
    """AI: In categories mode, selecting a category should populate classes from that category only."""
    fixture.mock_browser.list_categories.return_value = ["Kernel"]
    fixture.mock_browser.list_classes_in_category.return_value = [
        "OrderLine",
    ]
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )

    fixture.mock_browser.list_classes_in_category.assert_called_with("Kernel")
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine"]


@with_fixtures(SwordfishGuiFixture)
def test_add_class_creates_in_selected_package_and_selects_it(fixture):
    """AI: Adding a class in categories mode should create it in UserGlobals."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.mock_browser.list_classes_in_category.return_value = [
        "OrderLine",
        "Order",
        "Invoice",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["Invoice", "Object"],
    ):
        fixture.browser_window.classes_widget.add_class()
        fixture.root.update()

    fixture.mock_browser.create_class.assert_called_with(
        class_name="Invoice",
        superclass_name="Object",
        in_dictionary="UserGlobals",
    )
    assert not fixture.mock_browser.assign_class_to_package.called
    assert fixture.session_record.selected_class == "Invoice"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.classes_widget.selection_list.selection_listbox
        )
        == "Invoice"
    )


@with_fixtures(SwordfishGuiFixture)
def test_add_class_in_dictionary_mode_creates_in_selected_dictionary(fixture):
    """AI: Adding a class in dictionary mode should create it directly in the selected dictionary."""
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals"]
    fixture.mock_browser.list_classes_in_dictionary.return_value = ["Invoice"]
    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "UserGlobals",
    )

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["Invoice", "Object"],
    ):
        fixture.browser_window.classes_widget.add_class()
        fixture.root.update()

    fixture.mock_browser.create_class.assert_called_with(
        class_name="Invoice",
        superclass_name="Object",
        in_dictionary="UserGlobals",
    )
    assert not fixture.mock_browser.assign_class_to_package.called


@with_fixtures(SwordfishGuiFixture)
def test_delete_class_removes_selected_class_and_clears_method_selection(fixture):
    """AI: Deleting a selected class in categories mode should target UserGlobals and clear class/method selection state."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_classes_in_category.return_value = ["Order"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.classes_widget.delete_class()
        fixture.root.update()

    fixture.mock_browser.delete_class.assert_called_once_with(
        "OrderLine",
        in_dictionary="UserGlobals",
    )
    assert fixture.session_record.selected_class is None
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.classes_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    ) == ["Order"]


@with_fixtures(SwordfishGuiFixture)
def test_add_category_creates_category_for_selected_class_side(fixture):
    """AI: Adding a category from the category pane should create it on the selected class side and select it."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "validation",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="validation",
    ):
        fixture.browser_window.categories_widget.add_category()
        fixture.root.update()

    fixture.mock_browser.create_method_category.assert_called_once_with(
        "OrderLine",
        "validation",
        True,
    )
    assert fixture.session_record.selected_method_category == "validation"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "validation"
    )


@with_fixtures(SwordfishGuiFixture)
def test_delete_category_removes_selected_category_and_selects_remaining(fixture):
    """AI: Deleting a selected category should remove it from the current class side and select a remaining category."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.select_in_listbox(
        fixture.browser_window.categories_widget.selection_list.selection_listbox,
        "accessing",
    )
    fixture.mock_browser.list_method_categories.return_value = ["testing"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.categories_widget.delete_category()
        fixture.root.update()

    fixture.mock_browser.delete_method_category.assert_called_once_with(
        "OrderLine",
        "accessing",
        True,
    )
    assert fixture.session_record.selected_method_category == "testing"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "testing"
    )


@with_fixtures(SwordfishGuiFixture)
def test_add_method_compiles_template_in_as_yet_unclassified_and_opens_tab(fixture):
    """AI: Adding a method compiles a starter template in as yet unclassified and opens that method in the editor."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "as yet unclassified",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="calculateTotal",
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        "OrderLine",
        True,
        "calculateTotal\n    ^self",
        method_category="as yet unclassified",
    )
    assert fixture.session_record.selected_method_category == "as yet unclassified"
    assert fixture.session_record.selected_method_symbol == "calculateTotal"
    assert (
        "OrderLine",
        True,
        "calculateTotal",
    ) in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_add_method_generates_keyword_template_argument_names(fixture):
    """AI: Keyword selectors are prepopulated with argument placeholders so the generated method source compiles."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "as yet unclassified",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="copyFrom:to:",
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        "OrderLine",
        True,
        "copyFrom: argument1 to: argument2\n    ^self",
        method_category="as yet unclassified",
    )


@with_fixtures(SwordfishGuiFixture)
def test_delete_method_removes_selected_method_from_class(fixture):
    """AI: Deleting a selected method should remove it from the class and clear selected method state."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.list_methods.return_value = ["description"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.methods_widget.delete_method()
        fixture.root.update()

    fixture.mock_browser.delete_method.assert_called_once_with(
        "OrderLine",
        "total",
        True,
    )
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    ) == ["description"]


@with_fixtures(SwordfishGuiFixture)
def test_selecting_method_opens_editor_tab(fixture):
    """Choosing a method from the method list opens a new editor tab
    containing that method's source code."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 1
    tab_text = notebook.tab(notebook.tabs()[0], "text")
    assert tab_text == "total"


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_source_shows_line_numbers(fixture):
    """AI: Method source editors display a synchronized line-number column."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert line_numbers[:2] == ["1", "2"]

    tab.code_panel.text_editor.insert("end", "\n    ^42")
    fixture.root.update()

    updated_line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert updated_line_numbers[:3] == ["1", "2", "3"]
    tab.code_panel.text_editor.mark_set(tk.INSERT, "2.4")
    tab.code_panel.cursor_position_indicator.update_position()
    assert tab.code_panel.cursor_position_label.cget("text") == "Ln 2, Col 5"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_already_open_method_brings_its_tab_to_fore(fixture):
    """Re-selecting a method that already has an open tab switches to that
    tab rather than opening a duplicate."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 2
    selected_tab = notebook.select()
    assert notebook.tab(selected_tab, "text") == "total"


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_back_and_forward_navigate_method_history(fixture):
    """AI: Back and Forward should move through the selected-method trail like browser navigation."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    editor.back_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "total"

    editor.forward_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "description"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "description"


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_history_list_jumps_to_selected_entry(fixture):
    """AI: Choosing an entry in method history should jump directly to that earlier method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    history_values = editor.history_combobox.cget("values")
    matching_indices = [
        index
        for index, value in enumerate(history_values)
        if "OrderLine>>total" in value
    ]
    target_index = matching_indices[0]

    editor.history_combobox.current(target_index)
    editor.history_combobox.event_generate("<<ComboboxSelected>>")
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "total"


@with_fixtures(SwordfishGuiFixture)
def test_saving_method_compiles_to_gemstone(fixture):
    """Saving an open editor tab sends the current source to GemstoneBrowserSession
    for compilation."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^42")
    tab.save()

    fixture.mock_browser.compile_method.assert_called_with(
        "OrderLine", True, "total\n    ^42"
    )


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_save_and_close_for_open_tab(fixture):
    """AI: Right-clicking in an editor text area exposes Save and Close actions for the current tab."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Jump to Class" in command_labels
    assert "Save" in command_labels
    assert "Close" in command_labels
    assert "Set Breakpoint Here" in command_labels
    assert "Clear Breakpoint Here" in command_labels
    assert "Implementors" in command_labels
    assert "Senders" in command_labels
    assert "Find Implementors" not in command_labels
    assert "Find Senders" not in command_labels
    assert "Select All" in command_labels
    assert "Copy" in command_labels
    assert "Paste" in command_labels
    assert "Undo" in command_labels
    assert "Preview Rename Method" not in command_labels
    assert "Preview Move Method" not in command_labels
    assert "Preview Add Parameter" not in command_labels
    assert "Preview Remove Parameter" not in command_labels
    assert "Preview Extract Method" not in command_labels
    assert "Preview Inline Method" not in command_labels
    assert "Method Sends" not in command_labels
    assert "Method Structure" not in command_labels
    assert "Method Control Flow" not in command_labels
    assert "Method AST" not in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_set_breakpoint_command_from_text_context_menu_uses_method_context(
    fixture,
):
    """AI: Setting a breakpoint from method editor context menu should target the selected method context and cursor offset."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    fixture.session_record.set_breakpoint = Mock(return_value={"breakpoint_id": "bp-1"})

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Set Breakpoint Here")

    fixture.session_record.set_breakpoint.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        ANY,
    )


@with_fixtures(SwordfishGuiFixture)
def test_method_source_displays_breakpoint_markers_for_existing_breakpoints(
    fixture,
):
    """AI: Method editor should visibly tag source locations where breakpoints already exist."""
    fixture.mock_browser.list_breakpoints.return_value = [
        {
            "breakpoint_id": "bp-1",
            "class_name": "OrderLine",
            "show_instance_side": True,
            "method_selector": "total",
            "source_offset": 1,
            "step_point": 1,
        }
    ]
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    breakpoint_ranges = tab.code_panel.text_editor.tag_ranges("breakpoint_marker")

    assert len(breakpoint_ranges) == 2


@with_fixtures(SwordfishGuiFixture)
def test_clear_breakpoint_command_from_text_context_menu_uses_method_context(
    fixture,
):
    """AI: Clearing a breakpoint from method editor context menu should target the selected method context and cursor offset."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    fixture.session_record.clear_breakpoint_at = Mock(
        return_value={"breakpoint_id": "bp-1"}
    )

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Clear Breakpoint Here")

    fixture.session_record.clear_breakpoint_at.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        ANY,
    )


@with_fixtures(SwordfishGuiFixture)
def test_set_breakpoint_reports_nearest_executable_location_when_snapped(
    fixture,
):
    """AI: Setting a breakpoint should explain when the cursor location is snapped to a nearby executable offset."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.mark_set(tk.INSERT, "1.2")
    fixture.session_record.set_breakpoint = Mock(
        return_value={
            "breakpoint_id": "bp-1",
            "class_name": "OrderLine",
            "show_instance_side": True,
            "method_selector": "total",
            "source_offset": 8,
            "step_point": 2,
        }
    )
    with patch("reahl.swordfish.main.messagebox") as mock_messagebox:
        tab.code_panel.set_breakpoint_at_cursor()

    mock_messagebox.showinfo.assert_called_once()
    showinfo_message = mock_messagebox.showinfo.call_args.args[1]
    assert "nearest executable location" in showinfo_message


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_run_and_inspect_for_selected_text_in_open_tab(
    fixture,
):
    """AI: Selecting method source text should expose Run and Inspect in the editor context menu."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4\n5 + 6")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Run" in command_labels
    assert "Inspect" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_graph_inspect_for_selected_text_in_open_tab(
    fixture,
):
    """AI: Selecting method source text should expose Graph Inspect in the editor context menu."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4\n5 + 6")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Graph Inspect" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from method source should launch class-reference lookup for the selected class name."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.application.open_find_dialog_for_class = Mock()
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "OrderLine")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.9")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    tab.code_panel.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_inspect_command_from_method_source_context_menu_opens_inspector_for_selection(
    fixture,
):
    """AI: Choosing Inspect from method source context menu should evaluate selected source and open Inspector."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    inspected_object = make_mock_gemstone_object("Integer", "7", oop=3004)
    fixture.mock_browser.run_code.return_value = inspected_object
    tab.code_panel.application.open_inspector_for_object = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Inspect")

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    tab.code_panel.application.open_inspector_for_object.assert_called_with(
        inspected_object,
    )


@with_fixtures(SwordfishGuiFixture)
def test_graph_inspect_command_from_method_source_context_menu_opens_graph_for_selection(
    fixture,
):
    """AI: Choosing Graph Inspect from method source context menu should evaluate selected source and open Graph on the result."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    inspected_object = make_mock_gemstone_object("Integer", "7", oop=3004)
    fixture.mock_browser.run_code.return_value = inspected_object
    tab.code_panel.application.open_graph_inspector_for_object = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Graph Inspect")

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    tab.code_panel.application.open_graph_inspector_for_object.assert_called_with(
        inspected_object,
    )


@with_fixtures(SwordfishGuiFixture)
def test_save_command_from_text_context_menu_compiles_to_gemstone(fixture):
    """AI: Choosing Save from text context menu compiles the current editor contents."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^99")

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Save")

    fixture.mock_browser.compile_method.assert_called_with(
        "OrderLine", True, "total\n    ^99"
    )


@with_fixtures(SwordfishGuiFixture)
def test_close_command_from_text_context_menu_closes_the_tab(fixture):
    """AI: Choosing Close from text context menu removes the current method tab."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Close")

    assert (
        "OrderLine",
        True,
        "total",
    ) not in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_jump_to_class_command_from_text_context_menu_syncs_browser_selection(
    fixture,
):
    """AI: Choosing Jump to Class from a method tab synchronizes package/class/side/category/method browser selections to that method context."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    fixture.browser_window.classes_widget.selection_var.set("class")
    fixture.root.update()
    assert fixture.browser_window.classes_widget.selection_var.get() == "class"

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Jump to Class")

    assert fixture.session_record.selected_package == "Kernel"
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.show_instance_side is True
    assert fixture.session_record.selected_method_category == "accessing"
    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.browser_window.classes_widget.selection_var.get() == "instance"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.packages_widget.selection_list.selection_listbox
        )
        == "Kernel"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.classes_widget.selection_list.selection_listbox
        )
        == "OrderLine"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "accessing"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.methods_widget.selection_list.selection_listbox
        )
        == "total"
    )


@with_fixtures(SwordfishGuiFixture)
def test_text_editor_context_menu_paste_replaces_selected_text_and_undo_restores_it(
    fixture,
):
    """Pasting from the editor context menu replaces selected text and Undo restores the previous source."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "alpha beta")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.6", "1.10")

    fixture.root.clipboard_clear()
    fixture.root.clipboard_append("gamma")

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Paste")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha gamma"

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Undo")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha beta"

    tab.code_panel.text_editor.tag_add(tk.SEL, "1.6", "1.10")
    tab.code_panel.replace_selected_text_editor_before_typing(
        types.SimpleNamespace(state=0, char="q", keysym="q"),
    )
    tab.code_panel.text_editor.insert(tk.INSERT, "q")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha q"


@with_fixtures(SwordfishGuiFixture)
def test_selector_for_navigation_uses_full_keyword_selector_from_selected_send_fragment(
    fixture,
):
    """AI: Selecting a keyword send fragment with arguments should resolve to the full keyword selector token sequence."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert(
        "1.0",
        "total\n" "    ^self _twoArgInstPrim: 4 with: srcByteObj with: destByteObj",
    )
    selection_start = tab.code_panel.text_editor.search(
        "_twoArgInstPrim:",
        "1.0",
        stopindex="end",
    )
    selection_end = tab.code_panel.text_editor.search(
        "destByteObj",
        "1.0",
        stopindex="end",
    )
    tab.code_panel.text_editor.tag_add(
        tk.SEL,
        selection_start,
        selection_end,
    )

    resolved_selector = tab.code_panel.selector_for_navigation()

    assert resolved_selector == "_twoArgInstPrim:with:with:"


@with_fixtures(SwordfishGuiFixture)
def test_opening_hierarchy_tab_builds_and_expands_tree_for_selected_class(fixture):
    """AI: Switching to hierarchy view should show superclass/child structure and expand to the selected class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )

    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    order_line_item = child_with_text(order_item, "OrderLine")

    assert tree.selection() == (order_line_item,)
    assert tree.item(object_item, "open")
    assert tree.item(order_item, "open")
    assert tree.set(order_line_item, "class_category") == "Kernel"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_class_in_hierarchy_selects_default_category_and_refreshes_methods(
    fixture,
):
    """AI: Selecting a class in hierarchy view should auto-select a method category and refresh method views."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    child_with_text(order_item, "OrderLine")
    classes_widget.select_class(
        "OrderLine",
        selection_source="hierarchy",
        class_category="Kernel",
    )
    fixture.root.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_method_category == "all"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox,
        )
        == "all"
    )
    method_entries = list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert method_entries == ["total", "description"]


@with_fixtures(SwordfishGuiFixture)
def test_show_class_definition_displays_and_updates_for_selected_class(fixture):
    """AI: Enabling class definition view should render the selected class definition and refresh when selection changes."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    classes_widget = fixture.browser_window.classes_widget
    assert (
        str(classes_widget.class_definition_frame)
        not in classes_widget.class_content_paned.panes()
    )
    assert str(classes_widget.selection_list.master) == str(
        classes_widget.classes_notebook
    )
    assert str(classes_widget.class_controls_frame.master) == str(classes_widget)
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1
    initial_requested_width = classes_widget.winfo_reqwidth()
    assert (
        classes_widget.class_radiobutton.grid_info()["row"]
        == classes_widget.instance_radiobutton.grid_info()["row"]
        == classes_widget.show_class_definition_checkbox.grid_info()["row"]
        == 0
    )
    assert int(classes_widget.instance_radiobutton.grid_info()["column"]) == 0
    assert int(classes_widget.class_radiobutton.grid_info()["column"]) == 1
    classes_widget.show_class_definition_var.set(True)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    assert (
        str(classes_widget.class_definition_frame)
        in classes_widget.class_content_paned.panes()
    )
    shown_requested_width = classes_widget.winfo_reqwidth()
    assert shown_requested_width <= initial_requested_width + 10
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1
    classes_widget.class_content_paned.sashpos(0, 150)
    fixture.root.update()
    sash_position_after_drag = classes_widget.class_content_paned.sashpos(0)

    rendered_definition = classes_widget.class_definition_text.get(
        "1.0",
        "end",
    ).strip()
    rendered_line_numbers = (
        classes_widget.class_definition_line_number_column.line_numbers_text.get(
            "1.0",
            "end-1c",
        ).splitlines()
    )
    assert rendered_line_numbers[:3] == ["1", "2", "3"]
    classes_widget.class_definition_text.mark_set(tk.INSERT, "2.3")
    classes_widget.class_definition_cursor_position_indicator.update_position()
    assert (
        classes_widget.class_definition_cursor_position_label.cget("text")
        == "Ln 2, Col 4"
    )
    assert "Order subclass: 'OrderLine'" in rendered_definition
    assert "instVarNames: #(amount quantity)" in rendered_definition
    assert "inDictionary: Kernel" in rendered_definition

    fixture.browser_window.classes_widget.selection_list.selection_listbox.selection_clear(
        0,
        "end",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "Order",
    )
    fixture.root.update()
    updated_definition = classes_widget.class_definition_text.get(
        "1.0",
        "end",
    ).strip()
    assert "Object subclass: 'Order'" in updated_definition
    assert "instVarNames: #(lines)" in updated_definition

    classes_widget.show_class_definition_var.set(False)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    assert (
        str(classes_widget.class_definition_frame)
        not in classes_widget.class_content_paned.panes()
    )
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1

    classes_widget.show_class_definition_var.set(True)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    restored_sash_position = classes_widget.class_content_paned.sashpos(0)
    assert abs(restored_sash_position - sash_position_after_drag) <= 5


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_checkbox_shows_class_hierarchy(fixture):
    """AI: Enabling method inheritance view should show the selected method's superclass chain as class names only."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    assert str(methods_widget.controls_frame.master) == str(methods_widget)
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1
    assert (
        str(methods_widget.method_hierarchy_frame)
        not in methods_widget.method_content_paned.panes()
    )
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    assert (
        str(methods_widget.method_hierarchy_frame)
        in methods_widget.method_content_paned.panes()
    )
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1
    assert fixture.session_record.selected_method_symbol == "total"
    method_hierarchy_tree = methods_widget.method_hierarchy_tree
    root_item_ids = method_hierarchy_tree.get_children("")
    assert len(root_item_ids) == 1
    assert method_hierarchy_tree.item(root_item_ids[0], "text") == "Object"
    fixture.root.update()

    tree = methods_widget.method_hierarchy_tree
    root_item_ids = tree.get_children("")
    assert len(root_item_ids) == 1
    object_item = root_item_ids[0]
    order_item_ids = tree.get_children(object_item)
    assert len(order_item_ids) == 1
    order_item = order_item_ids[0]
    order_line_item_ids = tree.get_children(order_item)
    assert len(order_line_item_ids) == 1
    order_line_item = order_line_item_ids[0]

    assert tree.item(object_item, "text") == "Object"
    assert tree.item(order_item, "text") == "Order"
    assert tree.item(order_line_item, "text") == "OrderLine"
    assert tree.selection() == (order_line_item,)
    methods_widget.show_method_hierarchy_var.set(False)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    assert (
        str(methods_widget.method_hierarchy_frame)
        not in methods_widget.method_content_paned.panes()
    )
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1


@with_fixtures(SwordfishGuiFixture)
def test_methods_pane_does_not_show_add_method_button(fixture):
    """AI: Method creation should be offered through context menu actions, not a permanent button in the methods pane."""
    methods_widget = fixture.browser_window.methods_widget
    assert not hasattr(methods_widget, "add_method_button")


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_hierarchy_refreshes_on_method_selection_change(fixture):
    """AI: Selecting a different method in the methods list should immediately refresh inheritance analysis for the new selector."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.mock_browser.get_compiled_method.reset_mock()

    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, "end")
    fixture.select_in_listbox(
        methods_listbox,
        "description",
    )

    expected_calls = [
        call("Object", "description", True),
        call("Order", "description", True),
        call("OrderLine", "description", True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_updates_after_explicit_method_click_from_hierarchy_class_view(
    fixture,
):
    """AI: With class selected from hierarchy view and no method selected, clicking a method should refresh method inheritance for that method."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    classes_widget.select_class(
        "OrderLine",
        selection_source="hierarchy",
        class_category="Kernel",
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol is None
    assert fixture.session_record.selected_method_category == "all"

    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    assert not methods_widget.method_hierarchy_tree.get_children("")

    fixture.mock_browser.get_compiled_method.reset_mock()
    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, "end")
    fixture.select_in_listbox(
        methods_listbox,
        "total",
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    expected_calls = [
        call("Object", "total", True),
        call("Order", "total", True),
        call("OrderLine", "total", True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)
    assert methods_widget.method_hierarchy_tree.get_children("")


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
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    assert fixture.session_record.selected_method_category == "accessing"

    fixture.browser_window.classes_widget.switch_side()
    fixture.root.update()

    assert fixture.session_record.selected_method_category is None


class FakeGemstoneError(GemstoneError):
    """AI: Minimal GemstoneError for testing — bypasses the real constructor
    which requires an active session and a C error structure."""

    def __init__(self):
        pass

    def __str__(self):
        return "AI: Simulated Smalltalk error"

    @property
    def context(self):
        return None


class FakeCompileGemstoneError(GemstoneError):
    """AI: Minimal compile error carrying GemStone-like structured arguments."""

    def __init__(self, source_text, source_offset):
        self.source_text = source_text
        self.source_offset = source_offset

    def __str__(self):
        return "a CompileError occurred (error 1001), unexpected token"

    @property
    def number(self):
        return 1001

    @property
    def args(self):
        return ([[1034, self.source_offset, "unexpected token"]], self.source_text)

    @property
    def context(self):
        return None


class SwordfishAppFixture(Fixture):
    @set_up
    def create_app(self):
        self.mock_gemstone_session = Mock()
        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        self.mock_browser.list_categories.return_value = ["Kernel", "Collections"]
        self.mock_browser.list_dictionaries.return_value = [
            "Kernel",
            "Collections",
        ]
        self.mock_browser.list_classes_in_category.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.list_classes_in_dictionary.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.rowan_installed.return_value = False
        self.mock_browser.list_rowan_packages.return_value = []
        self.mock_browser.list_classes_in_rowan_package.return_value = []
        self.mock_browser.list_method_categories.return_value = ["accessing"]
        self.mock_browser.list_methods.return_value = ["total"]
        self.mock_browser.list_breakpoints.return_value = []
        self.mock_browser.get_method_category.return_value = "accessing"
        class_definitions = {
            "OrderLine": {
                "class_name": "OrderLine",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["amount", "quantity"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Order": {
                "class_name": "Order",
                "superclass_name": "Object",
                "package_name": "Kernel",
                "inst_var_names": ["lines"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Object": {
                "class_name": "Object",
                "superclass_name": None,
                "package_name": "Kernel",
                "inst_var_names": [],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
        }

        def get_class_definition(class_name):
            class_definition = class_definitions.get(class_name)
            if class_definition is None:
                raise GemstoneDomainException("Unknown class_name.")
            return class_definition

        self.mock_browser.get_class_definition.side_effect = get_class_definition

        # AI: Chained mock for EditorTab.repopulate() which calls
        # get_compiled_method().sourceString().to_py
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = "total\n    ^1"
        self.mock_browser.get_compiled_method.return_value = mock_method

        # AI: Bypass GemstoneSessionRecord.__init__ (which opens a live GemStone
        # connection) by using __new__ and manually setting all instance variables.
        self.session_record = GemstoneSessionRecord.__new__(GemstoneSessionRecord)
        self.session_record.gemstone_session = self.mock_gemstone_session
        self.session_record.gemstone_browser_session = self.mock_browser
        self.session_record.selected_package = None
        self.session_record.selected_dictionary = None
        self.session_record.selected_class = None
        self.session_record.selected_method_category = None
        self.session_record.selected_method_symbol = None
        self.session_record.show_instance_side = True
        self.session_record.browse_mode = "dictionaries"

        self.app = Swordfish()
        self.app.withdraw()
        self.app.update()

    @tear_down
    def destroy_app(self):
        self.app.destroy()

    def simulate_login(self):
        """AI: Publish LoggedInSuccessfully to transition the app to the
        browser interface without going through the real login dialog."""
        self.app.event_queue.publish("LoggedInSuccessfully", self.session_record)
        self.app.update()
        self.mock_browser.reset_mock()


@with_fixtures(SwordfishAppFixture)
def test_successful_login_switches_to_browser_interface(fixture):
    """Providing valid credentials causes the app to transition from the
    login screen to the main browser interface with a notebook visible."""
    with patch.object(
        GemstoneSessionRecord, "log_in_linked", return_value=fixture.session_record
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert fixture.app.is_logged_in
    assert fixture.app.notebook is not None


@with_fixtures(SwordfishAppFixture)
def test_login_screen_defaults_stone_name_to_gs64stone(fixture):
    """AI: The login screen should prefill stone name with gs64stone when no CLI argument is supplied."""
    assert fixture.app.login_frame.stone_name_entry.get() == "gs64stone"


@with_fixtures(SwordfishAppFixture)
def test_swordfish_custom_default_stone_name_prefills_login_field(fixture):
    """AI: A configured default stone name should be shown in the login screen stone field."""
    custom_app = Swordfish(default_stone_name="customStone")
    custom_app.withdraw()
    custom_app.update()
    assert custom_app.login_frame.stone_name_entry.get() == "customStone"
    custom_app.destroy()


def test_run_application_uses_default_stone_name_when_arg_not_given():
    """AI: run_application should construct Swordfish with gs64stone by default and leave embedded MCP stopped."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop") as swordfish_mainloop:
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish"]):
                    Swordfish.run()
    init_swordfish.assert_called_once()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["default_stone_name"] == "gs64stone"
    assert not swordfish_call_arguments["start_embedded_mcp"]
    assert swordfish_call_arguments["mcp_runtime_config"].mcp_host == "127.0.0.1"
    swordfish_mainloop.assert_called_once()


def test_run_application_uses_cli_stone_name_when_given():
    """AI: run_application should pass an explicitly provided stone name into Swordfish with embedded MCP stopped."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop") as swordfish_mainloop:
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish", "myStone"]):
                    Swordfish.run()
    init_swordfish.assert_called_once()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["default_stone_name"] == "myStone"
    assert not swordfish_call_arguments["start_embedded_mcp"]
    swordfish_mainloop.assert_called_once()


def test_run_application_uses_saved_mcp_config_when_no_cli_runtime_overrides():
    """AI: run_application should load saved MCP runtime settings when no explicit MCP CLI overrides are supplied."""
    saved_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        require_gemstone_ast=True,
        mcp_host="10.0.0.5",
        mcp_port=9177,
        mcp_http_path="/saved",
    )
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=saved_runtime_config,
            ):
                with patch("sys.argv", ["swordfish"]):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    resolved_runtime_config = swordfish_call_arguments["mcp_runtime_config"]
    assert resolved_runtime_config.allow_eval_arbitrary
    assert resolved_runtime_config.allow_source_write
    assert resolved_runtime_config.allow_ide_read
    assert resolved_runtime_config.allow_ide_write
    assert resolved_runtime_config.allow_commit
    assert resolved_runtime_config.allow_tracing
    assert resolved_runtime_config.require_gemstone_ast
    assert resolved_runtime_config.mcp_host == "10.0.0.5"
    assert resolved_runtime_config.mcp_port == 9177
    assert resolved_runtime_config.mcp_http_path == "/saved"


def test_run_application_cli_runtime_overrides_take_precedence_over_saved_mcp_config():
    """AI: Explicit MCP CLI flags should override matching saved MCP config fields while leaving the rest unchanged."""
    saved_runtime_config = McpRuntimeConfig(
        allow_source_read=False,
        allow_eval_arbitrary=False,
        allow_source_write=True,
        allow_ide_read=False,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=True,
        require_gemstone_ast=False,
        mcp_host="10.0.0.5",
        mcp_port=9177,
        mcp_http_path="/saved",
    )
    resolved_runtime_config = saved_runtime_config.copy()
    resolved_runtime_config.update_with(
        allow_eval_arbitrary=True,
        allow_source_read=True,
        allow_ide_read=True,
        mcp_host="127.0.0.1",
        mcp_port=8123,
    )
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=resolved_runtime_config,
            ):
                with patch(
                    "sys.argv",
                    [
                        "swordfish",
                        "--allow-eval-arbitrary",
                        "--allow-source-read",
                        "--allow-ide-read",
                        "--mcp-host",
                        "127.0.0.1",
                        "--mcp-port",
                        "8123",
                    ],
                ):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    resolved_runtime_config = swordfish_call_arguments["mcp_runtime_config"]
    assert resolved_runtime_config.allow_eval_arbitrary
    assert resolved_runtime_config.allow_source_read
    assert resolved_runtime_config.allow_source_write
    assert resolved_runtime_config.allow_ide_read
    assert not resolved_runtime_config.allow_ide_write
    assert not resolved_runtime_config.allow_commit
    assert resolved_runtime_config.allow_tracing
    assert not resolved_runtime_config.require_gemstone_ast
    assert resolved_runtime_config.mcp_host == "127.0.0.1"
    assert resolved_runtime_config.mcp_port == 8123
    assert resolved_runtime_config.mcp_http_path == "/saved"


def test_run_application_starts_headless_mcp_when_headless_flag_is_set():
    """AI: --headless-mcp should run only the MCP server and not construct the GUI."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig()
            with patch.object(McpServerController, "run") as run_mcp:
                with patch("sys.argv", ["swordfish", "--headless-mcp"]):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once()


def test_run_application_passes_streamable_http_configuration_to_mcp():
    """AI: headless mode should pass streamable-http host/port/path options into MCP startup arguments."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig(
                mcp_host="127.0.0.1",
                mcp_port=9177,
                mcp_http_path="/running-ide",
            )
            with patch.object(McpServerController, "run") as run_mcp:
                with patch(
                    "sys.argv",
                    [
                        "swordfish",
                        "--headless-mcp",
                        "--transport",
                        "streamable-http",
                        "--mcp-host",
                        "127.0.0.1",
                        "--mcp-port",
                        "9177",
                        "--mcp-http-path",
                        "/running-ide",
                    ],
                ):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once_with("streamable-http")


def test_run_application_supports_legacy_headless_mode_argument():
    """AI: Legacy --mode mcp-headless still maps to headless MCP startup."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig()
            with patch.object(McpServerController, "run") as run_mcp:
                with patch("sys.argv", ["swordfish", "--mode", "mcp-headless"]):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once()


def test_save_and_load_mcp_runtime_config_uses_xdg_home_location():
    """AI: MCP runtime config should persist under XDG config home and round-trip all permission flags."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary_directory}):
            runtime_config = McpRuntimeConfig(
                allow_source_read=True,
                allow_eval_arbitrary=True,
                allow_source_write=True,
                allow_ide_read=True,
                allow_ide_write=True,
                allow_commit=True,
                allow_tracing=True,
                require_gemstone_ast=True,
                mcp_host="127.0.0.1",
                mcp_port=8123,
                mcp_http_path="/saved",
            )
            configuration_store = McpConfigurationStore()
            configuration_store.save(runtime_config)
            loaded_runtime_config = configuration_store.load()
            expected_config_path = os.path.join(
                temporary_directory,
                "swordfish",
                "mcp.json",
            )
            assert configuration_store.config_file_path() == expected_config_path
            assert loaded_runtime_config is not None
            assert loaded_runtime_config.to_dict() == runtime_config.to_dict()


def test_run_mcp_server_passes_streamable_http_options_to_create_server():
    """AI: MCP startup should forward host/port/path options to create_server and run with the requested transport."""
    arguments = types.SimpleNamespace(
        allow_source_read=True,
        allow_eval_arbitrary=False,
        allow_source_write=True,
        allow_test_execution=False,
        allow_ide_read=True,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=True,
        require_gemstone_ast=False,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/running-ide",
        transport="streamable-http",
    )
    configuration_store = McpConfigurationStore()
    runtime_config = configuration_store.config_from_arguments(arguments)
    mcp_server_controller = McpServerController(None, runtime_config)
    with patch("reahl.swordfish.main.create_server") as create_server:
        mock_server = Mock()
        create_server.return_value = mock_server
        mcp_server_controller.run(arguments.transport)
    create_server.assert_called_once_with(
        allow_source_read=True,
        allow_source_write=True,
        allow_eval_arbitrary=False,
        allow_test_execution=False,
        allow_ide_read=True,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=True,
        integrated_session_state=None,
        require_gemstone_ast=False,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_streamable_http_path="/running-ide",
    )
    mock_server.run.assert_called_once_with(transport="streamable-http")


@with_fixtures(SwordfishAppFixture)
def test_configure_mcp_server_updates_and_saves_config_without_forcing_restart(
    fixture,
):
    """AI: MCP config dialog apply should persist settings and defer applying them to running MCP until restart."""
    fixture.simulate_login()
    updated_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        require_gemstone_ast=True,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/updated",
    )
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.applied_runtime_config = (
            fixture.app.mcp_runtime_config.copy()
        )
    fake_dialog = types.SimpleNamespace(result=updated_runtime_config)

    with patch("reahl.swordfish.main.McpConfigurationDialog", return_value=fake_dialog):
        with patch.object(fixture.app, "wait_window") as wait_window:
            with patch.object(
                fixture.app.mcp_server_controller,
                "stop",
            ) as stop_server:
                with patch.object(fixture.app, "start_mcp_server") as start_server:
                    with patch(
                        "reahl.swordfish.main.McpServerController.save_configuration"
                    ) as save_configuration:
                        fixture.app.configure_mcp_server_from_menu()

    wait_window.assert_called_once_with(fake_dialog)
    stop_server.assert_not_called()
    start_server.assert_not_called()
    save_configuration.assert_called_once()
    assert fixture.app.mcp_runtime_config.to_dict() == updated_runtime_config.to_dict()
    assert fixture.app.embedded_mcp_server_status()["restart_required_for_config"]


@with_fixtures(SwordfishAppFixture)
def test_collaboration_status_mentions_restart_when_running_config_is_outdated(
    fixture,
):
    """AI: Collaboration status should tell the user to restart MCP when config changed while MCP is running."""
    fixture.simulate_login()
    configured_runtime_config = McpRuntimeConfig(
        mcp_host="127.0.0.1",
        mcp_port=9100,
        mcp_http_path="/configured",
    )
    active_runtime_config = McpRuntimeConfig(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        mcp_http_path="/mcp",
    )
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.starting = False
        fixture.app.mcp_server_controller.stopping = False
        fixture.app.mcp_server_controller.runtime_config = configured_runtime_config
        fixture.app.mcp_server_controller.applied_runtime_config = active_runtime_config

    fixture.app.refresh_collaboration_status()
    fixture.app.update()

    assert "MCP config changed; stop and start MCP to apply latest settings." in (
        fixture.app.collaboration_status_text.get()
    )


@with_fixtures(SwordfishAppFixture)
def test_failed_login_shows_error_label(fixture):
    """If login credentials are rejected, the login frame stays visible and
    shows a red error label describing the failure instead of the browser."""
    with patch.object(
        GemstoneSessionRecord,
        "log_in_linked",
        side_effect=DomainException("Bad credentials"),
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame.error_label is not None
    assert "Bad credentials" in fixture.app.login_frame.error_label.cget("text")


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
def test_login_layout_is_consistent_before_and_after_logout(fixture):
    """AI: The login form layout should stay compact and anchored after returning from the main app."""
    initial_login_frame = fixture.app.login_frame
    assert int(initial_login_frame.grid_rowconfigure(0)["weight"]) == 1
    assert int(initial_login_frame.grid_rowconfigure(1)["weight"]) == 0
    assert initial_login_frame.form_frame.grid_info()["sticky"] == "n"
    assert int(initial_login_frame.form_frame.grid_columnconfigure(1)["weight"]) == 1

    fixture.simulate_login()
    fixture.app.logout()
    fixture.app.update()

    returned_login_frame = fixture.app.login_frame
    assert int(returned_login_frame.grid_rowconfigure(0)["weight"]) == 1
    assert int(returned_login_frame.grid_rowconfigure(1)["weight"]) == 0
    assert returned_login_frame.form_frame.grid_info()["sticky"] == "n"
    assert int(returned_login_frame.form_frame.grid_columnconfigure(1)["weight"]) == 1


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

        def on_busy_state_changed(
            self,
            is_busy=False,
            operation_name="",
            busy_lease_token=None,
        ):
            self.events.append((is_busy, operation_name))

    listener = BusyListener()
    fixture.app.event_queue.subscribe(
        "McpBusyStateChanged",
        listener.on_busy_state_changed,
    )

    fixture.app.last_mcp_busy_state = fixture.app.integrated_session_state.is_mcp_busy()
    fixture.app.integrated_session_state.begin_mcp_operation("gs_eval")
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (True, "gs_eval")

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (False, "")


@with_fixtures(SwordfishAppFixture)
def test_mcp_busy_state_disables_run_and_session_controls(fixture):
    """AI: When MCP is busy, Run and Session controls are visually disabled and re-enabled when idle."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()

    fixture.app.integrated_session_state.begin_mcp_operation("gs_apply_rename_method")
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget("state")) == tk.DISABLED
    assert str(fixture.app.run_tab.debug_button.cget("state")) == tk.DISABLED
    assert fixture.app.run_tab.source_text.cget("state") == tk.DISABLED
    assert fixture.app.menu_bar.session_menu.entrycget(0, "state") == tk.DISABLED

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget("state")) == tk.NORMAL
    assert str(fixture.app.run_tab.debug_button.cget("state")) == tk.NORMAL
    assert fixture.app.run_tab.source_text.cget("state") == tk.NORMAL
    assert fixture.app.menu_bar.session_menu.entrycget(0, "state") == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_close_run_tab_drops_stale_mcp_busy_callback(fixture):
    """AI: Closing Run tab invalidates callback context so queued busy callbacks cannot touch destroyed widgets."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    fixture.app.publish_mcp_busy_state_event(
        is_busy=True,
        operation_name='gs_eval',
    )
    run_tab.close_tab()

    with expected(NoException):
        fixture.app.update()

    assert fixture.app.run_tab is None


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_contains_start_stop_and_config_commands(fixture):
    """AI: MCP menu should expose start/stop/configure commands for runtime control."""
    mcp_menu = fixture.app.menu_bar.mcp_menu
    labels = menu_command_labels(mcp_menu)
    assert labels == ["Start MCP", "Stop MCP", "Configure MCP"]
    assert mcp_menu.entrycget(0, "state") == tk.NORMAL
    assert mcp_menu.entrycget(1, "state") == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_file_menu_contains_breakpoints_command_when_logged_in(fixture):
    """AI: File menu should expose a Breakpoints dialog action after login."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    file_menu_labels = menu_command_labels(fixture.app.menu_bar.file_menu)
    assert "Breakpoints" in file_menu_labels


@with_fixtures(SwordfishAppFixture)
def test_file_menu_contains_find_implementors_and_senders_shortcuts(
    fixture,
):
    """AI: File menu should include Find shortcuts for implementors and senders directly below Find."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    file_menu_labels = menu_command_labels(fixture.app.menu_bar.file_menu)
    assert "Find" in file_menu_labels
    assert "Implementors" in file_menu_labels
    assert "Senders" in file_menu_labels
    assert file_menu_labels.index("Find") < file_menu_labels.index("Implementors")
    assert file_menu_labels.index("Implementors") < file_menu_labels.index("Senders")


@with_fixtures(SwordfishAppFixture)
def test_file_menu_find_implementors_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: File menu Implementors action should delegate to Swordfish find-implementors handler."""
    fixture.simulate_login()
    file_menu = fixture.app.menu_bar.file_menu
    with patch.object(fixture.app, "open_implementors_dialog") as open_dialog:
        invoke_menu_command_by_label(file_menu, "Implementors")
    open_dialog.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_file_menu_find_senders_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: File menu Senders action should delegate to Swordfish find-senders handler."""
    fixture.simulate_login()
    file_menu = fixture.app.menu_bar.file_menu
    with patch.object(fixture.app, "open_senders_dialog") as open_dialog:
        invoke_menu_command_by_label(file_menu, "Senders")
    open_dialog.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_open_implementors_dialog_configures_find_dialog_for_exact_method_search(
    fixture,
):
    """AI: Opening implementors dialog should configure Find for exact method implementors lookup."""
    with patch.object(fixture.app, "open_find_dialog") as open_find_dialog:
        fixture.app.open_implementors_dialog(method_symbol="total")
    open_find_dialog.assert_called_once_with(
        search_type="method",
        search_query="total",
        run_search=True,
        match_mode="exact",
    )


@with_fixtures(SwordfishAppFixture)
def test_open_senders_dialog_configures_find_dialog_for_exact_method_references(
    fixture,
):
    """AI: Opening senders dialog should configure Find for exact method reference lookup."""
    with patch.object(fixture.app, "open_find_dialog") as open_find_dialog:
        fixture.app.open_senders_dialog(method_symbol="total")
    open_find_dialog.assert_called_once_with(
        search_type="reference",
        search_query="total",
        run_search=True,
        match_mode="exact",
        reference_target="method",
        sender_source_class_name=None,
    )


@with_fixtures(SwordfishAppFixture)
def test_file_menu_breakpoints_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: File menu Breakpoints action should delegate to Swordfish dialog handler."""
    fixture.simulate_login()
    file_menu = fixture.app.menu_bar.file_menu
    with patch.object(fixture.app, "open_breakpoints_dialog") as open_dialog:
        invoke_menu_command_by_label(file_menu, "Breakpoints")
    open_dialog.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_open_breakpoints_dialog_lists_active_breakpoints(fixture):
    """AI: Opening Breakpoints dialog should list the active breakpoints from session record."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )

    fixture.app.open_breakpoints_dialog()
    fixture.app.update()
    dialogs = [
        child
        for child in fixture.app.winfo_children()
        if isinstance(child, BreakpointsDialog)
    ]
    assert dialogs
    dialog = dialogs[0]
    dialog_rows = dialog.breakpoint_list.get_children()
    assert len(dialog_rows) == 1
    row_values = dialog.breakpoint_list.item(dialog_rows[0], "values")
    assert row_values[0] == "OrderLine"
    assert row_values[1] == "instance"
    assert row_values[2] == "total"
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_dialog_double_click_navigates_to_selected_method(
    fixture,
):
    """AI: Double-clicking a breakpoint should navigate browser selection to that method and focus Browser tab."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )

    fixture.app.open_breakpoints_dialog()
    fixture.app.update()
    dialogs = [
        child
        for child in fixture.app.winfo_children()
        if isinstance(child, BreakpointsDialog)
    ]
    assert dialogs
    dialog = dialogs[0]

    dialog.breakpoint_list.focus("bp-1")
    dialog.breakpoint_list.selection_set("bp-1")
    dialog.on_breakpoint_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.session_record.show_instance_side
    selected_tab_text = fixture.app.notebook.tab(
        fixture.app.notebook.select(),
        "text",
    )
    assert selected_tab_text == "Browser"


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_commands_delegate_to_swordfish_handlers(fixture):
    """AI: Selecting MCP menu actions should call corresponding Swordfish command handlers."""
    mcp_menu = fixture.app.menu_bar.mcp_menu
    with patch.object(fixture.app, "start_mcp_server_from_menu") as start_mcp:
        invoke_menu_command_by_label(mcp_menu, "Start MCP")
    start_mcp.assert_called_once()
    with patch.object(fixture.app, "stop_mcp_server_from_menu") as stop_mcp:
        with fixture.app.mcp_server_controller.lock:
            fixture.app.mcp_server_controller.running = True
        fixture.app.menu_bar.update_menus()
        invoke_menu_command_by_label(mcp_menu, "Stop MCP")
    stop_mcp.assert_called_once()
    with patch.object(fixture.app, "configure_mcp_server_from_menu") as configure_mcp:
        invoke_menu_command_by_label(mcp_menu, "Configure MCP")
    configure_mcp.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_reflects_embedded_server_running_state(fixture):
    """AI: MCP menu should disable start and enable stop while embedded MCP is running."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
    fixture.app.menu_bar.update_menus()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    assert mcp_menu.entrycget(0, "state") == tk.DISABLED
    assert mcp_menu.entrycget(1, "state") == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_reflects_embedded_server_stopping_state(fixture):
    """AI: MCP menu should disable start/stop/configure while embedded MCP is stopping."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.stopping = True
    fixture.app.menu_bar.update_menus()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    assert mcp_menu.entrycget(0, "state") == tk.DISABLED
    assert mcp_menu.entrycget(1, "state") == tk.DISABLED
    assert mcp_menu.entrycget(3, "state") == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_start_mcp_menu_action_uses_foreground_activity_feedback(fixture):
    """AI: Starting MCP from menu should use the shared foreground activity feedback path."""
    with patch.object(fixture.app, "start_mcp_server", return_value=True):
        with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
            with patch.object(fixture.app, "end_foreground_activity") as end_activity:
                fixture.app.start_mcp_server_from_menu()
    begin_activity.assert_called_once_with("Starting MCP server...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_stop_mcp_menu_action_uses_foreground_activity_feedback(fixture):
    """AI: Stopping MCP from menu should use the shared foreground activity feedback path."""
    with patch.object(fixture.app, "stop_mcp_server", return_value=True):
        with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
            with patch.object(fixture.app, "end_foreground_activity") as end_activity:
                fixture.app.stop_mcp_server_from_menu()
    begin_activity.assert_called_once_with("Stopping MCP server...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_foreground_activity_feedback_controls_status_and_indicator(fixture):
    """AI: Foreground activity helper should show/hide progress feedback for non-MCP long actions."""
    fixture.simulate_login()

    class ActivityListener:
        def __init__(self):
            self.activity_events = []
            self.indicator_events = []

        def on_activity_changed(self, is_active=False, message=""):
            self.activity_events.append((is_active, message))

        def on_indicator_changed(self, is_visible=False):
            self.indicator_events.append(is_visible)

    listener = ActivityListener()
    fixture.app.event_queue.subscribe(
        "UiActivityChanged",
        listener.on_activity_changed,
    )
    fixture.app.event_queue.subscribe(
        "UiActivityIndicatorChanged",
        listener.on_indicator_changed,
    )

    fixture.app.begin_foreground_activity("Running long action...")
    fixture.app.update()
    assert fixture.app.collaboration_status_text.get() == "Running long action..."
    assert fixture.app.mcp_activity_indicator_visible is True
    assert listener.activity_events[-1] == (True, "Running long action...")
    assert listener.indicator_events[-1] is True

    fixture.app.end_foreground_activity()
    fixture.app.update()
    assert fixture.app.foreground_activity_message == ""
    assert fixture.app.mcp_activity_indicator_visible is False
    assert listener.activity_events[-1] == (False, "")
    assert listener.indicator_events[-1] is False


@with_fixtures(SwordfishAppFixture)
def test_foreground_activity_feedback_advances_indicator_immediately(fixture):
    """AI: Foreground activity should advance the indicator immediately so it remains visible during synchronous work."""
    fixture.simulate_login()
    fixture.app.begin_foreground_activity("Running tests...")
    fixture.app.update_idletasks()

    assert float(fixture.app.mcp_activity_indicator.cget("value")) > 0.0

    fixture.app.end_foreground_activity()


@with_fixtures(SwordfishAppFixture)
def test_indicator_is_hidden_when_mcp_server_is_running_but_idle(fixture):
    """AI: Idle startup status should not show a partially-filled progress indicator when MCP is merely running."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.endpoint_url = "http://127.0.0.1:9177/mcp"
    fixture.simulate_login()
    fixture.app.refresh_collaboration_status()
    fixture.app.update()

    assert fixture.app.mcp_activity_indicator_visible is False
    assert fixture.app.mcp_activity_indicator.winfo_manager() == ""
    assert fixture.app.collaboration_status_text.get().startswith(
        "IDE ready. MCP running at http://127.0.0.1:"
    )


@with_fixtures(SwordfishAppFixture)
def test_run_tab_run_action_uses_foreground_activity_feedback(fixture):
    """AI: Run action should trigger shared foreground activity feedback while code executes."""
    fixture.simulate_login()
    fixture.app.run_code("3 + 4")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
        with patch.object(fixture.app, "end_foreground_activity") as end_activity:
            run_tab.run_code_from_editor()

    begin_activity.assert_called_once_with("Running source...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_result_on_successful_eval(fixture):
    """Running code in the Run tab should populate the result area with the evaluated object's printString."""
    fixture.simulate_login()

    # AI: on_run_complete calls result.asString().to_py to render the result.
    mock_result = Mock()
    mock_result.asString.return_value.to_py = "7"
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code("3 + 4")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    result_content = run_tab.result_text.get("1.0", "end").strip()
    assert result_content == "7"


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_always_shows_enabled_debug_button(fixture):
    """The Run tab should always show an enabled Debug button, even before any run error occurs."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, "debug_button")
    assert run_tab.debug_button.winfo_exists()
    assert not run_tab.debug_button.instate(["disabled"])


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_debug_button_when_code_raises_error(fixture):
    """If run code raises a GemstoneError, the Run tab should still show the Debug button for opening the debugger."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, "debug_button")
    assert run_tab.debug_button.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_run_source_text_shortcuts_replace_selection_and_support_undo(fixture):
    """Run source text supports select/copy/paste/undo shortcuts, and typed input replaces selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.source_text.bind("<Control-a>")
    assert run_tab.source_text.bind("<Control-c>")
    assert run_tab.source_text.bind("<Control-v>")
    assert run_tab.source_text.bind("<Control-z>")

    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "alpha beta")
    run_tab.source_text.tag_add(tk.SEL, "1.6", "1.10")

    fixture.app.clipboard_clear()
    fixture.app.clipboard_append("gamma")
    run_tab.paste_into_source_text()
    assert run_tab.source_text.get("1.0", "end-1c") == "alpha gamma"

    run_tab.undo_source_text()
    assert run_tab.source_text.get("1.0", "end-1c") == "alpha beta"

    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")
    run_tab.replace_selected_source_text_before_typing(
        types.SimpleNamespace(state=0, char="z", keysym="z"),
    )
    run_tab.source_text.insert(tk.INSERT, "z")
    assert run_tab.source_text.get("1.0", "end-1c") == "z beta"

    run_tab.select_all_source_text()
    run_tab.copy_source_selection()
    assert fixture.app.clipboard_get() == "z beta"


@with_fixtures(SwordfishAppFixture)
def test_run_source_editor_shows_line_numbers(fixture):
    """AI: Run source editor displays line numbers that track visible source lines."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert(
        "1.0",
        "alpha\nbeta\ngamma",
    )
    fixture.app.update()

    line_numbers = run_tab.source_line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert line_numbers[:3] == ["1", "2", "3"]
    run_tab.source_text.mark_set(tk.INSERT, "3.2")
    run_tab.source_cursor_position_indicator.update_position()
    assert run_tab.source_cursor_position_label.cget("text") == "Ln 3, Col 3"


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_run_and_inspect_for_selected_text(fixture):
    """Run source context menu exposes Run and Inspect commands that target selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Run" in labels
    assert "Inspect" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_graph_inspect_for_selected_text(fixture):
    """AI: Run source context menu should expose Graph Inspect when source text is selected."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Graph Inspect" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_run_executes_selected_text_only(fixture):
    """Run command in Run source context menu evaluates only the selected source fragment."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    mock_result = Mock()
    mock_result.asString.return_value.to_py = "7"
    fixture.mock_browser.run_code.return_value = mock_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Run")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert run_tab.result_text.get("1.0", "end").strip() == "7"


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_inspect_opens_inspector_for_selected_result(fixture):
    """Inspect command in Run source context menu evaluates selected source and opens Inspector on the result object."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert fixture.app.inspector_tab is not None
    assert isinstance(fixture.app.inspector_tab, InspectorTab)
    assert isinstance(fixture.app.inspector_tab.explorer, Explorer)
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Inspect"


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_graph_inspect_opens_graph_for_selected_result(fixture):
    """AI: Graph Inspect in Run source context menu should evaluate selected source and open the Graph tab on that result."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7", oop=4444)
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Graph Inspect")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert fixture.app.graph_tab is not None
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Graph"
    assert fixture.app.graph_tab.graph_canvas.registry.contains_object(inspected_result)


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_opens_graph_for_oops(fixture):
    """AI: MCP IDE navigation action should resolve requested oops and open those objects in the Graph tab."""
    fixture.simulate_login()
    first_object = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001)
    second_object = make_mock_gemstone_object("Order", "anOrder", oop=3002)
    objects_by_source = {
        "Object _objectForOop: 3001": first_object,
        "Object _objectForOop: 3002": second_object,
    }

    def object_for_source(source):
        return objects_by_source[source]

    fixture.mock_browser.run_code.side_effect = object_for_source
    response = fixture.app.perform_mcp_ide_navigation_action(
        "open_graph_for_oops",
        {
            "oop_labels": ["3001", "3002"],
            "clear_existing": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert response["opened_oops"] == ["3001", "3002"]
    assert response["unresolved_oops"] == []
    assert fixture.app.graph_tab is not None
    registry = fixture.app.graph_tab.graph_canvas.registry
    assert registry.contains_object(first_object)
    assert registry.contains_object(second_object)


@with_fixtures(SwordfishAppFixture)
def test_open_uml_for_class_creates_uml_tab_and_adds_class(fixture):
    """AI: Opening UML for a class should create the UML tab and register that class node."""
    fixture.simulate_login()

    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    assert fixture.app.uml_tab is not None
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "UML"
    assert (
        fixture.app.uml_tab.uml_canvas.registry.class_node_for("OrderLine")
        is not None
    )


@with_fixtures(SwordfishAppFixture)
def test_uml_tab_shows_inheritance_for_added_classes(fixture):
    """AI: Adding related classes to the UML should create one inheritance edge between them."""
    fixture.simulate_login()

    fixture.app.open_uml_for_class("Order")
    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    relationships = fixture.app.uml_tab.uml_canvas.registry.all_relationships()
    inheritance_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 1
    assert inheritance_relationships[0].source_node.class_name == "OrderLine"
    assert inheritance_relationships[0].target_node.class_name == "Order"
    assert inheritance_relationships[0].relationship_style == "direct"


@with_fixtures(SwordfishAppFixture)
def test_uml_tab_shows_inferred_inheritance_for_transitive_ancestors(fixture):
    """AI: Adding a class and a transitive ancestor to the UML should show an inferred inheritance edge."""
    fixture.simulate_login()

    fixture.app.open_uml_for_class("Object")
    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    relationships = fixture.app.uml_tab.uml_canvas.registry.all_relationships()
    inheritance_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 1
    assert inheritance_relationships[0].source_node.class_name == "OrderLine"
    assert inheritance_relationships[0].target_node.class_name == "Object"
    assert inheritance_relationships[0].relationship_style == "inferred"


@with_fixtures(SwordfishAppFixture)
def test_pin_method_in_uml_adds_method_to_class_node(fixture):
    """AI: Pinning a method into UML should add a method entry to that class node."""
    fixture.simulate_login()

    fixture.app.pin_method_in_uml("OrderLine", True, "total")
    fixture.app.update()

    node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("OrderLine")

    assert node is not None
    assert node.pinned_methods == [
        {
            "selector": "total",
            "show_instance_side": True,
            "label": "total",
        }
    ]


@with_fixtures(SwordfishAppFixture)
def test_uml_browse_class_selects_browser_class(fixture):
    """AI: Browsing a UML class should route to the browser class selection flow."""
    fixture.simulate_login()
    fixture.app.handle_find_selection = Mock()

    fixture.app.uml_tab = None
    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    fixture.app.uml_tab.browse_class("OrderLine")
    fixture.app.update()

    fixture.app.handle_find_selection.assert_called_once_with(True, "OrderLine")


@with_fixtures(SwordfishAppFixture)
def test_uml_browse_method_selects_browser_method(fixture):
    """AI: Browsing a pinned UML method should route to the browser method selection flow."""
    fixture.simulate_login()
    fixture.app.handle_sender_selection = Mock()

    fixture.app.pin_method_in_uml("OrderLine", True, "total")
    fixture.app.update()

    node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("OrderLine")
    fixture.app.uml_tab.browse_method("OrderLine", node.pinned_methods[0])
    fixture.app.update()

    fixture.app.handle_sender_selection.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishAppFixture)
def test_uml_method_chooser_lists_and_filters_methods_before_pinning(fixture):
    """AI: UML method selection should offer browser-style category and method filtering before pinning an existing method."""
    fixture.simulate_login()
    def list_method_categories(class_name, show_instance_side):
        if show_instance_side:
            return ["all", "accessing", "testing"]
        return ["all", "class accessing"]

    def list_methods(class_name, method_category, show_instance_side):
        if show_instance_side:
            return ["total", "description"]
        return ["defaultLineClass"]

    fixture.mock_browser.list_method_categories.side_effect = list_method_categories
    fixture.mock_browser.list_methods.side_effect = list_methods
    on_method_selected = Mock()

    dialog = UmlMethodChooserDialog(
        fixture.app,
        fixture.app,
        "OrderLine",
        on_method_selected,
    )
    fixture.app.update()

    category_entries = list(
        dialog.category_selection.selection_listbox.get(0, "end")
    )
    method_entries = list(dialog.method_selection.selection_listbox.get(0, "end"))

    assert category_entries == ["all", "accessing", "testing"]
    assert method_entries == ["total", "description"]

    dialog.method_selection.filter_var.set("tot")
    fixture.app.update()

    filtered_method_entries = list(dialog.method_selection.selection_listbox.get(0, "end"))
    assert filtered_method_entries == ["total"]

    dialog.side_var.set("class")
    dialog.handle_side_changed()
    fixture.app.update()

    class_side_category_entries = list(
        dialog.category_selection.selection_listbox.get(0, "end")
    )
    class_side_method_entries = list(
        dialog.method_selection.selection_listbox.get(0, "end")
    )
    assert class_side_category_entries == ["all", "class accessing"]
    assert class_side_method_entries == ["defaultLineClass"]

    dialog.side_var.set("instance")
    dialog.handle_side_changed()
    fixture.app.update()

    dialog.select_method("total")
    dialog.add_selected_method()
    fixture.app.update()

    on_method_selected.assert_called_once_with("OrderLine", True, "total")


@with_fixtures(SwordfishAppFixture)
def test_uml_add_existing_method_pins_it_on_class_node(fixture):
    """AI: Adding a chosen existing method from UML should pin it on the UML node without invoking method creation."""
    fixture.simulate_login()
    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("OrderLine")

    fixture.app.uml_tab.add_existing_method_to_node(
        "OrderLine",
        True,
        "total",
    )
    fixture.app.update()

    fixture.mock_browser.compile_method.assert_not_called()
    assert node.pinned_methods[0] == {
        "selector": "total",
        "show_instance_side": True,
        "label": "total",
    }


@with_fixtures(SwordfishAppFixture)
def test_uml_association_prompt_adds_target_class_and_relationship(fixture):
    """AI: Adding an association from a UML node should prompt for a target class and create the labeled edge."""
    fixture.simulate_login()
    fixture.app.open_uml_for_class("Order")
    fixture.app.update()
    source_node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("Order")

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="OrderLine",
    ):
        fixture.app.uml_tab.prompt_add_association(source_node, "lines")
        fixture.app.update()

    target_node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("OrderLine")
    relationships = fixture.app.uml_tab.uml_canvas.registry.all_relationships()
    association_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "association"
    ]

    assert target_node is not None
    assert len(association_relationships) == 1
    assert association_relationships[0].source_node is source_node
    assert association_relationships[0].target_node is target_node
    assert association_relationships[0].label == "lines"


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_restores_diagram_after_clear(fixture):
    """AI: Undo after clearing the UML should restore the previously shown classes."""
    fixture.simulate_login()
    fixture.app.open_uml_for_class("Order")
    fixture.app.open_uml_for_class("OrderLine")
    fixture.app.update()

    fixture.app.uml_tab.clear_diagram()
    fixture.app.update()

    assert fixture.app.uml_tab.uml_canvas.registry.all_nodes() == []

    fixture.app.uml_tab.undo_diagram()
    fixture.app.update()

    restored_class_names = [
        node.class_name
        for node in fixture.app.uml_tab.uml_canvas.registry.all_nodes()
    ]
    assert sorted(restored_class_names) == ["Order", "OrderLine"]


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_reverts_association_addition_in_one_step(fixture):
    """AI: Undoing an association add should remove both the edge and any target class added by that action."""
    fixture.simulate_login()
    fixture.app.open_uml_for_class("Order")
    fixture.app.update()
    source_node = fixture.app.uml_tab.uml_canvas.registry.class_node_for("Order")

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="OrderLine",
    ):
        fixture.app.uml_tab.prompt_add_association(source_node, "lines")
        fixture.app.update()

    fixture.app.uml_tab.undo_diagram()
    fixture.app.update()

    remaining_class_names = [
        node.class_name
        for node in fixture.app.uml_tab.uml_canvas.registry.all_nodes()
    ]
    assert remaining_class_names == ["Order"]
    assert fixture.app.uml_tab.uml_canvas.registry.all_relationships() == []


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_reverts_pinned_method_and_added_class_in_one_step(fixture):
    """AI: Undoing the first method pin should remove both the pinned method and the class added for it."""
    fixture.simulate_login()

    fixture.app.pin_method_in_uml("OrderLine", True, "total")
    fixture.app.update()

    fixture.app.uml_tab.undo_diagram()
    fixture.app.update()

    assert fixture.app.uml_tab.uml_canvas.registry.all_nodes() == []


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_selects_class_in_browser(fixture):
    """AI: MCP IDE navigation action should select class context in the browser."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    response = fixture.app.perform_mcp_ide_navigation_action(
        "select_class",
        {
            "class_name": "OrderLine",
            "show_instance_side": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.show_instance_side is True


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_opens_method_in_browser(fixture):
    """AI: MCP IDE navigation action should select method context in the browser."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"

    response = fixture.app.perform_mcp_ide_navigation_action(
        "open_method",
        {
            "class_name": "OrderLine",
            "method_symbol": "total",
            "show_instance_side": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.session_record.selected_method_category == "accessing"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_browser_source_selection(fixture):
    """AI: MCP current-view action should report active browser method source selection and method context."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"
    open_method_response = fixture.app.perform_mcp_ide_navigation_action(
        "open_method",
        {
            "class_name": "OrderLine",
            "method_symbol": "total",
            "show_instance_side": True,
        },
    )
    assert open_method_response["ok"], open_method_response
    method_editor = fixture.app.browser_tab.editor_area_widget
    selected_editor_tab_id = method_editor.editor_notebook.select()
    selected_editor_tab = method_editor.editor_notebook.nametowidget(
        selected_editor_tab_id
    )
    source_text_widget = selected_editor_tab.code_panel.text_editor
    source_text_widget.tag_add(tk.SEL, "1.0", "1.5")
    source_text_widget.mark_set(tk.INSERT, "1.5")

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["active_tab"]["kind"] == "browser"
    assert response["active_source_view"]["kind"] == "browser_method_source"
    browser_source_state = response["active_source_view"]["state"]
    assert browser_source_state["method_context"] == {
        "class_name": "OrderLine",
        "show_instance_side": True,
        "method_symbol": "total",
    }
    assert browser_source_state["selection"]["has_selection"]
    assert browser_source_state["selection"]["selected_text"] == "total"
    assert response["browser_state"]["selected_method_symbol"] == "total"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_sender_find_dialog_state(fixture):
    """AI: MCP current-view action should report sender metadata from an open Find senders dialog."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
                "class_category": "Sales-Core",
                "method_category": "calculating",
                "method_category_is_extension": False,
                "extension_category_name": None,
            },
            {
                "class_name": "OrderAudit",
                "show_instance_side": True,
                "method_selector": "recordTotalChange",
                "class_category": "Auditing-Core",
                "method_category": "*Sales-Core",
                "method_category_is_extension": True,
                "extension_category_name": "Sales-Core",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["find_dialog_state"]["is_open"]
    assert response["find_dialog_state"]["is_sender_reference_search"]
    assert response["find_dialog_state"]["displayed_sender_count"] == 2
    assert {
        "class_name": "OrderAudit",
        "show_instance_side": True,
        "method_selector": "recordTotalChange",
        "class_category": "Auditing-Core",
        "method_category": "*Sales-Core",
        "method_category_is_extension": True,
        "extension_category_name": "Sales-Core",
    } in response["find_dialog_state"]["displayed_senders"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_filters_sender_find_dialog_by_class_category(
    fixture,
):
    """AI: MCP sender filter action should include extension methods when configured to match extension categories."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
                "class_category": "Sales-Core",
                "method_category": "calculating",
                "method_category_is_extension": False,
                "extension_category_name": None,
            },
            {
                "class_name": "OrderAudit",
                "show_instance_side": True,
                "method_selector": "recordTotalChange",
                "class_category": "Auditing-Core",
                "method_category": "*Sales-Core",
                "method_category_is_extension": True,
                "extension_category_name": "Sales-Core",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    include_extensions_response = fixture.app.perform_mcp_ide_navigation_action(
        "filter_senders_in_find_dialog",
        {
            "class_category_filters": ["Sales-Core"],
            "include_extension_method_category_for_class_category": True,
        },
    )
    assert include_extensions_response["ok"], include_extensions_response
    assert include_extensions_response["displayed_sender_count"] == 2
    assert list(dialog.results_listbox.get(0, "end")) == [
        "OrderAudit>>recordTotalChange",
        "OrderLine>>recalculateTotal",
    ]

    exclude_extensions_response = fixture.app.perform_mcp_ide_navigation_action(
        "filter_senders_in_find_dialog",
        {
            "class_category_filters": ["Sales-Core"],
            "include_extension_method_category_for_class_category": False,
        },
    )
    assert exclude_extensions_response["ok"], exclude_extensions_response
    assert exclude_extensions_response["displayed_sender_count"] == 1
    assert list(dialog.results_listbox.get(0, "end")) == ["OrderLine>>recalculateTotal"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_debugger_source_selection(fixture):
    """AI: MCP current-view action should report active debugger frame context and selected source text."""
    fixture.simulate_login()
    debugger_tab = ttk.Frame(fixture.app.notebook)
    debugger_source_widget = tk.Text(debugger_tab)
    debugger_source_widget.insert("1.0", "recalculateTotal\n    ^self total")
    debugger_source_widget.tag_add(tk.SEL, "1.0", "1.10")
    debugger_source_widget.mark_set(tk.INSERT, "1.10")
    selected_frame = types.SimpleNamespace(
        level=2,
        class_name="OrderLine",
        method_name="recalculateTotal",
        step_point_offset=17,
    )
    debugger_tab.code_panel = types.SimpleNamespace(text_editor=debugger_source_widget)
    debugger_tab.get_selected_stack_frame = Mock(return_value=selected_frame)
    debugger_tab.frame_method_context = Mock(
        return_value=("OrderLine", True, "recalculateTotal")
    )
    debugger_tab.is_running = True
    fixture.app.debugger_tab = debugger_tab
    fixture.app.notebook.add(debugger_tab, text="Debugger")
    fixture.app.notebook.select(debugger_tab)
    fixture.app.update()

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["active_tab"]["kind"] == "debugger"
    assert response["active_source_view"]["kind"] == "debugger_method_source"
    debugger_source_state = response["active_source_view"]["state"]
    assert debugger_source_state["method_context"] == {
        "class_name": "OrderLine",
        "show_instance_side": True,
        "method_symbol": "recalculateTotal",
    }
    assert debugger_source_state["selection"]["has_selection"]
    assert debugger_source_state["selection"]["selected_text"] == "recalculat"
    assert debugger_source_state["selected_frame"]["class_name"] == "OrderLine"
    assert debugger_source_state["selected_frame"]["method_name"] == "recalculateTotal"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_delegates_to_debugger_opener(fixture):
    """AI: MCP debugger action should delegate to debugger opening handler."""
    fixture.simulate_login()
    example_exception = RuntimeError("MCP debugger test")

    with patch.object(
        fixture.app,
        "open_debugger_for_mcp_exception",
        return_value={"ok": True, "debugger_opened": True},
    ) as debugger_opener:
        response = fixture.app.perform_mcp_ide_navigation_action(
            "open_debugger_for_exception",
            {
                "exception": example_exception,
                "ask_before_open": True,
            },
        )

    debugger_opener.assert_called_once_with(
        example_exception,
        ask_before_open=True,
    )
    assert response["ok"], response


@with_fixtures(SwordfishAppFixture)
def test_run_inspector_uses_object_summary_as_first_tab_label(fixture):
    """AI: The first inspector tab should identify the inspected object rather than a generic Context label."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "Date today")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    inspected_result = make_mock_gemstone_object("Date", "2023/12/12")
    inspected_result.oop = 2003
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    first_tab_id = inspector_tab.explorer.tabs()[0]
    first_tab_label = inspector_tab.explorer.tab(first_tab_id, "text")
    assert first_tab_label == "2003:Date 2023/12/12"


@with_fixtures(SwordfishAppFixture)
def test_run_inspector_tab_can_be_closed_with_close_button(fixture):
    """The inspector tab opened from Run can be dismissed using its Close Inspector button."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    inspector_tab.close_button.invoke()
    fixture.app.update()

    assert fixture.app.inspector_tab is None
    tab_labels = [
        fixture.app.notebook.tab(tab_id, "text")
        for tab_id in fixture.app.notebook.tabs()
    ]
    assert "Inspect" not in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_tab_places_close_button_to_the_right_of_primary_actions(fixture):
    """AI: Run tab actions keep close on the right so tab controls align with other tabs."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert int(run_tab.button_frame.grid_info()["row"]) == 0
    assert int(run_tab.source_label.grid_info()["row"]) == 1
    assert int(run_tab.source_editor_frame.grid_info()["row"]) == 2

    run_column = int(run_tab.run_button.grid_info()["column"])
    debug_column = int(run_tab.debug_button.grid_info()["column"])
    close_column = int(run_tab.close_button.grid_info()["column"])

    assert run_column < debug_column
    assert debug_column < close_column
    assert run_tab.close_button.cget("text") == "Close"


@with_fixtures(SwordfishAppFixture)
def test_inspector_tab_uses_top_action_row_with_close_button(fixture):
    """AI: Inspector tab places close control in the top action row above explorer content."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    assert int(inspector_tab.actions_frame.grid_info()["row"]) == 0
    assert int(inspector_tab.explorer.grid_info()["row"]) == 1
    assert int(inspector_tab.close_button.grid_info()["row"]) == 0
    assert inspector_tab.close_button.cget("text") == "Close"


@with_fixtures(SwordfishAppFixture)
def test_inspector_tab_navigates_object_history_with_back_and_forward(fixture):
    """AI: Inspector tracks selected inspected objects and supports back/forward navigation through that history."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "anObject")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.8")

    nested_object = make_mock_gemstone_object("Integer", "7", oop=2002)
    inspected_result = make_mock_instance_with_inst_vars(
        "OrderLine",
        "anOrderLine",
        {"child": nested_object},
        oop=2001,
    )
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    assert str(inspector_tab.back_button.cget("state")) == tk.DISABLED
    assert str(inspector_tab.forward_button.cget("state")) == tk.DISABLED

    context_tab_id = inspector_tab.explorer.tabs()[0]
    context_inspector = inspector_tab.explorer.nametowidget(context_tab_id)
    context_row = context_inspector.treeview.get_children()[0]
    context_inspector.treeview.focus(context_row)
    context_inspector.on_item_double_click(None)
    fixture.app.update()

    context_label = inspector_tab.explorer.tab(context_tab_id, "text")
    nested_label = inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
    assert context_label == "2001:OrderLine anOrderLine"
    assert nested_label == "2002:Integer 7"
    assert str(inspector_tab.back_button.cget("state")) == tk.NORMAL
    assert str(inspector_tab.forward_button.cget("state")) == tk.DISABLED

    inspector_tab.back_button.invoke()
    fixture.app.update()

    assert (
        inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
        == context_label
    )
    assert str(inspector_tab.forward_button.cget("state")) == tk.NORMAL

    inspector_tab.forward_button.invoke()
    fixture.app.update()

    assert (
        inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
        == nested_label
    )
    history_labels = list(inspector_tab.history_combobox["values"])
    assert nested_label in history_labels
    assert context_label in history_labels


@with_fixtures(SwordfishAppFixture)
def test_run_result_text_supports_copy_and_has_result_context_menu(fixture):
    """Run result text supports selecting/copying output via shortcuts and context menu actions."""
    fixture.simulate_login()
    mock_result = Mock()
    mock_result.asString.return_value.to_py = "42"
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code("40 + 2")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.result_text.bind("<Control-a>")
    assert run_tab.result_text.bind("<Control-c>")

    run_tab.select_all_result_text()
    run_tab.copy_result_selection()
    assert fixture.app.clipboard_get() == "42"

    run_tab.open_result_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Select All" in labels
    assert "Copy" in labels
    assert "Paste" not in labels
    assert "Undo" not in labels


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_compile_error_location_and_highlights_source(fixture):
    """Compile errors show line/column details and visually mark the source position that failed to parse."""
    fixture.simulate_login()
    source_text = (
        "| a b |\n"
        "b := (Set new) add: 123; add: 457; add 1122; yourself.\n"
        "a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n"
        "\n"
        "a halt at: 5\n"
    )
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(
        source_text, 48
    )

    fixture.app.run_code(source_text)
    fixture.app.update()
    run_tab = fixture.app.run_tab

    status_text = run_tab.status_label.cget("text")
    assert "line 2, column 40" in status_text

    result_text = run_tab.result_text.get("1.0", "end")
    assert "Line 2, column 40" in result_text
    assert "b := (Set new) add: 123; add: 457; add 1122; yourself." in result_text
    assert "\n                                       ^\n" in result_text

    highlight_range = run_tab.source_text.tag_ranges("compile_error_location")
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == "2.39"
    assert str(highlight_range[1]) == "2.40"


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_preserves_leading_blank_lines_for_compile_error_location(
    fixture,
):
    """Compile error location mapping keeps the source exactly as shown in the Run editor."""
    fixture.simulate_login()
    source_text = "\n" "| a |\n" "\n" "a := set new.\n" "a\n"

    def raise_compile_error(executed_source):
        offset = executed_source.index("set") + 1
        raise FakeCompileGemstoneError(executed_source, offset)

    fixture.mock_browser.run_code.side_effect = raise_compile_error

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", source_text)

    run_tab.run_button.invoke()
    fixture.app.update()

    status_text = run_tab.status_label.cget("text")
    assert "line 4, column 6" in status_text
    expected_source = run_tab.source_text.get("1.0", "end-1c")
    assert fixture.mock_browser.run_code.call_args_list[-1] == call(expected_source)

    highlight_range = run_tab.source_text.tag_ranges("compile_error_location")
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == "4.5"
    assert str(highlight_range[1]) == "4.6"


@with_fixtures(SwordfishAppFixture)
def test_debug_button_opens_debugger_tab_in_notebook(fixture):
    """Clicking Debug from the Run tab after a runtime error should open a Debugger tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(t, "text") for t in fixture.app.notebook.tabs()
    ]
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_button_uses_current_source_text_not_stale_prior_error(fixture):
    """Debug always evaluates the code currently visible in the Run source editor."""
    fixture.simulate_login()
    successful_result = Mock()
    successful_result.asString.return_value.to_py = "4"
    fixture.mock_browser.run_code.side_effect = [
        FakeGemstoneError(),
        successful_result,
    ]

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "2 + 2")

    run_tab.debug_button.invoke()
    fixture.app.update()

    assert fixture.mock_browser.run_code.call_args_list[-1] == call("2 + 2")
    assert fixture.app.debugger_tab is None
    assert (
        run_tab.status_label.cget("text")
        == "Completed successfully; no debugger context"
    )


@with_fixtures(SwordfishAppFixture)
def test_debug_button_does_not_open_debugger_for_compile_error(fixture):
    """Debug does not open a debugger tab when current source has a compile error."""
    fixture.simulate_login()
    source_text = (
        "| a b |\n"
        "b := (Set new) add: 123; add: 457; add 1122; yourself.\n"
        "a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n"
        "\n"
        "a halt at: 5\n"
    )
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", source_text)
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(
        source_text, 48
    )

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(t, "text") for t in fixture.app.notebook.tabs()
    ]
    assert "Debugger" not in tab_labels
    expected_source = run_tab.source_text.get("1.0", "end-1c")
    assert fixture.mock_browser.run_code.call_args_list[-1] == call(expected_source)
    assert "line 2, column 40" in run_tab.status_label.cget("text")


@with_fixtures(SwordfishAppFixture)
def test_debug_button_selects_debugger_tab_as_visible(fixture):
    """After Debug is clicked from the Run tab, the Debugger tab should become the selected notebook tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Debugger"


@with_fixtures(SwordfishAppFixture)
def test_debugger_refresh_uses_selected_top_frame_source(fixture):
    """AI: Debugger refresh should render source for the selected top frame, not the next frame."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    top_frame = types.SimpleNamespace(
        level=1,
        class_name="TopFrameClass",
        method_name="topFrameMethod",
        method_source="top frame source",
        step_point_offset=4,
        self=Mock(),
        vars={},
    )
    second_frame = types.SimpleNamespace(
        level=2,
        class_name="SecondFrameClass",
        method_name="secondFrameMethod",
        method_source="second frame source",
        step_point_offset=9,
        self=Mock(),
        vars={},
    )

    class OneBasedStack:
        def __init__(self, frames):
            self.frames = list(frames)

        def __iter__(self):
            return iter(self.frames)

        def __bool__(self):
            return bool(self.frames)

        def __getitem__(self, level):
            return self.frames[level - 1]

    debugger_tab.stack_frames = OneBasedStack([top_frame, second_frame])

    with patch.object(debugger_tab.code_panel, "refresh") as refresh_source:
        with patch.object(debugger_tab, "refresh_explorer") as refresh_explorer:
            debugger_tab.refresh()

    assert debugger_tab.listbox.selection() == ("1",)
    refresh_source.assert_called_once_with("top frame source", mark=4)
    refresh_explorer.assert_called_once_with(top_frame)


@with_fixtures(SwordfishAppFixture)
def test_debugger_selected_stack_frame_matches_treeview_level_identifier(fixture):
    """AI: Debugger selection should resolve Treeview level ids to matching frame levels."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    top_frame = types.SimpleNamespace(
        level=1,
        class_name="TopFrameClass",
        method_name="topFrameMethod",
        method_source="top frame source",
        step_point_offset=4,
        self=Mock(),
        vars={},
    )
    second_frame = types.SimpleNamespace(
        level=2,
        class_name="SecondFrameClass",
        method_name="secondFrameMethod",
        method_source="second frame source",
        step_point_offset=9,
        self=Mock(),
        vars={},
    )

    class OneBasedStack:
        def __init__(self, frames):
            self.frames = list(frames)

        def __iter__(self):
            return iter(self.frames)

        def __bool__(self):
            return bool(self.frames)

        def __getitem__(self, level):
            return self.frames[level - 1]

    debugger_tab.stack_frames = OneBasedStack([top_frame, second_frame])
    debugger_tab.refresh()

    assert debugger_tab.get_selected_stack_frame() is top_frame

    debugger_tab.listbox.selection_set("2")
    debugger_tab.listbox.focus("2")
    assert debugger_tab.get_selected_stack_frame() is second_frame


@with_fixtures(SwordfishAppFixture)
def test_completed_debugger_can_be_dismissed_with_close_button(fixture):
    """AI: Once debugger execution completes, the UI should expose a close action that exits debugger mode."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    completed_result = Mock()
    completed_result.asString.return_value.to_py = "42"
    debugger_tab.finish(completed_result)
    fixture.app.update()

    assert debugger_tab.close_button.winfo_exists()
    debugger_tab.close_button.invoke()
    fixture.app.update()

    assert fixture.app.debugger_tab is None
    tab_labels = [
        fixture.app.notebook.tab(tab_id, "text")
        for tab_id in fixture.app.notebook.tabs()
    ]
    assert "Debugger" not in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debugger_active_controls_keep_close_on_right(fixture):
    """AI: Debugger control row includes close on the right of stepping and browse actions."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    assert debugger_tab is not None
    assert debugger_tab.close_button is debugger_tab.debugger_controls.close_button

    browse_column = int(
        debugger_tab.debugger_controls.browse_button.grid_info()["column"]
    )
    close_column = int(
        debugger_tab.debugger_controls.close_button.grid_info()["column"]
    )
    assert browse_column < close_column
    assert debugger_tab.debugger_controls.close_button.cget("text") == "Close"


@with_fixtures(SwordfishAppFixture)
def test_debugger_active_controls_place_restart_between_through_and_stop(
    fixture,
):
    """AI: Restart action should be in stepping flow between Through and Stop."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    through_column = int(
        debugger_tab.debugger_controls.through_button.grid_info()["column"]
    )
    restart_column = int(
        debugger_tab.debugger_controls.restart_button.grid_info()["column"]
    )
    stop_column = int(debugger_tab.debugger_controls.stop_button.grid_info()["column"])

    assert through_column < restart_column
    assert restart_column < stop_column
    assert debugger_tab.debugger_controls.restart_button.cget("text") == "Restart"


@with_fixtures(SwordfishAppFixture)
def test_debugger_restart_button_dispatches_to_restart_frame(fixture):
    """AI: Restart debugger control should invoke restart of the selected frame."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    with patch.object(debugger_tab, "restart_frame") as restart_frame:
        debugger_tab.debugger_controls.restart_button.invoke()

    restart_frame.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_debugger_restart_frame_uses_selected_level_with_debug_session(
    fixture,
):
    """AI: Restart frame action should restart exactly the selected frame level and apply the resulting outcome."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    action_outcome = Mock()
    with patch.object(
        debugger_tab,
        "selected_frame_level",
        return_value=3,
    ):
        with patch.object(
            debugger_tab.debug_session,
            "restart_frame",
            return_value=action_outcome,
        ) as restart_frame:
            with patch.object(
                debugger_tab,
                "apply_debug_action_outcome",
            ) as apply_debug_action_outcome:
                debugger_tab.restart_frame()

    restart_frame.assert_called_once_with(3)
    apply_debug_action_outcome.assert_called_once_with(action_outcome)


@with_fixtures(SwordfishAppFixture)
def test_completed_debugger_keeps_close_in_top_action_row(fixture):
    """AI: Completed debugger view keeps close action above result content for layout consistency."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    completed_result = Mock()
    completed_result.asString.return_value.to_py = "42"
    debugger_tab.finish(completed_result)
    fixture.app.update()

    assert debugger_tab.close_button.master is debugger_tab.finished_actions
    assert int(debugger_tab.finished_actions.grid_info()["row"]) == 0
    assert int(debugger_tab.result_text.grid_info()["row"]) == 1
    assert debugger_tab.close_button.cget("text") == "Close"


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_navigates_to_selected_stack_frame_method(fixture):
    """AI: Browse Method on debugger should navigate the browser to the selected stack frame method."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name="OrderLine",
        method_name="total",
    )

    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            "handle_sender_selection",
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_maps_class_side_frames_to_class_side_selection(fixture):
    """AI: Class-side stack frames should browse to the class side in the browser."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name="OrderLine class",
        method_name="buildForDemo",
    )

    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            "handle_sender_selection",
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        "OrderLine",
        False,
        "buildForDemo",
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_button_dispatches_to_browse_selected_frame_method(fixture):
    """AI: Browse Method debugger control should invoke debugger frame browsing action."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab

    with patch.object(
        debugger_tab,
        "open_selected_frame_method",
    ) as open_selected_frame_method:
        debugger_tab.debugger_controls.browse_button.invoke()

    open_selected_frame_method.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_debugger_variable_inspect_opens_main_inspector_tab(fixture):
    """AI: Inspecting a debugger variable from its context menu opens the main Inspector tab for that object."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame_self = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001)
    frame_variable = make_mock_gemstone_object("Integer", "42", oop=3002)
    frame = types.SimpleNamespace(
        self=frame_self,
        vars={"x": frame_variable},
    )
    debugger_tab.refresh_explorer(frame)
    fixture.app.update()

    context_tab_id = debugger_tab.explorer.tabs()[0]
    context_inspector = debugger_tab.explorer.nametowidget(context_tab_id)
    variable_row = None
    for row_id in context_inspector.treeview.get_children():
        row_name = context_inspector.treeview.item(row_id, "values")[0]
        if row_name == "x" and variable_row is None:
            variable_row = row_id
    assert variable_row is not None

    context_inspector.treeview.focus(variable_row)
    context_inspector.treeview.selection_set(variable_row)
    context_inspector.open_object_menu(
        types.SimpleNamespace(
            x=-1,
            y=-1,
            x_root=1,
            y_root=1,
        ),
    )
    menu_labels = menu_command_labels(context_inspector.current_object_menu)
    assert "Inspect" in menu_labels
    invoke_menu_command_by_label(context_inspector.current_object_menu, "Inspect")
    fixture.app.update()

    assert fixture.app.inspector_tab is not None
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "3002:Integer 42"


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_context_menu_inspect_evaluates_selected_expression_in_frame(
    fixture,
):
    """AI: Inspect from debugger source menu evaluates selected expression in the active frame and opens Inspector."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    evaluated_value = make_mock_gemstone_object("Integer", "3", oop=3003)
    mock_var_context = Mock()
    mock_gemstone_session = Mock()
    mock_gemstone_session.execute.return_value = evaluated_value
    frame = types.SimpleNamespace(
        self=make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001),
        vars={"x": make_mock_gemstone_object("Integer", "2", oop=3002)},
        var_context=mock_var_context,
        gemstone_session=mock_gemstone_session,
    )

    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "x + 1")
    debugger_tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        debugger_tab.code_panel.open_text_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        menu_labels = menu_command_labels(debugger_tab.code_panel.current_context_menu)
        assert "Inspect" in menu_labels
        invoke_menu_command_by_label(
            debugger_tab.code_panel.current_context_menu,
            "Inspect",
        )
        fixture.app.update()

    mock_gemstone_session.execute.assert_called_once_with(
        "x + 1",
        context=mock_var_context,
    )
    assert fixture.app.inspector_tab is not None
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "3003:Integer 3"


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_context_menu_inspect_reads_self_instance_variable(
    fixture,
):
    """AI: Inspecting an instance-variable token in debugger source should resolve from self, not evaluate as a free symbol."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    full_value = make_mock_gemstone_object("Set", "aSet", oop=4004)
    frame_self = make_mock_instance_with_inst_vars(
        "ExampleSetTest",
        "anExampleSetTest",
        {"full": full_value},
        oop=4001,
    )
    mock_var_context = Mock()
    mock_gemstone_session = Mock()
    mock_gemstone_session.execute.side_effect = FakeGemstoneError()
    frame = types.SimpleNamespace(
        self=frame_self,
        vars={},
        var_context=mock_var_context,
        gemstone_session=mock_gemstone_session,
    )

    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "full add: 5")
    debugger_tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.4")
    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        debugger_tab.code_panel.open_text_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        invoke_menu_command_by_label(
            debugger_tab.code_panel.current_context_menu,
            "Inspect",
        )
        fixture.app.update()

    mock_gemstone_session.execute.assert_not_called()
    assert fixture.app.inspector_tab is not None
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "4004:Set aSet"


@with_fixtures(SwordfishAppFixture)
def test_file_run_command_opens_run_tab_in_notebook(fixture):
    """Choosing File > Run should open and select a Run tab in the main notebook."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(tab_id, "text")
        for tab_id in fixture.app.notebook.tabs()
    ]
    assert "Run" in tab_labels
    selected_tab_text = fixture.app.notebook.tab(fixture.app.notebook.select(), "text")
    assert selected_tab_text == "Run"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_search_populates_result_list(fixture):
    """Searching for a class name in the FindDialog calls GemStone and
    populates the results listbox with the matching class names."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(fixture.app)

    dialog.find_entry.insert(0, "Order")
    dialog.find_text()

    results = list(dialog.results_listbox.get(0, "end"))
    assert "OrderLine" in results
    assert "OrderHistory" in results
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_mode_supports_contains_and_exact_matching(
    fixture,
):
    """AI: Class mode should switch between contains and exact class-name matching."""
    fixture.simulate_login()

    def classes_for_pattern(pattern, should_stop=None):
        if pattern == "Order":
            return ["Order", "OrderLine"]
        if pattern == "^Order$":
            return ["Order"]
        return []

    fixture.mock_browser.find_classes.side_effect = classes_for_pattern

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="class",
            search_query="Order",
            run_search=True,
            match_mode="contains",
        )

    assert list(dialog.results_listbox.get(0, "end")) == ["Order", "OrderLine"]
    dialog.match_mode.set("exact")
    dialog.find_text()
    assert list(dialog.results_listbox.get(0, "end")) == ["Order"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_can_stop_a_running_class_search(fixture):
    """AI: Stop should cancel class search and keep partial results."""
    fixture.simulate_login()

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="class",
            search_query="Order",
            match_mode="contains",
        )

    def classes_for_pattern(pattern, should_stop=None):
        class_names = []
        class_index = 0
        while class_index < 10:
            if should_stop is not None and should_stop():
                return class_names
            class_names.append("Order%s" % class_index)
            if class_index == 2:
                dialog.request_stop_find()
            class_index = class_index + 1
        return class_names

    fixture.mock_browser.find_classes.side_effect = classes_for_pattern

    dialog.find_text()

    assert dialog.status_var.get() == "Find stopped. Showing partial results."
    assert list(dialog.results_listbox.get(0, "end")) == [
        "Order0",
        "Order1",
        "Order2",
    ]
    assert str(dialog.stop_button.cget("state")) == tk.DISABLED
    assert str(dialog.find_button.cget("state")) == tk.NORMAL
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_method_mode_supports_contains_and_exact_matching(
    fixture,
):
    """AI: Method mode should search selectors for contains and implementors for exact."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "Order", "show_instance_side": False},
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="contains",
        )

    assert list(dialog.results_listbox.get(0, "end")) == ["subtotal", "total"]
    dialog.match_mode.set("exact")
    dialog.find_text()
    assert list(dialog.results_listbox.get(0, "end")) == [
        "Order class>>total",
        "OrderLine>>total",
    ]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_shows_search_intent_and_result_action_text(fixture):
    """AI: Find dialog should show current search intent and result action guidance."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="contains",
        )

    assert dialog.search_intent_var.get() == 'Methods containing selector "total".'
    assert (
        dialog.result_action_var.get()
        == "Double-click a selector to find implementors (exact)."
    )

    dialog.match_mode.set("exact")
    dialog.find_text()

    assert dialog.search_intent_var.get() == 'Implementors of method "total".'
    assert (
        dialog.result_action_var.get()
        == "Double-click an implementor to open the method."
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_method_contains_double_click_pivots_to_exact_search_in_place(fixture):
    """AI: Double-clicking a method selector in contains mode should pivot in-place to exact implementors."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="method",
            search_query="tot",
            run_search=True,
            match_mode="contains",
        )

    with patch.object(fixture.app, "open_implementors_dialog") as open_implementors:
        selector_names = list(dialog.results_listbox.get(0, "end"))
        dialog.results_listbox.selection_set(selector_names.index("total"))
        dialog.on_result_double_click(None)

    open_implementors.assert_not_called()
    fixture.mock_browser.find_implementors.assert_called_once_with("total")
    assert dialog.winfo_exists() == 1
    assert dialog.match_mode.get() == "exact"
    assert dialog.find_entry.get() == "total"
    assert list(dialog.results_listbox.get(0, "end")) == ["OrderLine>>total"]
    assert dialog.search_intent_var.get() == 'Implementors of method "total".'
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_reference_method_search_is_always_exact(
    fixture,
):
    """AI: Method reference search should force exact matching; narrow tracing requires a known source class."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            }
        ],
        "total_count": 1,
        "returned_count": 1,
    }

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="contains",
            reference_target="method",
        )

    assert dialog.match_mode.get() == "exact"
    assert str(dialog.match_contains_radio.cget("state")) == tk.DISABLED
    fixture.mock_browser.find_selectors.assert_not_called()
    fixture.mock_browser.find_senders.assert_called_once_with(
        "total",
        include_category_details=True,
    )
    assert str(dialog.narrow_button.cget("state")) == tk.DISABLED
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_reference_class_search_is_always_exact(
    fixture,
):
    """AI: Class reference search should force exact matching."""
    fixture.simulate_login()
    fixture.mock_browser.find_class_references.return_value = {
        "references": [
            {
                "class_name": "OrderBuilder",
                "show_instance_side": True,
                "method_selector": "fromOrder:",
            }
        ],
        "total_count": 1,
        "returned_count": 1,
    }

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="Or",
            run_search=True,
            match_mode="contains",
            reference_target="class",
        )

    assert dialog.match_mode.get() == "exact"
    assert str(dialog.match_contains_radio.cget("state")) == tk.DISABLED
    fixture.mock_browser.find_classes.assert_not_called()
    fixture.mock_browser.find_class_references.assert_called_once_with("Or")
    assert list(dialog.results_listbox.get(0, "end")) == ["OrderBuilder>>fromOrder:"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_open_find_dialog_for_class_prefills_and_executes_reference_search(
    fixture,
):
    """AI: Opening class references should run class-reference lookup and show matching methods."""
    fixture.simulate_login()
    fixture.mock_browser.find_class_references.return_value = {
        "references": [
            {
                "class_name": "Order",
                "show_instance_side": True,
                "method_selector": "addLine:",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "defaultLineClass",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }

    with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
        with patch.object(fixture.app, "end_foreground_activity") as end_activity:
            with patch.object(FindDialog, "wait_visibility"):
                dialog = fixture.app.open_find_dialog_for_class("OrderLine")

    assert dialog is not None
    assert dialog.search_type.get() == "reference"
    assert dialog.reference_target.get() == "class"
    assert dialog.match_mode.get() == "exact"
    assert dialog.find_entry.get() == "OrderLine"
    begin_activity.assert_called_once_with(
        "Finding references to class OrderLine...",
    )
    end_activity.assert_called_once_with()
    assert list(dialog.results_listbox.get(0, "end")) == [
        "Order class>>defaultLineClass",
        "Order>>addLine:",
    ]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_navigates_to_selected_class_reference_method(
    fixture,
):
    """AI: Double-clicking a class-reference match should navigate to the referenced method context."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(fixture.app)

    dialog.search_type.set("reference")
    dialog.reference_target.set("class")
    dialog.match_mode.set("exact")
    dialog.navigation_method_results = [("Order", False, "defaultLineClass")]
    dialog.results_listbox.insert(tk.END, "Order class>>defaultLineClass")
    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_package == "Kernel"
    assert fixture.session_record.selected_class == "Order"
    assert fixture.session_record.show_instance_side is False
    assert fixture.session_record.selected_method_symbol == "defaultLineClass"
    assert fixture.session_record.selected_method_category == "accessing"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_navigates_browser_to_selected_class(fixture):
    """Double-clicking a class name in the FindDialog results navigates the
    browser to that class by selecting its package and class in the columns."""
    fixture.simulate_login()
    fixture.app.browser_tab.packages_widget.browse_mode_var.set("categories")
    fixture.app.browser_tab.packages_widget.change_browse_mode()
    fixture.app.update()
    # AI: jump_to_class resolves the class symbol to find its package via
    # gemstone_session.resolve_symbol(name).category().to_py
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(fixture.app)

    dialog.results_listbox.insert(tk.END, "OrderLine")
    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_package == "Kernel"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_in_dictionary_mode_updates_dictionary_and_class_lists(
    fixture,
):
    """AI: In dictionary browse mode, selecting a class from Find should switch dictionary/class panes to the class's dictionary and selected class."""
    fixture.simulate_login()
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals", "Kernel"]

    def classes_for_dictionary(dictionary_name):
        if dictionary_name == "UserGlobals":
            return ["LegacyClass"]
        if dictionary_name == "Kernel":
            return ["OrderLine", "Order"]
        return []

    fixture.mock_browser.list_classes_in_dictionary.side_effect = classes_for_dictionary
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    fixture.session_record.select_class_category("UserGlobals")
    fixture.app.event_queue.publish("SelectedClassChanged")
    fixture.app.update()

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(fixture.app)

    dialog.results_listbox.insert(tk.END, "OrderLine")
    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_dictionary == "Kernel"
    assert fixture.session_record.selected_class == "OrderLine"
    dictionary_listbox = (
        fixture.app.browser_tab.packages_widget.selection_list.selection_listbox
    )
    selected_dictionary_index = dictionary_listbox.curselection()[0]
    assert dictionary_listbox.get(selected_dictionary_index) == "Kernel"
    class_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "Order"]
    selected_class_index = class_listbox.curselection()[0]
    assert class_listbox.get(selected_class_index) == "OrderLine"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_in_dictionary_mode_uses_class_membership_not_symbol_category(
    fixture,
):
    """AI: In dictionary mode, Find navigation should choose the dictionary that contains the class even if class category metadata differs."""
    fixture.simulate_login()
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals", "Kernel"]

    def classes_for_dictionary(dictionary_name):
        if dictionary_name == "UserGlobals":
            return ["OrderLine", "LegacyClass"]
        if dictionary_name == "Kernel":
            return ["Order", "Collection"]
        return []

    fixture.mock_browser.list_classes_in_dictionary.side_effect = classes_for_dictionary
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    fixture.session_record.select_class_category("Kernel")
    fixture.app.event_queue.publish("SelectedClassChanged")
    fixture.app.update()

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(fixture.app)

    dialog.results_listbox.insert(tk.END, "OrderLine")
    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_dictionary == "UserGlobals"
    assert fixture.session_record.selected_class == "OrderLine"
    class_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "LegacyClass"]
    selected_class_index = class_listbox.curselection()[0]
    assert class_listbox.get(selected_class_index) == "OrderLine"


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_method_search_populates_result_list(fixture):
    """Searching for senders in the FindDialog shows sender methods with class/side labels."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "default",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    results = list(dialog.results_listbox.get(0, "end"))
    assert results == ["Order class>>default", "OrderLine>>recalculateTotal"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_double_click_navigates_browser_to_selected_sender(fixture):
    """Double-clicking a sender result jumps the browser to that sender method context."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }

    with patch.object(FindDialog, "wait_visibility"):
        dialog = FindDialog(
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    dialog.results_listbox.selection_set(0)
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_package == "Kernel"
    assert fixture.session_record.show_instance_side is True
    assert fixture.session_record.selected_method_symbol == "recalculateTotal"


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_filters_to_observed_senders(fixture):
    """AI: Narrowing sender results with tracing should keep only observed runtime callers."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "default",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 1,
        "candidate_tests": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "visited_selector_count": 3,
        "sender_search_truncated": False,
        "selector_limit_reached": False,
        "elapsed_limit_reached": False,
    }
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.return_value = {
        "method_name": "total",
        "total_sender_count": 2,
        "targeted_sender_count": 2,
        "traced_sender_count": 2,
        "skipped_sender_count": 0,
        "traced_senders": [],
        "skipped_senders": [],
    }
    fixture.mock_browser.observed_senders_for_selector.return_value = {
        "total_count": 1,
        "returned_count": 1,
        "total_observed_calls": 2,
        "observed_senders": [
            {
                "caller_class_name": "OrderLine",
                "caller_show_instance_side": True,
                "caller_method_selector": "recalculateTotal",
                "method_selector": "total",
                "observed_count": 2,
            },
        ],
    }
    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_run(dialog, timed_out=False, summary_message=""):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        if dialog.selected_tests is None:
            dialog.run_selected_tests()

    with patch.object(FindDialog, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_run,
            ):
                dialog = FindDialog(
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    results = list(dialog.results_listbox.get(0, "end"))
    assert results == ["OrderLine>>recalculateTotal"]
    fixture.mock_browser.sender_test_plan_for_selector.assert_called_once_with(
        "total",
        2,
        500,
        200,
        200,
        max_elapsed_ms=120000,
        should_stop=ANY,
        on_candidate_test=ANY,
    )
    fixture.mock_browser.trace_selector.assert_called_once_with(
        "total",
        max_results=250,
    )
    fixture.mock_browser.run_test_method.assert_called_once_with(
        "OrderLineTest",
        "testRecalculateTotal",
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_stops_when_no_candidate_tests(
    fixture,
):
    """AI: If discovery yields no candidate tests, narrowing should not proceed to tracing."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 0,
        "candidate_tests": [],
        "visited_selector_count": 1,
        "elapsed_limit_reached": False,
        "sender_search_truncated": True,
    }
    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_cancel(dialog, timed_out=False, summary_message=""):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        dialog.cancel_dialog()

    with patch.object(FindDialog, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_cancel,
            ):
                dialog = FindDialog(
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    fixture.mock_browser.trace_selector.assert_not_called()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_can_search_more_after_timeout(
    fixture,
):
    """AI: When timed out, choosing Search More should continue test discovery and merge newly found candidates."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.side_effect = [
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "OrderLineTest",
                    "test_method_selector": "testRecalculateTotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateTotal",
                },
            ],
            "sender_edges": [
                {
                    "from_selector": "total",
                    "to_class_name": "OrderLine",
                    "to_method_selector": "recalculateTotal",
                    "to_show_instance_side": True,
                    "depth": 1,
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": True,
            "elapsed_ms": 120000,
            "max_elapsed_ms": 120000,
            "stopped_by_user": False,
        },
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "InvoiceTest",
                    "test_method_selector": "testRecalculateSubtotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateSubtotal",
                },
            ],
            "sender_edges": [
                {
                    "from_selector": "total",
                    "to_class_name": "Invoice",
                    "to_method_selector": "recalculateSubtotal",
                    "to_show_instance_side": True,
                    "depth": 1,
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
            "elapsed_ms": 100,
            "max_elapsed_ms": 120000,
            "stopped_by_user": False,
        },
    ]
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.return_value = {
        "method_name": "total",
        "total_sender_count": 1,
        "targeted_sender_count": 1,
        "traced_sender_count": 1,
        "skipped_sender_count": 0,
        "traced_senders": [],
        "skipped_senders": [],
    }
    fixture.mock_browser.observed_senders_for_selector.return_value = {
        "total_count": 1,
        "returned_count": 1,
        "total_observed_calls": 1,
        "observed_senders": [
            {
                "caller_class_name": "OrderLine",
                "caller_show_instance_side": True,
                "caller_method_selector": "recalculateTotal",
                "method_selector": "total",
                "observed_count": 1,
            },
        ],
    }

    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_search_more_or_run(
        dialog,
        timed_out=False,
        summary_message="",
    ):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        if timed_out:
            dialog.request_search_further()
        if not timed_out:
            dialog.run_selected_tests()

    with patch.object(FindDialog, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_search_more_or_run,
            ):
                dialog = FindDialog(
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    assert fixture.mock_browser.sender_test_plan_for_selector.call_count == 2
    assert fixture.mock_browser.run_test_method.call_count == 2
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_stop_search_cancels_narrowing_instead_of_using_partial_results(
    fixture,
):
    """AI: Stopping discovery should cancel narrowing and never continue with partially found tests."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 1,
        "candidate_tests": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "visited_selector_count": 1,
        "sender_search_truncated": False,
        "selector_limit_reached": False,
        "elapsed_limit_reached": False,
        "stopped_by_user": False,
    }
    original_set_searching_state = CoveringTestsSearchDialog.set_searching_state

    def set_searching_then_stop(dialog):
        original_set_searching_state(dialog)
        dialog.request_stop_search()

    with patch.object(FindDialog, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_searching_state",
                autospec=True,
                side_effect=set_searching_then_stop,
            ):
                dialog = FindDialog(
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    assert dialog.status_var.get() == "Test discovery stopped."
    fixture.mock_browser.trace_selector.assert_not_called()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_reloads_static_senders_after_selector_change(
    fixture,
):
    """AI: Changing selector after tracing should refresh static sender candidates before narrowing again."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.side_effect = [
        {
            "senders": [
                {
                    "class_name": "OrderLine",
                    "show_instance_side": True,
                    "method_selector": "recalculateTotal",
                },
            ],
            "total_count": 1,
            "returned_count": 1,
        },
        {
            "senders": [
                {
                    "class_name": "Invoice",
                    "show_instance_side": True,
                    "method_selector": "recalculateSubtotal",
                },
            ],
            "total_count": 1,
            "returned_count": 1,
        },
    ]
    fixture.mock_browser.sender_test_plan_for_selector.side_effect = [
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "OrderLineTest",
                    "test_method_selector": "testRecalculateTotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateTotal",
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
        },
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "InvoiceTest",
                    "test_method_selector": "testRecalculateSubtotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateSubtotal",
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
        },
    ]
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.side_effect = [
        {
            "method_name": "total",
            "total_sender_count": 1,
            "targeted_sender_count": 1,
            "traced_sender_count": 1,
            "skipped_sender_count": 0,
            "traced_senders": [],
            "skipped_senders": [],
        },
        {
            "method_name": "subtotal",
            "total_sender_count": 1,
            "targeted_sender_count": 1,
            "traced_sender_count": 1,
            "skipped_sender_count": 0,
            "traced_senders": [],
            "skipped_senders": [],
        },
    ]
    fixture.mock_browser.observed_senders_for_selector.side_effect = [
        {
            "total_count": 1,
            "returned_count": 1,
            "total_observed_calls": 1,
            "observed_senders": [
                {
                    "caller_class_name": "OrderLine",
                    "caller_show_instance_side": True,
                    "caller_method_selector": "recalculateTotal",
                    "method_selector": "total",
                    "observed_count": 1,
                },
            ],
        },
        {
            "total_count": 1,
            "returned_count": 1,
            "total_observed_calls": 1,
            "observed_senders": [
                {
                    "caller_class_name": "Invoice",
                    "caller_show_instance_side": True,
                    "caller_method_selector": "recalculateSubtotal",
                    "method_selector": "subtotal",
                    "observed_count": 1,
                },
            ],
        },
    ]

    selected_tests_by_method = {
        "total": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "subtotal": [
            {
                "test_case_class_name": "InvoiceTest",
                "test_method_selector": "testRecalculateSubtotal",
                "depth": 1,
                "reached_from_selector": "recalculateSubtotal",
            },
        ],
    }

    def selected_tests_for_method(method_name):
        return selected_tests_by_method[method_name]

    with patch.object(FindDialog, "wait_visibility"):
        with patch.object(
            FindDialog,
            "choose_tests_for_tracing",
            side_effect=selected_tests_for_method,
        ):
            dialog = FindDialog(
                fixture.app,
                search_type="reference",
                search_query="total",
                run_search=True,
                match_mode="exact",
                reference_target="method",
            )
            dialog.narrow_senders_with_tracing()
            first_results = list(dialog.results_listbox.get(0, "end"))

            dialog.find_entry.delete(0, tk.END)
            dialog.find_entry.insert(0, "subtotal")
            dialog.narrow_senders_with_tracing()
            second_results = list(dialog.results_listbox.get(0, "end"))

    assert first_results == ["OrderLine>>recalculateTotal"]
    assert second_results == ["Invoice>>recalculateSubtotal"]
    assert fixture.mock_browser.find_senders.call_args_list == [
        call("total", include_category_details=True),
        call("subtotal", include_category_details=True),
    ]
    dialog.destroy()


def make_mock_gemstone_object(class_name="OrderLine", string_repr="anObject", oop=None):
    """AI: Minimal GemStone object mock satisfying ObjectInspector's full protocol.
    allInstVarNames() returns [] so sub-inspectors are created empty (no recursion needed).
    isBehavior() returns False so instances are inspected via inspect_instance, not inspect_class.
    """
    obj = Mock()
    obj.gemstone_class.return_value.asString.return_value.to_py = class_name
    obj.asString.return_value.to_py = string_repr
    obj.printString.return_value.to_py = string_repr
    obj.gemstone_class.return_value.allInstVarNames.return_value = []
    obj.isBehavior.return_value.to_py = False
    if oop is not None:
        obj.oop = oop
    return obj


def make_mock_dictionary(entries):
    dictionary = make_mock_gemstone_object(
        "Dictionary", f"a Dictionary({len(entries)})"
    )
    keys = []
    values_by_key = {}
    for key_name, value in entries:
        key = make_mock_gemstone_object("Symbol", key_name)
        keys.append(key)
        values_by_key[key] = value

    dictionary.keys.return_value = keys
    dictionary.size.return_value.to_py = len(keys)

    def at_key(key):
        return values_by_key[key]

    dictionary.at.side_effect = at_key
    return dictionary


def make_mock_array(values):
    array = make_mock_gemstone_object("Array", f"an Array({len(values)})")
    array.size.return_value.to_py = len(values)
    values_by_index = {index + 1: value for index, value in enumerate(values)}

    def at_index(index):
        return values_by_index[index]

    array.at.side_effect = at_index
    return array


def make_mock_instance_with_inst_vars(class_name, string_repr, inst_vars, oop=None):
    instance = make_mock_gemstone_object(class_name, string_repr, oop=oop)
    inst_var_names = []
    values_by_name = {}
    for inst_var_name, inst_var_value in inst_vars.items():
        inst_var_symbol = Mock()
        inst_var_symbol.to_py = inst_var_name
        inst_var_names.append(inst_var_symbol)
        values_by_name[inst_var_name] = inst_var_value

    instance.gemstone_class.return_value.allInstVarNames.return_value = inst_var_names

    def value_for_inst_var(inst_var_name):
        return values_by_name[inst_var_name.to_py]

    instance.instVarNamed.side_effect = value_for_inst_var
    return instance


class GraphObjectRegistryFixture(Fixture):
    @set_up
    def create_registry(self):
        self.registry = GraphObjectRegistry()


class UmlDiagramRegistryFixture(Fixture):
    @set_up
    def create_registry(self):
        self.registry = UmlDiagramRegistry()


class GraphObjectKeyScenarios(Fixture):
    @scenario
    def none_object(self):
        """AI: None should map to a stable sentinel key."""
        self.an_object = None
        self.expected_key = ("none",)

    @scenario
    def oop_backed_object(self):
        """AI: Objects exposing oop should use that oop for deduplication."""
        self.an_object = make_mock_gemstone_object("Integer", "7", oop=1234)
        self.expected_key = ("oop", "1234")

    @scenario
    def object_without_oop_attribute(self):
        """AI: Objects without oop should fall back to Python identity keys."""
        self.an_object = object()
        self.expected_key = ("identity", str(id(self.an_object)))

    @scenario
    def object_with_failing_oop_accessor(self):
        """AI: oop lookup failures should fall back to identity keys."""

        class OopFailingObject:
            @property
            def oop(self):
                raise RuntimeError("oop not available")

        self.an_object = OopFailingObject()
        self.expected_key = ("identity", str(id(self.an_object)))


@with_fixtures(GraphObjectRegistryFixture, GraphObjectKeyScenarios)
def test_graph_registry_oop_key_generation_handles_object_shapes(fixture, scenario):
    """AI: Graph registry key generation should choose oop keys when available and otherwise use stable fallbacks."""
    with expected(NoException):
        oop_key = fixture.registry.oop_key_for(scenario.an_object)
    assert oop_key == scenario.expected_key


@with_fixtures(GraphObjectRegistryFixture)
def test_graph_registry_registers_and_resolves_nodes_by_key(fixture):
    """AI: Registering a graph node should allow node lookup by an equivalent object key."""
    gemstone_object = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=2003)
    oop_key = fixture.registry.oop_key_for(gemstone_object)
    node = GraphNode(
        gemstone_object,
        oop_key,
        class_name="OrderLine",
        label="2003:OrderLine",
    )

    fixture.registry.register_node(node)

    assert fixture.registry.contains_object(gemstone_object)
    assert fixture.registry.node_for(gemstone_object) is node


@with_fixtures(GraphObjectRegistryFixture)
def test_graph_registry_avoids_duplicate_edges_for_same_source_target_and_label(
    fixture,
):
    """AI: Re-adding an existing source-target-label edge should not duplicate graph links."""
    source_object = make_mock_gemstone_object("Order", "anOrder", oop=101)
    target_object = make_mock_gemstone_object("OrderLine", "aLine", oop=102)
    source_node = GraphNode(
        source_object,
        fixture.registry.oop_key_for(source_object),
        class_name="Order",
        label="101:Order",
    )
    target_node = GraphNode(
        target_object,
        fixture.registry.oop_key_for(target_object),
        class_name="OrderLine",
        label="102:OrderLine",
    )

    first_edge = fixture.registry.add_edge(source_node, target_node, "line")
    duplicate_edge = fixture.registry.add_edge(source_node, target_node, "line")
    different_label_edge = fixture.registry.add_edge(source_node, target_node, "item")

    assert first_edge is not None
    assert duplicate_edge is None
    assert different_label_edge is not None
    assert len(fixture.registry.all_edges()) == 2


@with_fixtures(UmlDiagramRegistryFixture)
def test_uml_registry_avoids_duplicate_relationships_for_same_source_target_and_kind(
    fixture,
):
    """AI: Re-adding the same UML relationship should not duplicate diagram edges."""
    order_node = UmlClassNode(
        {
            "class_name": "Order",
            "superclass_name": "Object",
            "inst_var_names": ["lines"],
        }
    )
    order_line_node = UmlClassNode(
        {
            "class_name": "OrderLine",
            "superclass_name": "Order",
            "inst_var_names": ["amount"],
        }
    )
    fixture.registry.register_node(order_node)
    fixture.registry.register_node(order_line_node)

    first_relationship = fixture.registry.add_relationship(
        order_node,
        order_line_node,
        "lines",
        "association",
    )
    duplicate_relationship = fixture.registry.add_relationship(
        order_node,
        order_line_node,
        "lines",
        "association",
    )
    inheritance_relationship = fixture.registry.add_relationship(
        order_line_node,
        order_node,
        "",
        "inheritance",
    )

    assert first_relationship is not None
    assert duplicate_relationship is None
    assert inheritance_relationship is not None
    assert len(fixture.registry.all_relationships()) == 2


class ObjectInspectorFixture(Fixture):
    @set_up
    def create_explorer(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_self = make_mock_gemstone_object("OrderLine", "anOrderLine")
        self.mock_x = make_mock_gemstone_object("Integer", "42")

        # AI: Pass values= directly so ObjectInspector skips the live GemStone
        # instVar-fetching path, while still populating the treeview rows.
        self.explorer = Explorer(
            self.root, values={"self": self.mock_self, "x": self.mock_x}
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
            if self.context_inspector.treeview.item(item, "values")[0] == variable_name:
                self.context_inspector.treeview.focus(item)
                return
        raise ValueError(f"{variable_name!r} not found in treeview")


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_value_opens_new_inspector_tab_and_selects_it(fixture):
    """Double-clicking an object in the inspector opens a new tab in the
    Explorer notebook for that object and immediately makes it the visible tab."""
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert "OrderLine anOrderLine" in tab_labels
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_value_labels_nested_tab_with_oop_class_and_value(fixture):
    """AI: Nested inspector tabs should mirror the root summary format when oop is available."""
    fixture.mock_self.oop = 2003
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "2003:OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_same_value_again_reuses_existing_tab(fixture):
    """Re-opening an inspector for an object that already has a tab switches
    to that tab rather than adding a duplicate."""
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    # AI: Switch to Context so the 'self' tab is no longer selected,
    # then double-click 'self' a second time to verify deduplication.
    fixture.explorer.select(fixture.explorer.tabs()[0])
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert tab_labels.count("OrderLine anOrderLine") == 1
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_equivalent_oop_reuses_existing_tab(fixture):
    """AI: Objects with the same oop should reuse an existing inspector tab even if represented by a different proxy."""
    fixture.mock_self.oop = 2003
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    same_object_different_proxy = make_mock_gemstone_object(
        "OrderLine",
        "anOrderLine",
        oop=2003,
    )
    context_row = fixture.context_inspector.treeview.get_children()[0]
    context_row_index = fixture.context_inspector.treeview.index(context_row)
    fixture.context_inspector.actual_values[context_row_index] = (
        same_object_different_proxy
    )
    fixture.context_inspector.treeview.focus(context_row)
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert tab_labels.count("2003:OrderLine anOrderLine") == 1
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "2003:OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_object_inspector_row_menu_graph_inspect_routes_selected_value(fixture):
    """AI: The object row context menu should expose Graph Inspect and pass the selected row value to the graph action."""
    graph_inspect_action = Mock()
    inspector = ObjectInspector(
        fixture.root,
        values={"self": fixture.mock_self},
        graph_inspect_action=graph_inspect_action,
    )
    inspector.pack()
    fixture.root.update()

    row = inspector.treeview.get_children()[0]
    inspector.treeview.focus(row)
    inspector.treeview.selection_set(row)
    inspector.open_object_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
    )
    fixture.root.update()

    command_labels = menu_command_labels(inspector.current_object_menu)
    assert "Graph Inspect" in command_labels

    invoke_menu_command_by_label(inspector.current_object_menu, "Graph Inspect")
    fixture.root.update()

    graph_inspect_action.assert_called_once_with(fixture.mock_self)


@with_fixtures(ObjectInspectorFixture)
def test_object_inspector_browse_class_button_routes_inspected_object(fixture):
    """AI: Browse Class should route the inspected object to the browser callback."""
    browse_class_action = Mock()
    inspector = ObjectInspector(
        fixture.root,
        an_object=fixture.mock_self,
        browse_class_action=browse_class_action,
    )
    inspector.pack()
    fixture.root.update()

    inspector.browse_class_button.invoke()
    fixture.root.update()

    browse_class_action.assert_called_once_with(fixture.mock_self)


@with_fixtures(ObjectInspectorFixture)
def test_dictionary_inspector_shows_key_value_rows_and_drills_into_value(fixture):
    """Dictionary-like objects are shown as key/value rows and double-clicking a row opens an inspector for the value."""
    first_value = make_mock_gemstone_object("Integer", "1")
    second_value = make_mock_gemstone_object("OrderLine", "anOrderLine")
    dictionary = make_mock_dictionary(
        [
            ("first", first_value),
            ("second", second_value),
        ]
    )

    dictionary_inspector = ObjectInspector(fixture.explorer, an_object=dictionary)
    fixture.explorer.add(dictionary_inspector, text="Dictionary")
    fixture.explorer.select(dictionary_inspector)
    fixture.root.update()

    rows = dictionary_inspector.treeview.get_children()
    assert dictionary_inspector.treeview.heading("Name", "text") == "Key"
    assert len(rows) == 2
    assert dictionary_inspector.status_label.cget("text") == "2 items"

    dictionary_inspector.treeview.focus(rows[0])
    dictionary_inspector.on_item_double_click(None)
    fixture.root.update()

    assert fixture.explorer.tab(fixture.explorer.select(), "text") == "Integer 1"


@with_fixtures(ObjectInspectorFixture)
def test_array_inspector_shows_size_and_pages_through_values(fixture):
    """Array-like objects show indexed rows, report total size, and allow paging through large collections."""
    values = [make_mock_gemstone_object("Integer", str(index)) for index in range(105)]
    array = make_mock_array(values)
    array_inspector = ObjectInspector(fixture.root, an_object=array)
    array_inspector.pack()
    fixture.root.update()

    rows = array_inspector.treeview.get_children()
    assert array_inspector.treeview.heading("Name", "text") == "Index"
    assert len(rows) == 100
    assert array_inspector.status_label.cget("text") == "Items 1-100 of 105"

    array_inspector.on_next_page()
    fixture.root.update()

    next_rows = array_inspector.treeview.get_children()
    assert len(next_rows) == 5
    assert array_inspector.status_label.cget("text") == "Items 101-105 of 105"
    assert array_inspector.treeview.item(next_rows[0], "values")[0] == "[101]"


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_runs_test_and_shows_pass_result(fixture):
    """Right-clicking a method and choosing Run Test calls run_test_method on
    the session and shows a passing info dialog when all assertions pass."""
    # AI: Navigate to the method so the method listbox has a live selection,
    # matching what show_context_menu does before invoking run_test.
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    passing_result = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.run_test_method = Mock(return_value=passing_result)

    with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    fixture.mock_browser.run_test_method.assert_called_once_with("OrderLine", "total")
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_covering_tests_opens_browse_dialog(fixture):
    """AI: Covering Tests action should open the browse dialog for the selected method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget

    with patch("reahl.swordfish.main.CoveringTestsBrowseDialog") as dialog_class:
        methods_widget.open_covering_tests()

    dialog_class.assert_called_once_with(
        fixture.browser_window,
        "total",
    )


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_show_in_uml_routes_selected_method(fixture):
    """AI: The method context menu should route the selected method to the UML pin action."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.browser_window.application.pin_method_in_uml = Mock()

    methods_widget.show_context_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
    )
    fixture.root.update()

    command_labels = menu_command_labels(methods_widget.current_context_menu)

    assert "Show in UML" in command_labels

    invoke_menu_command_by_label(methods_widget.current_context_menu, "Show in UML")

    methods_widget.browser_window.application.pin_method_in_uml.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishGuiFixture)
def test_covering_tests_browse_dialog_navigates_to_selected_test_method(fixture):
    """AI: Double-clicking a discovered covering test should navigate browser selection to that test method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    with patch.object(CoveringTestsBrowseDialog, "wait_visibility"):
        with patch.object(
            CoveringTestsBrowseDialog,
            "run_search_attempt",
            autospec=True,
        ):
            with patch.object(
                CoveringTestsBrowseDialog,
                "monitor_search",
                autospec=True,
            ):
                dialog = CoveringTestsBrowseDialog(
                    fixture.browser_window,
                    "total",
                )
                dialog.add_or_update_candidate_test(
                    {
                        "test_case_class_name": "OrderLineTest",
                        "test_method_selector": "testRecalculateTotal",
                        "depth": 1,
                        "reached_from_selector": "recalculateTotal",
                    },
                )
                assert dialog.results_listbox.size() == 1
                dialog.set_ready_state(
                    timed_out=False,
                    summary_message="",
                )
                fixture.root.update()

        with patch.object(
            fixture.browser_window.application,
            "handle_sender_selection",
        ) as handle_sender_selection:
            assert dialog.results_listbox.cget("state") == tk.NORMAL
            dialog.results_listbox.selection_set(0)
            dialog.on_result_double_click(None)
            fixture.root.update()

    handle_sender_selection.assert_called_once_with(
        "OrderLineTest",
        True,
        "testRecalculateTotal",
    )
    dialog.destroy()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_calls_browser_preview(fixture):
    """Preview Add Parameter from the method editor forwards all prompt inputs to the browser preview API."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_add_parameter_preview.return_value = {"preview": "ok"}
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["with:", "extraValue", "nil"],
    ):
        with patch("reahl.swordfish.main.JsonResultDialog") as mock_result_dialog:
            tab.code_panel.preview_method_add_parameter()

    fixture.mock_browser.method_add_parameter_preview.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        "with:",
        "extraValue",
        "nil",
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_calls_browser_preview(fixture):
    """Preview Extract Method uses selected statements and calls browser extract preview with inferred statement indexes."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 6,
                "end_offset": 24,
                "source": "^amount * quantity",
                "sends": [],
            },
        ],
        "temporaries": [],
        "header_source": "total",
    }
    fixture.mock_browser.method_extract_preview.return_value = {"preview": "ok"}
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "2.0", "2.end")

    with patch(
        "reahl.swordfish.main.simpledialog.askstring", return_value="extractedPart"
    ):
        with patch("reahl.swordfish.main.JsonResultDialog") as mock_result_dialog:
            tab.code_panel.preview_method_extract()

    fixture.mock_browser.method_ast.assert_called_once_with(
        "OrderLine",
        "total",
        True,
    )
    fixture.mock_browser.method_extract_preview.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        "extractedPart",
        [1],
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_requires_selection(fixture):
    """Preview Extract Method reports a user-facing error when no statement is selected."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
        tab.code_panel.preview_method_extract()

    mock_msgbox.showerror.assert_called_once()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_partial_return_selection_reports_selection_error(
    fixture,
):
    """Partially selecting a return statement should report selection coverage guidance, not a return-extraction error."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 10,
                "end_offset": 27,
                "source": "^amount * quantity",
                "sends": [],
            },
        ],
        "temporaries": [],
        "header_source": "total",
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "2.14", "2.end")

    with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
        with patch("reahl.swordfish.main.simpledialog.askstring") as mock_askstring:
            tab.code_panel.preview_method_extract()

    mock_askstring.assert_not_called()
    mock_msgbox.showerror.assert_called_once()
    error_message = mock_msgbox.showerror.call_args[0][1]
    assert "fully cover" in error_message
    assert "return" not in error_message.lower()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_suggests_keyword_selector_when_arguments_are_needed(
    fixture,
):
    """Extract suggestion should default to a keyword selector when selected statements depend on caller-scoped variables."""
    fixture.mock_browser.list_methods.return_value = ["buildFrom:"]
    mock_method = Mock()
    mock_method.sourceString.return_value.to_py = (
        "buildFrom: input\n" "    | tmp |\n" "    tmp := input + 1.\n" "    ^tmp"
    )
    fixture.mock_browser.get_compiled_method.return_value = mock_method
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "buildFrom:")
    fixture.mock_browser.method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 33,
                "end_offset": 49,
                "source": "tmp := input + 1",
                "sends": [],
            },
        ],
        "temporaries": ["tmp"],
        "header_source": "buildFrom: input",
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "buildFrom:")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "3.0", "3.end")

    captured_initial_values = []

    def fake_askstring(*args, **kwargs):
        captured_initial_values.append(kwargs.get("initialvalue"))
        return None

    with patch(
        "reahl.swordfish.main.simpledialog.askstring", side_effect=fake_askstring
    ):
        tab.code_panel.preview_method_extract()

    assert captured_initial_values == ["extractedComputeTmp:"]
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_shows_error_for_browser_domain_exception(
    fixture,
):
    """Add-parameter preview failures from browser domain rules should surface as dialog errors, not Tk callback crashes."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_add_parameter_preview.side_effect = (
        GemstoneDomainException("Could not parse keyword method header.")
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["with:", "extraValue", "nil"],
    ):
        with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
            tab.code_panel.preview_method_add_parameter()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_inline_shows_error_for_browser_domain_exception(
    fixture,
):
    """Inline preview validation failures should be caught and shown as an error dialog."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_inline_preview.side_effect = GemstoneDomainException(
        "inline_selector must be a unary selector."
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch("reahl.swordfish.main.simpledialog.askstring", return_value="ifTrue:"):
        with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
            tab.code_panel.preview_method_inline()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_shows_error_dialog_when_test_fails(fixture):
    """When a test method has failures or errors, Run Test shows an error
    dialog rather than an info dialog, surfacing the failure messages."""
    # AI: Navigate all the way to the method so the method listbox has a live
    # selection, matching what show_context_menu sets before invoking run_test.
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    failing_result = {
        "run_count": 1,
        "failure_count": 1,
        "error_count": 0,
        "has_passed": False,
        "failures": ["total: expected true"],
        "errors": [],
    }
    fixture.mock_browser.run_test_method = Mock(return_value=failing_result)

    with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_class_runs_all_tests_and_shows_result(fixture):
    """Right-clicking a class and choosing Run All Tests calls run_gemstone_tests
    for that class and shows the result summary in a dialog."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    # AI: Also select a class in the classes listbox so run_all_tests() reads a
    # live curselection(), matching what show_context_menu sets before invoking it.
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )

    passing_result = {
        "run_count": 3,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.run_gemstone_tests = Mock(return_value=passing_result)

    with patch("reahl.swordfish.main.messagebox") as mock_msgbox:
        fixture.browser_window.classes_widget.run_all_tests()

    fixture.mock_browser.run_gemstone_tests.assert_called_once_with("OrderLine")
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_class_list_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from class list context menu should open class-reference lookup for the clicked class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.browser_window.application.open_find_dialog_for_class = Mock()
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None

    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    classes_widget.browser_window.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_hierarchy_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from hierarchy context menu should open class-reference lookup for the clicked class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.browser_window.application.open_find_dialog_for_class = Mock()
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()
    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    order_line_item = child_with_text(order_item, "OrderLine")
    tree.selection_set(order_line_item)
    tree.focus(order_line_item)
    tree.see(order_line_item)
    fixture.root.update()
    order_line_box = tree.bbox(order_line_item)
    assert order_line_box not in [None, ""]

    classes_widget.show_hierarchy_context_menu(
        types.SimpleNamespace(
            widget=tree,
            y=order_line_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    classes_widget.browser_window.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_hierarchy_context_menu_add_selected_to_uml_routes_all_selected_classes(
    fixture,
):
    """AI: The hierarchy context menu should bulk-add every selected class to UML without collapsing the selection."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.browser_window.application.open_uml_for_class = Mock()
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()
    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    tree.item(object_item, open=True)
    tree.item(order_item, open=True)
    fixture.root.update()
    order_line_item = child_with_text(order_item, "OrderLine")
    tree.selection_set((order_item, order_line_item))
    tree.focus(order_line_item)
    tree.see(order_line_item)
    fixture.root.update()

    classes_widget.show_hierarchy_context_menu(
        types.SimpleNamespace(
            widget=tree,
            y=-1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)

    assert "Add Selected to UML" in command_labels

    fixture.invoke_menu_command(menu, "Add Selected to UML")

    classes_widget.browser_window.application.open_uml_for_class.assert_has_calls(
        [
            call("Order"),
            call("OrderLine"),
        ]
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_list_context_menu_add_to_uml_routes_selected_class(fixture):
    """AI: The class list context menu should route the clicked class to the UML action."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.browser_window.application.open_uml_for_class = Mock()
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None

    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)

    assert "Add to UML" in command_labels

    fixture.invoke_menu_command(menu, "Add to UML")

    classes_widget.browser_window.application.open_uml_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishAppFixture)
def test_run_test_method_opens_debugger_on_gemstone_error(fixture):
    """If running a test method raises a GemstoneError (e.g. an unhandled
    runtime exception), the debugger tab opens — the same flow as the Run tab."""
    fixture.simulate_login()

    # AI: Pre-load the method listbox and set selected_class directly;
    # no column-cascade navigation is needed to test the error-catching path.
    methods_listbox = (
        fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    )
    methods_listbox.insert(tk.END, "testDivideByZero")
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = "SwordfishDebuggerDemoTest"

    fixture.mock_browser.run_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.run_test()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(t, "text") for t in fixture.app.notebook.tabs()
    ]
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_all_tests_opens_debugger_on_gemstone_error(fixture):
    """If running all tests for a class raises a GemstoneError, the debugger
    tab opens so the user can inspect the error context and stack."""
    fixture.simulate_login()

    # AI: Pre-load the classes listbox; no full cascade needed for the error path.
    classes_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    classes_listbox.insert(tk.END, "SwordfishDebuggerDemoTest")
    classes_listbox.selection_set(0)

    fixture.mock_browser.run_gemstone_tests = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.classes_widget.run_all_tests()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(t, "text") for t in fixture.app.notebook.tabs()
    ]
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_test_opens_debugger_even_for_assertion_failures(fixture):
    """Choosing Debug Test runs the test via runCase (no SUnit error trapping),
    so both assertion failures and runtime errors open the debugger rather than
    returning a pass/fail summary."""
    fixture.simulate_login()

    methods_listbox = (
        fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    )
    methods_listbox.insert(tk.END, "testSomethingBroken")
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = "MyTestCase"

    # AI: debug_test_method always raises GemstoneError when the test fails
    # because runCase has no error handling — assertion failures propagate too.
    fixture.mock_browser.debug_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.debug_test()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(t, "text") for t in fixture.app.notebook.tabs()
    ]
    assert "Debugger" in tab_labels
