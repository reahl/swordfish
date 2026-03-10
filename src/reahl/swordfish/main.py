#!/var/local/gemstone/venv/wonka/bin/python

import argparse
import asyncio
import json
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
import weakref
from collections import deque
from tkinter import ttk

from reahl.ptongue import GemstoneError, LinkedSession, RPCSession

from reahl.swordfish.gemstone import GemstoneBrowserSession, GemstoneDebugSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.mcp.integration_state import current_integrated_session_state
from reahl.swordfish.mcp.server import McpDependencyNotInstalled, create_server


class DomainException(Exception):
    pass


GRAPH_NODE_WIDTH = 200
GRAPH_NODE_HEIGHT = 60
GRAPH_NODE_PADDING_X = 40
GRAPH_NODE_PADDING_Y = 40
GRAPH_NODES_PER_ROW = 4
GRAPH_ORIGIN_X = 60
GRAPH_ORIGIN_Y = 60
UML_NODE_WIDTH = 240
UML_NODE_MIN_HEIGHT = 56
UML_NODE_PADDING_X = 40
UML_NODE_PADDING_Y = 40
UML_NODES_PER_ROW = 4
UML_ORIGIN_X = 60
UML_ORIGIN_Y = 60
UML_METHOD_LINE_HEIGHT = 18
UML_HEADER_HEIGHT = 26


def uml_method_label(show_instance_side, method_selector):
    if show_instance_side:
        return method_selector
    return f"class>>{method_selector}"


def close_popup_menu(menu):
    try:
        menu.unpost()
    except tk.TclError:
        pass


def add_close_command_to_popup_menu(menu):
    if menu.index("end") is not None:
        menu.add_separator()
    menu.add_command(
        label="Close Menu",
        command=lambda current_menu=menu: close_popup_menu(current_menu),
    )


def popup_menu(menu, event):
    menu.bind(
        "<Escape>",
        lambda popup_event, current_menu=menu: close_popup_menu(current_menu),
    )
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


class EditableText:
    def __init__(self, text_widget, clipboard_owner):
        self.text_widget = text_widget
        self.clipboard_owner = clipboard_owner

    def selected_range(self):
        start_index = None
        end_index = None
        try:
            start_index = self.text_widget.index(tk.SEL_FIRST)
            end_index = self.text_widget.index(tk.SEL_LAST)
        except tk.TclError:
            pass
        return start_index, end_index

    def delete_selection(self):
        start_index, end_index = self.selected_range()
        if start_index is None:
            return False
        self.text_widget.mark_set(tk.INSERT, start_index)
        self.text_widget.delete(start_index, end_index)
        return True

    def select_all(self):
        self.text_widget.tag_add(tk.SEL, "1.0", "end-1c")
        self.text_widget.mark_set(tk.INSERT, "1.0")
        self.text_widget.see(tk.INSERT)

    def copy_selection(self):
        start_index, end_index = self.selected_range()
        if start_index is None:
            return
        selected_text = self.text_widget.get(start_index, end_index)
        self.clipboard_owner.clipboard_clear()
        self.clipboard_owner.clipboard_append(selected_text)

    def clipboard_text(self):
        clipboard_text = None
        try:
            clipboard_text = self.clipboard_owner.clipboard_get()
        except tk.TclError:
            pass
        return clipboard_text

    def paste(self):
        clipboard_text = self.clipboard_text()
        if clipboard_text is None:
            return
        autoseparators_enabled = True
        can_configure_autoseparators = True
        try:
            autoseparators_value = self.text_widget.cget("autoseparators")
            autoseparators_enabled = bool(int(autoseparators_value))
        except (tk.TclError, TypeError, ValueError):
            can_configure_autoseparators = False

        if can_configure_autoseparators:
            self.text_widget.configure(autoseparators=False)
        self.text_widget.edit_separator()
        self.delete_selection()
        self.text_widget.insert(tk.INSERT, clipboard_text)
        self.text_widget.edit_separator()
        if can_configure_autoseparators and autoseparators_enabled:
            self.text_widget.configure(autoseparators=True)

    def undo(self):
        try:
            self.text_widget.edit_undo()
        except tk.TclError:
            pass

    def delete_selection_before_typing(self, event):
        control_key_pressed = bool(event.state & 0x4)
        if control_key_pressed:
            return
        inserts_character = bool(event.char)
        inserts_control_character = event.keysym in ("Return", "KP_Enter", "Tab")
        if inserts_character or inserts_control_character:
            self.delete_selection()


class CodeLineNumberColumn:
    def __init__(self, parent, text_widget, external_yscrollcommand=None):
        self.parent = parent
        self.text_widget = text_widget
        self.external_yscrollcommand = external_yscrollcommand
        self.line_numbers_text = tk.Text(
            parent,
            width=4,
            wrap="none",
            padx=6,
            takefocus=0,
            state="disabled",
            borderwidth=0,
            highlightthickness=0,
            background="#f2f2f2",
            foreground="#666666",
            cursor="arrow",
        )
        self.line_numbers_text.tag_configure(
            "line_number_alignment",
            justify="right",
        )
        self.line_numbers_text.bind("<MouseWheel>", self.scroll_main_text)
        self.line_numbers_text.bind("<Button-4>", self.scroll_main_text)
        self.line_numbers_text.bind("<Button-5>", self.scroll_main_text)
        self.line_numbers_text.bind("<Button-1>", self.ignore_mouse_click)

        self.text_widget.bind("<<Modified>>", self.on_text_modified, add="+")
        self.text_widget.bind("<Configure>", self.refresh_line_numbers, add="+")
        self.text_widget.bind("<KeyRelease>", self.refresh_line_numbers, add="+")
        self.text_widget.bind("<ButtonRelease-1>", self.refresh_line_numbers, add="+")
        self.text_widget.configure(yscrollcommand=self.on_text_scrolled)

        self.clear_modified_flag()
        self.refresh_line_numbers()

    def clear_modified_flag(self):
        try:
            self.text_widget.edit_modified(False)
        except tk.TclError:
            pass

    def on_text_modified(self, event=None):
        text_is_marked_modified = False
        try:
            text_is_marked_modified = bool(self.text_widget.edit_modified())
        except tk.TclError:
            text_is_marked_modified = True
        if text_is_marked_modified:
            self.clear_modified_flag()
            self.refresh_line_numbers()

    def ignore_mouse_click(self, event=None):
        return "break"

    def scroll_units_for_event(self, event):
        mouse_delta = 0
        if hasattr(event, "delta"):
            mouse_delta = event.delta
        if mouse_delta > 0:
            return -1
        if mouse_delta < 0:
            return 1
        button_number = getattr(event, "num", None)
        if button_number == 4:
            return -1
        if button_number == 5:
            return 1
        return 0

    def scroll_main_text(self, event):
        scroll_units = self.scroll_units_for_event(event)
        if scroll_units == 0:
            return None
        self.text_widget.yview_scroll(scroll_units, "units")
        self.sync_scroll_position()
        return "break"

    def on_text_scrolled(self, first_fraction, last_fraction):
        self.line_numbers_text.yview_moveto(first_fraction)
        if self.external_yscrollcommand:
            self.external_yscrollcommand(first_fraction, last_fraction)

    def line_count(self):
        line_number = int(self.text_widget.index("end-1c").split(".")[0])
        if line_number < 1:
            return 1
        return line_number

    def line_number_text_for_count(self, line_count):
        line_numbers = []
        for line_number in range(1, line_count + 1):
            line_numbers.append(str(line_number))
        return "\n".join(line_numbers)

    def sync_scroll_position(self):
        first_fraction, _ = self.text_widget.yview()
        self.line_numbers_text.yview_moveto(first_fraction)

    def refresh_line_numbers(self, event=None):
        line_count = self.line_count()
        line_number_text = self.line_number_text_for_count(line_count)
        self.line_numbers_text.configure(state="normal")
        self.line_numbers_text.delete("1.0", tk.END)
        self.line_numbers_text.insert(
            "1.0",
            line_number_text,
            "line_number_alignment",
        )
        self.line_numbers_text.configure(
            width=max(3, len(str(line_count)) + 1),
        )
        self.line_numbers_text.configure(state="disabled")
        self.sync_scroll_position()


class TextCursorPositionIndicator:
    def __init__(self, text_widget, label_widget):
        self.text_widget = text_widget
        self.label_widget = label_widget
        self.text_widget.bind("<KeyRelease>", self.update_position, add="+")
        self.text_widget.bind("<ButtonRelease-1>", self.update_position, add="+")
        self.text_widget.bind("<ButtonRelease-2>", self.update_position, add="+")
        self.text_widget.bind("<ButtonRelease-3>", self.update_position, add="+")
        self.text_widget.bind("<FocusIn>", self.update_position, add="+")
        self.update_position()

    def line_and_column(self):
        try:
            line_text, zero_based_column_text = self.text_widget.index(tk.INSERT).split(
                "."
            )
            line_number = int(line_text)
            one_based_column_number = int(zero_based_column_text) + 1
            return line_number, one_based_column_number
        except (tk.TclError, ValueError):
            return None, None

    def update_position(self, event=None):
        line_number, column_number = self.line_and_column()
        if line_number is None or column_number is None:
            self.label_widget.config(text="Ln -, Col -")
            return
        self.label_widget.config(text=f"Ln {line_number}, Col {column_number}")


class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.gemstone_browser_session = GemstoneBrowserSession(gemstone_session)
        self.change_event_publisher = None
        self.integrated_session_state = None
        self.selected_package = None
        self.selected_dictionary = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.show_instance_side = True
        self.browse_mode = "dictionaries"

    def set_integrated_session_state(self, integrated_session_state):
        self.integrated_session_state = integrated_session_state

    def require_write_access(self, operation_name):
        if self.integrated_session_state is None:
            return
        if not self.integrated_session_state.is_mcp_busy():
            return
        mcp_operation_name = (
            self.integrated_session_state.current_mcp_operation_name() or "unknown"
        )
        raise DomainException(
            (
                "IDE is read-only while MCP operation %s is active. "
                "Retry %s after MCP finishes."
            )
            % (
                mcp_operation_name,
                operation_name,
            )
        )

    def publish_model_change(self, change_kind):
        if self.change_event_publisher is None:
            return
        self.change_event_publisher(change_kind)

    def select_package(self, package):
        self.selected_package = package
        self.select_class(None)

    def select_dictionary(self, dictionary_name):
        self.selected_dictionary = dictionary_name
        self.select_class(None)

    def select_class_category(self, category_name):
        if self.browse_mode == "dictionaries":
            self.selected_package = None
            self.select_dictionary(category_name)
            return
        self.selected_dictionary = None
        self.select_package(category_name)

    def selected_class_category(self):
        if self.browse_mode == "dictionaries":
            return self.selected_dictionary
        return self.selected_package

    @property
    def rowan_installed(self):
        return self.gemstone_browser_session.rowan_installed()

    def select_browse_mode(self, browse_mode):
        browse_mode = browse_mode.strip().lower()
        valid_modes = ("dictionaries", "categories", "rowan")
        if browse_mode not in valid_modes:
            raise DomainException(
                "browse_mode must be dictionaries, categories, or rowan."
            )
        if browse_mode == "rowan" and not self.rowan_installed:
            raise DomainException("Rowan is not installed on this stone.")
        if self.browse_mode == browse_mode:
            return
        self.browse_mode = browse_mode
        self.selected_package = None
        self.selected_dictionary = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.publish_model_change("packages")
        self.publish_model_change("classes")
        self.publish_model_change("methods")

    def select_instance_side(self, show_instance_side):
        self.show_instance_side = show_instance_side
        self.select_method_category(None)

    def select_class(self, selected_class):
        self.selected_class = selected_class
        self.select_method_category(None)

    def select_method_category(self, selected_method_category):
        self.selected_method_category = selected_method_category
        self.select_method_symbol(None)

    def select_method_symbol(self, selected_method_symbol):
        self.selected_method_symbol = selected_method_symbol

    def commit(self):
        self.require_write_access("commit")
        self.gemstone_session.commit()

    def abort(self):
        self.require_write_access("abort")
        self.gemstone_session.abort()

    @classmethod
    def log_in_rpc(
        cls,
        gemstone_user_name,
        gemstone_password,
        rpc_hostname,
        stone_name,
        netldi_name,
    ):
        nrs_string = f"!@{rpc_hostname}#netldi:{netldi_name}!gemnetobject"
        logging.getLogger(__name__).debug(
            f"Logging in with: {gemstone_user_name} stone_name={stone_name} netldi_task={nrs_string}"
        )
        try:
            gemstone_session = RPCSession(
                gemstone_user_name,
                gemstone_password,
                stone_name=stone_name,
                netldi_task=nrs_string,
            )
        except GemstoneError as e:
            raise DomainException("Gemstone error: %s" % e)
        return cls(gemstone_session)

    @classmethod
    def log_in_linked(cls, gemstone_user_name, gemstone_password, stone_name):
        logging.getLogger(__name__).debug(
            f"Logging in with: {gemstone_user_name} stone_name={stone_name}"
        )
        try:
            gemstone_session = LinkedSession(
                gemstone_user_name, gemstone_password, stone_name=stone_name
            )
        except GemstoneError as e:
            raise DomainException("Gemstone error: %s" % e)
        return cls(gemstone_session)

    @property
    def stone_name(self):
        return self.gemstone_session.System.stoneName().to_py

    @property
    def host_name(self):
        return self.gemstone_session.System.hostname().to_py

    @property
    def user_name(self):
        return self.gemstone_session.System.myUserProfile().userId().to_py

    @property
    def session_id(self):
        # self.gemstone_session.System.session() returns our self.gemstone_session itself, not the id we want
        return self.gemstone_session.execute("System session").to_py

    def __str__(self):
        return f"{self.session_id}: {self.user_name} on {self.stone_name} at server {self.host_name}"

    def log_out(self):
        self.gemstone_browser_session.clear_stored_breakpoints()
        self.gemstone_session.log_out()

    @property
    def class_organizer(self):
        return self.gemstone_browser_session.class_organizer

    @property
    def class_categories(self):
        if self.browse_mode == "dictionaries":
            yield from self.gemstone_browser_session.list_dictionaries()
            return
        if self.browse_mode == "categories":
            yield from self.gemstone_browser_session.list_categories()
            return
        yield from self.gemstone_browser_session.list_rowan_packages()

    def create_and_install_package(self, package_name):
        self.require_write_access("create_and_install_package")
        self.gemstone_browser_session.create_and_install_package(package_name)
        self.publish_model_change("packages")

    def delete_package(self, package_name):
        self.require_write_access("delete_package")
        self.gemstone_browser_session.delete_package(package_name)
        if self.selected_package == package_name:
            self.selected_package = None
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("packages")

    def create_class(
        self,
        class_name,
        superclass_name="Object",
        in_dictionary=None,
    ):
        self.require_write_access("create_class")
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            if self.browse_mode == "dictionaries":
                selected_dictionary = self.selected_dictionary or "UserGlobals"
            else:
                selected_dictionary = "UserGlobals"
        self.gemstone_browser_session.create_class(
            class_name=class_name,
            superclass_name=superclass_name,
            in_dictionary=selected_dictionary,
        )
        self.publish_model_change("classes")

    def delete_class(self, class_name, in_dictionary=None):
        self.require_write_access("delete_class")
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            if self.browse_mode == "dictionaries":
                selected_dictionary = self.selected_dictionary or "UserGlobals"
            else:
                selected_dictionary = "UserGlobals"
        self.gemstone_browser_session.delete_class(
            class_name,
            in_dictionary=selected_dictionary,
        )
        if self.selected_class == class_name:
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("classes")

    def get_classes_in_category(self, category):
        if self.browse_mode == "dictionaries":
            yield from self.gemstone_browser_session.list_classes_in_dictionary(
                category
            )
            return
        if self.browse_mode == "categories":
            yield from self.gemstone_browser_session.list_classes_in_category(category)
            return
        yield from self.gemstone_browser_session.list_classes_in_rowan_package(category)

    def get_categories_in_class(self, class_name, show_instance_side):
        categories = self.gemstone_browser_session.list_method_categories(
            class_name,
            show_instance_side,
        )
        if categories and categories[0] == "all":
            categories = categories[1:]
        yield from categories

    def create_method_category(
        self,
        class_name,
        show_instance_side,
        method_category,
    ):
        self.require_write_access("create_method_category")
        self.gemstone_browser_session.create_method_category(
            class_name,
            method_category,
            show_instance_side,
        )
        self.publish_model_change("methods")

    def delete_method_category(
        self,
        class_name,
        show_instance_side,
        method_category,
    ):
        self.require_write_access("delete_method_category")
        self.gemstone_browser_session.delete_method_category(
            class_name,
            method_category,
            show_instance_side,
        )
        if self.selected_method_category == method_category:
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("methods")

    def get_selectors_in_class(self, class_name, method_category, show_instance_side):
        yield from self.gemstone_browser_session.list_methods(
            class_name,
            method_category,
            show_instance_side,
        )

    def get_method(self, class_name, show_instance_side, method_symbol):
        try:
            return self.gemstone_browser_session.get_compiled_method(
                class_name,
                method_symbol,
                show_instance_side,
            )
        except GemstoneError:
            return

    def class_category_containing_class(self, class_name):
        selected_category = self.selected_class_category()
        if selected_category:
            classes_in_selected_category = list(
                self.get_classes_in_category(selected_category)
            )
            if class_name in classes_in_selected_category:
                return selected_category
        all_categories = list(self.class_categories)
        matching_category = None
        category_index = 0
        while category_index < len(all_categories) and matching_category is None:
            category_name = all_categories[category_index]
            classes_in_category = list(self.get_classes_in_category(category_name))
            if class_name in classes_in_category:
                matching_category = category_name
            category_index += 1
        return matching_category

    def jump_to_class(self, class_name, show_instance_side):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_category = self.class_category_containing_class(class_name)
        if selected_category is None:
            selected_category = selected_gemstone_class.category().to_py
        self.select_class_category(selected_category)
        self.select_instance_side(show_instance_side)
        self.select_class(class_name)

    def jump_to_method(self, class_name, show_instance_side, method_symbol):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_package = selected_gemstone_class.category().to_py
        selected_method_category = self.gemstone_browser_session.get_method_category(
            class_name,
            method_symbol,
            show_instance_side,
        )
        self.select_package(selected_package)
        self.select_class(class_name)
        self.select_instance_side(show_instance_side)
        self.select_method_category(selected_method_category)
        self.select_method_symbol(method_symbol)

    def get_current_methods(self):
        return list(
            self.get_selectors_in_class(
                self.selected_class,
                self.selected_method_category,
                self.show_instance_side,
            )
        )

    def find_class_names_matching(self, search_input, should_stop=None):
        yield from self.gemstone_browser_session.find_classes(
            search_input,
            should_stop=should_stop,
        )

    def find_selectors_matching(self, search_input, should_stop=None):
        yield from self.gemstone_browser_session.find_selectors(
            search_input,
            should_stop=should_stop,
        )

    def find_class_references(self, class_name):
        class_reference_search_result = (
            self.gemstone_browser_session.find_class_references(class_name)
        )
        yield from [
            (
                reference["class_name"],
                reference["show_instance_side"],
                reference["method_selector"],
            )
            for reference in class_reference_search_result["references"]
        ]

    def find_implementors_of_method(self, method_name):
        yield from [
            (
                implementor["class_name"],
                not implementor["show_instance_side"],
            )
            for implementor in self.gemstone_browser_session.find_implementors(
                method_name
            )
        ]

    def sender_entries_for_method(
        self,
        method_name,
        include_category_details=False,
    ):
        sender_search_result = self.gemstone_browser_session.find_senders(
            method_name,
            include_category_details=include_category_details,
        )
        return sender_search_result["senders"]

    def find_senders_of_method(self, method_name):
        yield from [
            (
                sender["class_name"],
                sender["show_instance_side"],
                sender["method_selector"],
            )
            for sender in self.sender_entries_for_method(method_name)
        ]

    def plan_sender_evidence_tests(
        self,
        method_name,
        max_depth=2,
        max_nodes=500,
        max_senders_per_selector=200,
        max_test_methods=200,
        max_elapsed_ms=1500,
        should_stop=None,
        on_candidate_test=None,
    ):
        return self.gemstone_browser_session.sender_test_plan_for_selector(
            method_name,
            max_depth,
            max_nodes,
            max_senders_per_selector,
            max_test_methods,
            max_elapsed_ms=max_elapsed_ms,
            should_stop=should_stop,
            on_candidate_test=on_candidate_test,
        )

    def collect_sender_evidence_from_tests(
        self,
        method_name,
        selected_tests,
        max_traced_senders=250,
        max_observed_results=500,
        receiver_class_name=None,
        receiver_show_instance_side=True,
    ):
        self.require_write_access('collect_sender_evidence_from_tests')
        trace_result = None
        observed_result = None
        untrace_result = None
        test_runs = []
        tracer_enabled = False
        trace_installed = False
        self.gemstone_browser_session.ensure_tracer_manifest_matches()
        self.gemstone_browser_session.enable_tracer()
        tracer_enabled = True
        try:
            if receiver_class_name is not None:
                trace_result = self.gemstone_browser_session.trace_implementation(
                    receiver_class_name,
                    receiver_show_instance_side,
                    method_name,
                )
                if not trace_result.get('instrumented'):
                    trace_result = self.gemstone_browser_session.trace_selector(
                        method_name,
                        max_results=max_traced_senders,
                    )
                    trace_result['fallback_reason'] = (
                        '%s does not define %s — tracing all implementors instead.'
                        % (receiver_class_name, method_name)
                    )
            else:
                trace_result = self.gemstone_browser_session.trace_selector(
                    method_name,
                    max_results=max_traced_senders,
                )
            trace_installed = True
            self.gemstone_browser_session.clear_observed_senders(method_name)
            for selected_test in selected_tests:
                test_case_class_name = selected_test['test_case_class_name']
                test_method_selector = selected_test['test_method_selector']
                test_result = self.run_test_method(
                    test_case_class_name,
                    test_method_selector,
                )
                test_runs.append(
                    {
                        'test_case_class_name': test_case_class_name,
                        'test_method_selector': test_method_selector,
                        'depth': selected_test.get('depth'),
                        'tests_passed': test_result['has_passed'],
                        'result': test_result,
                    }
                )
            observed_result = (
                self.gemstone_browser_session.observed_senders_for_selector(
                    method_name,
                    max_results=max_observed_results,
                    count_only=False,
                )
            )
        finally:
            if trace_installed:
                try:
                    untrace_result = self.gemstone_browser_session.untrace_selector(
                        method_name
                    )
                except (
                    GemstoneDomainException,
                    GemstoneError,
                ):
                    untrace_result = None
            if tracer_enabled:
                try:
                    self.gemstone_browser_session.disable_tracer()
                except (
                    GemstoneDomainException,
                    GemstoneError,
                ):
                    pass
        return {
            'method_name': method_name,
            'trace': trace_result,
            'test_runs': test_runs,
            'observed': observed_result,
            'untrace': untrace_result,
        }

    def method_sends(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_sends(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_structure_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_structure_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_control_flow_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_control_flow_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_ast(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_ast(
            class_name,
            method_selector,
            show_instance_side,
        )

    def preview_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        return self.gemstone_browser_session.method_rename_preview(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )

    def apply_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        self.require_write_access("apply_method_rename")
        rename_result = self.gemstone_browser_session.apply_method_rename(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )
        self.publish_model_change("methods")
        return rename_result

    def preview_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        return self.gemstone_browser_session.method_move_preview(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
        )

    def apply_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
        overwrite_target_method=False,
        delete_source_method=True,
    ):
        self.require_write_access("apply_method_move")
        move_result = self.gemstone_browser_session.apply_method_move(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
            overwrite_target_method=overwrite_target_method,
            delete_source_method=delete_source_method,
        )
        self.publish_model_change("methods")
        return move_result

    def preview_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        return self.gemstone_browser_session.method_add_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )

    def apply_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        self.require_write_access("apply_method_add_parameter")
        add_parameter_result = self.gemstone_browser_session.apply_method_add_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )
        self.publish_model_change("methods")
        return add_parameter_result

    def preview_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        rewrite_source_senders=False,
    ):
        return self.gemstone_browser_session.method_remove_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            rewrite_source_senders=rewrite_source_senders,
        )

    def apply_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        overwrite_new_method=False,
        rewrite_source_senders=False,
    ):
        self.require_write_access("apply_method_remove_parameter")
        remove_parameter_result = (
            self.gemstone_browser_session.apply_method_remove_parameter(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                overwrite_new_method=overwrite_new_method,
                rewrite_source_senders=rewrite_source_senders,
            )
        )
        self.publish_model_change("methods")
        return remove_parameter_result

    def preview_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
    ):
        return self.gemstone_browser_session.method_extract_preview(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        )

    def apply_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
        overwrite_new_method=False,
    ):
        self.require_write_access("apply_method_extract")
        extract_result = self.gemstone_browser_session.apply_method_extract(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
            overwrite_new_method=overwrite_new_method,
        )
        self.publish_model_change("methods")
        return extract_result

    def preview_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
    ):
        return self.gemstone_browser_session.method_inline_preview(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
        )

    def apply_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
        delete_inlined_method=False,
    ):
        self.require_write_access("apply_method_inline")
        inline_result = self.gemstone_browser_session.apply_method_inline(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
            delete_inlined_method=delete_inlined_method,
        )
        self.publish_model_change("methods")
        return inline_result

    def update_method_source(
        self, selected_class, show_instance_side, method_symbol, source
    ):
        self.require_write_access("update_method_source")
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
        )
        self.publish_model_change("methods")

    def create_method(
        self,
        selected_class,
        show_instance_side,
        source,
        method_category="as yet unclassified",
    ):
        self.require_write_access("create_method")
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
            method_category=method_category,
        )
        self.publish_model_change("methods")

    def delete_method(self, selected_class, show_instance_side, method_selector):
        self.require_write_access("delete_method")
        self.gemstone_browser_session.delete_method(
            selected_class,
            method_selector,
            show_instance_side,
        )
        if self.selected_method_symbol == method_selector:
            self.selected_method_symbol = None
        self.publish_model_change("methods")

    def run_code(self, source):
        self.require_write_access("run_code")
        return self.gemstone_browser_session.run_code(source)

    def resolve_object(self, source):
        return self.gemstone_browser_session.run_code(source)

    def run_gemstone_tests(self, class_name):
        self.require_write_access("run_gemstone_tests")
        return self.gemstone_browser_session.run_gemstone_tests(class_name)

    def run_test_method(self, class_name, method_selector):
        self.require_write_access("run_test_method")
        return self.gemstone_browser_session.run_test_method(
            class_name, method_selector
        )

    def debug_test_method(self, class_name, method_selector):
        self.require_write_access("debug_test_method")
        return self.gemstone_browser_session.debug_test_method(
            class_name, method_selector
        )

    def set_breakpoint(
        self,
        class_name,
        show_instance_side,
        method_selector,
        source_offset,
    ):
        self.require_write_access("set_breakpoint")
        return self.gemstone_browser_session.set_breakpoint(
            class_name,
            method_selector,
            show_instance_side,
            source_offset,
        )

    def clear_breakpoint(self, breakpoint_id):
        self.require_write_access("clear_breakpoint")
        return self.gemstone_browser_session.clear_breakpoint(breakpoint_id)

    def clear_breakpoint_at(
        self,
        class_name,
        show_instance_side,
        method_selector,
        source_offset,
    ):
        self.require_write_access("clear_breakpoint_at")
        return self.gemstone_browser_session.clear_breakpoint_at(
            class_name,
            method_selector,
            show_instance_side,
            source_offset,
        )

    def list_breakpoints(self):
        return self.gemstone_browser_session.list_breakpoints()

    def clear_all_breakpoints(self):
        self.require_write_access("clear_all_breakpoints")
        return self.gemstone_browser_session.clear_all_breakpoints()

# except GemstoneError as e:
#     try:
#         e.context.gciStepOverFromLevel(1)
#     except GemstoneError as ex:
#         result = ex.continue_with()


UI_CONTEXT_SEQUENCE = 0
UI_CONTEXT_SEQUENCE_LOCK = threading.RLock()


def next_ui_context_identifier(tab_id):
    global UI_CONTEXT_SEQUENCE
    with UI_CONTEXT_SEQUENCE_LOCK:
        UI_CONTEXT_SEQUENCE = UI_CONTEXT_SEQUENCE + 1
        return '%s-%s' % (tab_id, UI_CONTEXT_SEQUENCE)


class UiContext:
    def __init__(self, tab_id):
        self.tab_id = next_ui_context_identifier(tab_id)
        self.version = 0
        self.alive = True
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return (self.tab_id, self.version)

    def invalidate(self):
        with self.lock:
            if self.alive:
                self.alive = False
                self.version = self.version + 1

    def matches(self, snapshot):
        with self.lock:
            return self.alive and snapshot == (self.tab_id, self.version)


class UiDispatcher:
    def __init__(self, root):
        self.root = root
        self.pending_callbacks = deque()
        self.lock = threading.RLock()
        self.flush_scheduled = False

    def dispatch(self, callback, *args, **kwargs):
        should_schedule_flush = False
        with self.lock:
            self.pending_callbacks.append((callback, args, kwargs))
            should_schedule_flush = not self.flush_scheduled
            if should_schedule_flush:
                self.flush_scheduled = True
        if should_schedule_flush:
            try:
                self.root.after(0, self.flush_pending_callbacks)
            except tk.TclError:
                with self.lock:
                    self.flush_scheduled = False

    def flush_pending_callbacks(self):
        pending_callbacks = []
        with self.lock:
            while self.pending_callbacks:
                pending_callbacks.append(self.pending_callbacks.popleft())
            self.flush_scheduled = False
        for callback, args, kwargs in pending_callbacks:
            callback(*args, **kwargs)


class BusyCoordinator:
    def __init__(self):
        self.lock = threading.RLock()
        self.active_lease_token = 0
        self.next_lease_token = 0
        self.active_operation_name = ''
        self.busy = False

    def lease_for_state(self, is_busy=False, operation_name=''):
        with self.lock:
            if is_busy:
                operation_changed = operation_name != self.active_operation_name
                if not self.busy or operation_changed:
                    self.next_lease_token = self.next_lease_token + 1
                    self.active_lease_token = self.next_lease_token
                self.busy = True
                self.active_operation_name = operation_name
                return self.active_lease_token
            self.busy = False
            self.active_operation_name = ''
            self.active_lease_token = 0
            return self.active_lease_token

    def is_current_lease(self, lease_token):
        with self.lock:
            if lease_token is None:
                return True
            if self.busy:
                return lease_token == self.active_lease_token
            return lease_token == 0


class ActionGate:
    def __init__(self):
        self.actions_blocked_while_busy = {
            'session',
            'run',
            'breakpoints',
            'run_editor_source',
            'method_editor_source',
            'ide_write',
            'mcp_stop',
        }

    def allows(self, action_name, is_busy=False):
        if is_busy and action_name in self.actions_blocked_while_busy:
            return False
        return True

    def state_for(self, action_name, is_busy=False):
        if self.allows(action_name, is_busy=is_busy):
            return tk.NORMAL
        return tk.DISABLED

    def read_only_for(self, action_name, is_busy=False):
        return not self.allows(action_name, is_busy=is_busy)


def configure_widget_if_alive(widget, **configuration):
    if widget is None:
        return
    widget_exists = False
    try:
        widget_exists = bool(widget.winfo_exists())
    except tk.TclError:
        widget_exists = False
    if widget_exists:
        try:
            widget.configure(**configuration)
        except tk.TclError:
            pass


class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = deque()
        self.queue_lock = threading.RLock()
        self.root_thread_ident = threading.get_ident()
        self.wakeup_read_descriptor = None
        self.wakeup_write_descriptor = None
        self.processing_events = False
        self.ui_dispatcher = UiDispatcher(self.root)
        self.root.bind('<<CustomEventsPublished>>', self.schedule_event_processing)
        self.configure_cross_thread_wakeup()

    def schedule_event_processing(self, event=None):
        self.ui_dispatcher.dispatch(self.process_events)

    def subscription_is_active(self, ui_context, context_snapshot):
        if ui_context is None:
            return True
        if context_snapshot is None:
            return False
        return ui_context.matches(context_snapshot)

    def configure_cross_thread_wakeup(self):
        supports_filehandler = hasattr(self.root, "createfilehandler")
        if not supports_filehandler:
            return
        try:
            read_descriptor, write_descriptor = os.pipe()
            os.set_blocking(read_descriptor, False)
            os.set_blocking(write_descriptor, False)
            self.root.createfilehandler(
                read_descriptor,
                tk.READABLE,
                self.process_cross_thread_wakeup,
            )
            self.wakeup_read_descriptor = read_descriptor
            self.wakeup_write_descriptor = write_descriptor
        except (AttributeError, OSError):
            self.wakeup_read_descriptor = None
            self.wakeup_write_descriptor = None

    def callback_reference_for(self, callback):
        try:
            return weakref.WeakMethod(callback)
        except TypeError:
            return weakref.ref(callback)

    def subscribe(self, event_name, callback, *args, ui_context=None):
        context_snapshot = None
        if ui_context is not None:
            context_snapshot = ui_context.snapshot()
        self.events.setdefault(event_name, [])
        self.events[event_name].append(
            (
                self.callback_reference_for(callback),
                args,
                ui_context,
                context_snapshot,
            )
        )

    def publish(self, event_name, *args, **kwargs):
        if event_name in self.events:
            with self.queue_lock:
                self.queue.append((event_name, args, kwargs))
        if threading.get_ident() == self.root_thread_ident:
            if self.processing_events:
                return
            self.process_events()
            return
        self.publish_cross_thread_wakeup()

    def publish_cross_thread_wakeup(self):
        if self.wakeup_write_descriptor is not None:
            try:
                os.write(self.wakeup_write_descriptor, b"1")
            except OSError:
                pass
            return
        try:
            self.root.event_generate("<<CustomEventsPublished>>")
        except tk.TclError:
            pass

    def process_cross_thread_wakeup(self, file_descriptor, wakeup_mask):
        if self.wakeup_read_descriptor is not None:
            while True:
                try:
                    wakeup_payload = os.read(self.wakeup_read_descriptor, 1024)
                except BlockingIOError:
                    break
                except OSError:
                    break
                if wakeup_payload == b"":
                    break
                if len(wakeup_payload) < 1024:
                    break
        self.schedule_event_processing()

    def process_events(self):
        if self.processing_events:
            return
        self.processing_events = True
        try:
            while True:
                with self.queue_lock:
                    if not self.queue:
                        break
                    event_name, args, kwargs = self.queue.popleft()
                if event_name in self.events:
                    logging.getLogger(__name__).debug(f"Processing: {event_name}")
                    retained_callbacks = []
                    for (
                        weak_callback,
                        callback_args,
                        ui_context,
                        context_snapshot,
                    ) in self.events[event_name]:
                        callback = weak_callback()
                        callback_is_live = callback is not None
                        context_is_active = self.subscription_is_active(
                            ui_context,
                            context_snapshot,
                        )
                        if callback_is_live and context_is_active:
                            retained_callbacks.append(
                                (
                                    weak_callback,
                                    callback_args,
                                    ui_context,
                                    context_snapshot,
                                )
                            )
                            logging.getLogger(__name__).debug(f"Calling: {callback}")
                            callback(*callback_args, *args, **kwargs)
                    self.events[event_name] = retained_callbacks
        finally:
            self.processing_events = False

    def clear_subscribers(self, owner):
        for event_name, registered_callbacks in self.events.copy().items():
            cleaned_callbacks = []
            for (
                weak_callback,
                callback_args,
                ui_context,
                context_snapshot,
            ) in registered_callbacks:
                callback = weak_callback()
                callback_is_live = callback is not None
                owner_matches = False
                if callback_is_live:
                    owner_matches = getattr(callback, "__self__", None) is owner
                if callback_is_live and not owner_matches:
                    cleaned_callbacks.append(
                        (
                            weak_callback,
                            callback_args,
                            ui_context,
                            context_snapshot,
                        )
                    )
            self.events[event_name] = cleaned_callbacks

    def close(self):
        if self.wakeup_read_descriptor is not None and hasattr(
            self.root, "deletefilehandler"
        ):
            try:
                self.root.deletefilehandler(self.wakeup_read_descriptor)
            except tk.TclError:
                pass
        if self.wakeup_read_descriptor is not None:
            try:
                os.close(self.wakeup_read_descriptor)
            except OSError:
                pass
            self.wakeup_read_descriptor = None
        if self.wakeup_write_descriptor is not None:
            try:
                os.close(self.wakeup_write_descriptor)
            except OSError:
                pass
            self.wakeup_write_descriptor = None


MCP_RUNTIME_CONFIG_SCHEMA_VERSION = 2
MCP_RUNTIME_CONFIG_FILE_NAME = "mcp.json"


class McpConfigurationStore:
    def config_home_directory(self):
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg_config_home:
            return xdg_config_home
        return os.path.join(os.path.expanduser("~"), ".config")

    def config_file_path(self):
        return os.path.join(
            self.config_home_directory(),
            "swordfish",
            MCP_RUNTIME_CONFIG_FILE_NAME,
        )

    def validate_config_dict(self, config_payload):
        if not isinstance(config_payload, dict):
            raise ValueError("mcp_runtime_config must be an object.")
        if "mcp_host" in config_payload:
            mcp_host = str(config_payload["mcp_host"]).strip()
            if not mcp_host:
                raise ValueError("mcp_host cannot be empty.")
        if "mcp_port" in config_payload:
            mcp_port = config_payload["mcp_port"]
            if isinstance(mcp_port, bool) or not isinstance(mcp_port, int):
                raise ValueError("mcp_port must be an integer.")
            if mcp_port <= 0:
                raise ValueError("mcp_port must be greater than zero.")
        if "mcp_http_path" in config_payload:
            mcp_http_path = str(config_payload["mcp_http_path"]).strip()
            if not mcp_http_path.startswith("/"):
                raise ValueError("mcp_http_path must start with '/'.")
        return config_payload

    def load(self):
        config_file_path = self.config_file_path()
        if not os.path.exists(config_file_path):
            return None
        try:
            with open(config_file_path, "r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
            if not isinstance(payload, dict):
                return None
            schema_version = payload.get(
                "schema_version",
                MCP_RUNTIME_CONFIG_SCHEMA_VERSION,
            )
            if schema_version != MCP_RUNTIME_CONFIG_SCHEMA_VERSION:
                return None
            config_payload = payload.get("mcp_runtime_config")
            validated_payload = self.validate_config_dict(config_payload)
            return McpRuntimeConfig.from_dict(validated_payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save(self, runtime_config):
        config_file_path = self.config_file_path()
        config_directory = os.path.dirname(config_file_path)
        payload = {
            "schema_version": MCP_RUNTIME_CONFIG_SCHEMA_VERSION,
            "mcp_runtime_config": runtime_config.to_dict(),
        }
        temporary_file_path = config_file_path + ".tmp"
        try:
            os.makedirs(config_directory, exist_ok=True)
            with open(temporary_file_path, "w", encoding="utf-8") as config_file:
                json.dump(payload, config_file, indent=2, sort_keys=True)
                config_file.write("\n")
            os.replace(temporary_file_path, config_file_path)
            os.chmod(config_file_path, 0o600)
        except OSError as error:
            try:
                os.remove(temporary_file_path)
            except OSError:
                pass
            raise DomainException(
                "Unable to save MCP configuration to %s: %s" % (config_file_path, error)
            )

    def argument_is_explicitly_set(self, argument_tokens, option_name):
        option_prefix = option_name + "="
        for argument_token in argument_tokens:
            if argument_token == option_name:
                return True
            if argument_token.startswith(option_prefix):
                return True
        return False

    def explicit_overrides_from_argument_tokens(self, argument_tokens):
        explicit_overrides = {}
        if self.argument_is_explicitly_set(argument_tokens, "--allow-source-read"):
            explicit_overrides["allow_source_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--disallow-source-read"):
            explicit_overrides["allow_source_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-source-write"):
            explicit_overrides["allow_source_write"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-eval-arbitrary"):
            explicit_overrides["allow_eval_arbitrary"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-ide-read"):
            explicit_overrides["allow_ide_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--disallow-ide-read"):
            explicit_overrides["allow_ide_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-ide-write"):
            explicit_overrides["allow_ide_write"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-test-execution"):
            explicit_overrides["allow_test_execution"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-commit"):
            explicit_overrides["allow_commit"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-tracing"):
            explicit_overrides["allow_tracing"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--require-gemstone-ast"):
            explicit_overrides["require_gemstone_ast"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-host"):
            explicit_overrides["mcp_host"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-port"):
            explicit_overrides["mcp_port"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-http-path"):
            explicit_overrides["mcp_http_path"] = True
        return explicit_overrides

    def config_from_arguments(self, arguments):
        return McpRuntimeConfig(
            allow_source_read=getattr(arguments, "allow_source_read", True),
            allow_source_write=getattr(arguments, "allow_source_write", False),
            allow_eval_arbitrary=getattr(arguments, "allow_eval_arbitrary", False),
            allow_test_execution=getattr(arguments, "allow_test_execution", False),
            allow_ide_read=getattr(arguments, "allow_ide_read", True),
            allow_ide_write=getattr(arguments, "allow_ide_write", False),
            allow_commit=getattr(arguments, "allow_commit", False),
            allow_tracing=getattr(arguments, "allow_tracing", False),
            require_gemstone_ast=getattr(arguments, "require_gemstone_ast", False),
            mcp_host=getattr(arguments, "mcp_host", "127.0.0.1"),
            mcp_port=getattr(arguments, "mcp_port", 8000),
            mcp_http_path=getattr(arguments, "mcp_http_path", "/mcp"),
        )

    def merged_config_from_arguments(
        self,
        arguments,
        argument_tokens=None,
        persisted_runtime_config=None,
    ):
        cli_runtime_config = self.config_from_arguments(arguments)
        if persisted_runtime_config is None:
            persisted_runtime_config = self.load()
        if persisted_runtime_config is None:
            return cli_runtime_config
        if argument_tokens is None:
            argument_tokens = []
        explicit_overrides = self.explicit_overrides_from_argument_tokens(
            argument_tokens
        )
        if len(explicit_overrides) < 1:
            return persisted_runtime_config.copy()
        merged_runtime_config = persisted_runtime_config.copy()
        merged_runtime_config.update_with(
            allow_source_read=(
                cli_runtime_config.allow_source_read
                if explicit_overrides.get("allow_source_read")
                else None
            ),
            allow_source_write=(
                cli_runtime_config.allow_source_write
                if explicit_overrides.get("allow_source_write")
                else None
            ),
            allow_eval_arbitrary=(
                cli_runtime_config.allow_eval_arbitrary
                if explicit_overrides.get("allow_eval_arbitrary")
                else None
            ),
            allow_test_execution=(
                cli_runtime_config.allow_test_execution
                if explicit_overrides.get("allow_test_execution")
                else None
            ),
            allow_ide_read=(
                cli_runtime_config.allow_ide_read
                if explicit_overrides.get("allow_ide_read")
                else None
            ),
            allow_ide_write=(
                cli_runtime_config.allow_ide_write
                if explicit_overrides.get("allow_ide_write")
                else None
            ),
            allow_commit=(
                cli_runtime_config.allow_commit
                if explicit_overrides.get("allow_commit")
                else None
            ),
            allow_tracing=(
                cli_runtime_config.allow_tracing
                if explicit_overrides.get("allow_tracing")
                else None
            ),
            require_gemstone_ast=(
                cli_runtime_config.require_gemstone_ast
                if explicit_overrides.get("require_gemstone_ast")
                else None
            ),
            mcp_host=(
                cli_runtime_config.mcp_host
                if explicit_overrides.get("mcp_host")
                else None
            ),
            mcp_port=(
                cli_runtime_config.mcp_port
                if explicit_overrides.get("mcp_port")
                else None
            ),
            mcp_http_path=(
                cli_runtime_config.mcp_http_path
                if explicit_overrides.get("mcp_http_path")
                else None
            ),
        )
        return merged_runtime_config


class McpRuntimeConfig:
    def __init__(
        self,
        allow_source_read=True,
        allow_source_write=False,
        allow_eval_arbitrary=False,
        allow_test_execution=False,
        allow_ide_read=True,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=False,
        require_gemstone_ast=False,
        mcp_host="127.0.0.1",
        mcp_port=8000,
        mcp_http_path="/mcp",
    ):
        self.allow_source_read = allow_source_read
        self.allow_source_write = allow_source_write
        self.allow_eval_arbitrary = allow_eval_arbitrary
        self.allow_test_execution = allow_test_execution
        self.allow_ide_read = allow_ide_read
        self.allow_ide_write = allow_ide_write
        self.allow_commit = allow_commit
        self.allow_tracing = allow_tracing
        self.require_gemstone_ast = require_gemstone_ast
        self.mcp_host = mcp_host
        self.mcp_port = mcp_port
        self.mcp_http_path = mcp_http_path

    def copy(self):
        return McpRuntimeConfig(
            allow_source_read=self.allow_source_read,
            allow_source_write=self.allow_source_write,
            allow_eval_arbitrary=self.allow_eval_arbitrary,
            allow_test_execution=self.allow_test_execution,
            allow_ide_read=self.allow_ide_read,
            allow_ide_write=self.allow_ide_write,
            allow_commit=self.allow_commit,
            allow_tracing=self.allow_tracing,
            require_gemstone_ast=self.require_gemstone_ast,
            mcp_host=self.mcp_host,
            mcp_port=self.mcp_port,
            mcp_http_path=self.mcp_http_path,
        )

    @classmethod
    def from_dict(cls, config_payload):
        return cls(
            allow_source_read=bool(config_payload.get("allow_source_read", True)),
            allow_source_write=bool(config_payload.get("allow_source_write", False)),
            allow_eval_arbitrary=bool(
                config_payload.get("allow_eval_arbitrary", False)
            ),
            allow_test_execution=bool(
                config_payload.get("allow_test_execution", False)
            ),
            allow_ide_read=bool(config_payload.get("allow_ide_read", True)),
            allow_ide_write=bool(config_payload.get("allow_ide_write", False)),
            allow_commit=bool(config_payload.get("allow_commit", False)),
            allow_tracing=bool(config_payload.get("allow_tracing", False)),
            require_gemstone_ast=bool(
                config_payload.get("require_gemstone_ast", False)
            ),
            mcp_host=str(config_payload.get("mcp_host", "127.0.0.1")).strip(),
            mcp_port=int(config_payload.get("mcp_port", 8000)),
            mcp_http_path=str(config_payload.get("mcp_http_path", "/mcp")).strip(),
        )

    def to_dict(self):
        return {
            "allow_source_read": bool(self.allow_source_read),
            "allow_source_write": bool(self.allow_source_write),
            "allow_eval_arbitrary": bool(self.allow_eval_arbitrary),
            "allow_test_execution": bool(self.allow_test_execution),
            "allow_ide_read": bool(self.allow_ide_read),
            "allow_ide_write": bool(self.allow_ide_write),
            "allow_commit": bool(self.allow_commit),
            "allow_tracing": bool(self.allow_tracing),
            "require_gemstone_ast": bool(self.require_gemstone_ast),
            "mcp_host": self.mcp_host,
            "mcp_port": self.mcp_port,
            "mcp_http_path": self.mcp_http_path,
        }

    def __eq__(self, other):
        if not isinstance(other, McpRuntimeConfig):
            return False
        return self.to_dict() == other.to_dict()

    def endpoint_url(self):
        return "http://%s:%s%s" % (
            self.mcp_host,
            self.mcp_port,
            self.mcp_http_path,
        )

    def update_with(
        self,
        allow_source_read=None,
        allow_source_write=None,
        allow_eval_arbitrary=None,
        allow_test_execution=None,
        allow_ide_read=None,
        allow_ide_write=None,
        allow_commit=None,
        allow_tracing=None,
        require_gemstone_ast=None,
        mcp_host=None,
        mcp_port=None,
        mcp_http_path=None,
    ):
        if allow_source_read is not None:
            self.allow_source_read = bool(allow_source_read)
        if allow_source_write is not None:
            self.allow_source_write = bool(allow_source_write)
        if allow_eval_arbitrary is not None:
            self.allow_eval_arbitrary = bool(allow_eval_arbitrary)
        if allow_test_execution is not None:
            self.allow_test_execution = bool(allow_test_execution)
        if allow_ide_read is not None:
            self.allow_ide_read = bool(allow_ide_read)
        if allow_ide_write is not None:
            self.allow_ide_write = bool(allow_ide_write)
        if allow_commit is not None:
            self.allow_commit = bool(allow_commit)
        if allow_tracing is not None:
            self.allow_tracing = bool(allow_tracing)
        if require_gemstone_ast is not None:
            self.require_gemstone_ast = bool(require_gemstone_ast)
        if mcp_host is not None:
            self.mcp_host = mcp_host
        if mcp_port is not None:
            self.mcp_port = mcp_port
        if mcp_http_path is not None:
            self.mcp_http_path = mcp_http_path


class McpServerController:
    def __init__(
        self,
        integrated_session_state,
        runtime_config,
        configuration_store=None,
    ):
        self.integrated_session_state = integrated_session_state
        if configuration_store is None:
            configuration_store = McpConfigurationStore()
        self.configuration_store = configuration_store
        self.runtime_config = runtime_config.copy()
        self.applied_runtime_config = None
        self.lock = threading.RLock()
        self.server_thread = None
        self.uvicorn_server = None
        self.last_error_message = ""
        self.starting = False
        self.stopping = False
        self.running = False
        self.shutdown_requested = False
        self.server_state_subscribers = []

    def current_runtime_config(self):
        with self.lock:
            return self.runtime_config.copy()

    def update_runtime_config(self, runtime_config):
        with self.lock:
            self.runtime_config = runtime_config.copy()

    def save_configuration(self):
        self.configuration_store.save(self.current_runtime_config())

    def status(self):
        with self.lock:
            configured_endpoint_url = self.runtime_config.endpoint_url()
            active_endpoint_url = configured_endpoint_url
            if self.applied_runtime_config is not None:
                active_endpoint_url = self.applied_runtime_config.endpoint_url()
            restart_required_for_config = False
            if self.running and self.applied_runtime_config is not None:
                restart_required_for_config = (
                    self.runtime_config != self.applied_runtime_config
                )
            return {
                "running": self.running,
                "starting": self.starting,
                "stopping": self.stopping,
                "last_error_message": self.last_error_message,
                "endpoint_url": active_endpoint_url,
                "configured_endpoint_url": configured_endpoint_url,
                "restart_required_for_config": restart_required_for_config,
            }

    def callback_reference_for(self, callback):
        try:
            return weakref.WeakMethod(callback)
        except TypeError:
            return weakref.ref(callback)

    def subscribe_server_state(self, callback):
        with self.lock:
            self.server_state_subscribers.append(self.callback_reference_for(callback))

    def live_callbacks_from_references(self, callback_references):
        callbacks = []
        live_callback_references = []
        for callback_reference in callback_references:
            callback = callback_reference()
            if callback is None:
                continue
            callbacks.append(callback)
            live_callback_references.append(callback_reference)
        return callbacks, live_callback_references

    def notify_server_state_subscribers(self):
        callbacks = []
        status_payload = self.status()
        with self.lock:
            callbacks, live_callback_references = self.live_callbacks_from_references(
                self.server_state_subscribers
            )
            self.server_state_subscribers = live_callback_references
        for callback in callbacks:
            callback(
                running=status_payload["running"],
                starting=status_payload["starting"],
                stopping=status_payload["stopping"],
                endpoint_url=status_payload["endpoint_url"],
                last_error_message=status_payload["last_error_message"],
            )

    def clear_subscribers(self, owner):
        with self.lock:
            self.server_state_subscribers = self.cleaned_subscribers_for_owner(
                self.server_state_subscribers,
                owner,
            )

    def cleaned_subscribers_for_owner(self, callback_references, owner):
        cleaned_callback_references = []
        for callback_reference in callback_references:
            callback = callback_reference()
            if callback is None:
                continue
            callback_owner = getattr(callback, "__self__", None)
            if callback_owner is owner:
                continue
            cleaned_callback_references.append(callback_reference)
        return cleaned_callback_references

    def start(self):
        with self.lock:
            if self.running or self.starting:
                return False
            self.starting = True
            self.stopping = False
            self.shutdown_requested = False
            self.last_error_message = ""
            self.server_thread = threading.Thread(
                target=self.run_server,
                daemon=True,
                name="SwordfishMCP",
            )
            self.server_thread.start()
        self.notify_server_state_subscribers()
        return True

    def stop(self):
        server_thread = None
        with self.lock:
            server = self.uvicorn_server
            if server is None and not self.running and not self.starting:
                return False
            self.starting = False
            self.stopping = True
            self.shutdown_requested = True
            server_thread = self.server_thread
            if server is not None:
                server.should_exit = True
        self.notify_server_state_subscribers()
        if (
            server_thread is not None
            and server_thread.is_alive()
            and threading.current_thread() is not server_thread
        ):
            wait_thread = threading.Thread(
                target=self.wait_for_server_thread_exit,
                args=(server_thread,),
                daemon=True,
                name="SwordfishMCPStopWait",
            )
            wait_thread.start()
        return True

    def wait_for_server_thread_exit(self, server_thread):
        server_thread.join(timeout=5)

    def server_for_runtime_config(self, runtime_config):
        return create_server(
            allow_source_read=runtime_config.allow_source_read,
            allow_source_write=runtime_config.allow_source_write,
            allow_eval_arbitrary=runtime_config.allow_eval_arbitrary,
            allow_test_execution=runtime_config.allow_test_execution,
            allow_ide_read=runtime_config.allow_ide_read,
            allow_ide_write=runtime_config.allow_ide_write,
            allow_commit=runtime_config.allow_commit,
            allow_tracing=runtime_config.allow_tracing,
            integrated_session_state=self.integrated_session_state,
            require_gemstone_ast=runtime_config.require_gemstone_ast,
            mcp_host=runtime_config.mcp_host,
            mcp_port=runtime_config.mcp_port,
            mcp_streamable_http_path=runtime_config.mcp_http_path,
        )

    def run(self, transport):
        local_runtime_config = self.current_runtime_config()
        mcp_server = self.server_for_runtime_config(local_runtime_config)
        mcp_server.run(transport=transport)

    def run_server(self):
        local_runtime_config = self.current_runtime_config()
        with self.lock:
            if self.shutdown_requested:
                self.starting = False
                self.stopping = False
                self.server_thread = None
                self.notify_server_state_subscribers()
                return
        try:
            mcp_server = self.server_for_runtime_config(local_runtime_config)
            import uvicorn

            streamable_http_application = mcp_server.streamable_http_app()
            uvicorn_config = uvicorn.Config(
                streamable_http_application,
                host=local_runtime_config.mcp_host,
                port=local_runtime_config.mcp_port,
                log_level=mcp_server.settings.log_level.lower(),
            )
            server = uvicorn.Server(uvicorn_config)
            with self.lock:
                self.uvicorn_server = server
                self.applied_runtime_config = local_runtime_config.copy()
                self.running = True
                self.starting = False
                self.last_error_message = ""
                if self.shutdown_requested:
                    server.should_exit = True
            self.notify_server_state_subscribers()
            asyncio.run(server.serve())
        except (
            McpDependencyNotInstalled,
            ImportError,
            ModuleNotFoundError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            with self.lock:
                self.last_error_message = str(error)
            self.notify_server_state_subscribers()
        finally:
            with self.lock:
                self.running = False
                self.starting = False
                self.stopping = False
                self.uvicorn_server = None
                self.server_thread = None
                self.applied_runtime_config = None
            self.notify_server_state_subscribers()


class McpConfigurationDialog(tk.Toplevel):
    def __init__(self, parent, current_runtime_config):
        super().__init__(parent)
        self.parent = parent
        self.current_runtime_config = current_runtime_config.copy()
        self.result = None
        self.title("MCP Configuration")
        self.geometry("500x560")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.host_variable = tk.StringVar(value=self.current_runtime_config.mcp_host)
        self.port_variable = tk.StringVar(
            value=str(self.current_runtime_config.mcp_port)
        )
        self.path_variable = tk.StringVar(
            value=self.current_runtime_config.mcp_http_path
        )
        self.allow_source_read_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_source_read
        )
        self.allow_source_write_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_source_write
        )
        self.allow_eval_arbitrary_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_eval_arbitrary
        )
        self.allow_test_execution_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_test_execution
        )
        self.allow_ide_read_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_ide_read
        )
        self.allow_ide_write_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_ide_write
        )
        self.allow_commit_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_commit
        )
        self.allow_tracing_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_tracing
        )
        self.require_gemstone_ast_variable = tk.BooleanVar(
            value=self.current_runtime_config.require_gemstone_ast
        )
        self.risk_note_variable = tk.StringVar()

        self.create_widgets()
        for var in (
            self.allow_source_write_variable,
            self.allow_eval_arbitrary_variable,
            self.allow_test_execution_variable,
            self.allow_commit_variable,
        ):
            var.trace_add('write', self.update_risk_note)
        self.update_risk_note()

    def create_widgets(self):
        body_frame = ttk.Frame(self, padding=12)
        body_frame.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        ttk.Label(body_frame, text="Host").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.host_variable).grid(
            row=1, column=0, sticky="ew", pady=(0, 10)
        )

        ttk.Label(body_frame, text="Port").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.port_variable).grid(
            row=3, column=0, sticky="ew", pady=(0, 10)
        )

        ttk.Label(body_frame, text="HTTP Path").grid(
            row=4, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.path_variable).grid(
            row=5, column=0, sticky="ew", pady=(0, 12)
        )

        ttk.Checkbutton(
            body_frame,
            text="Allow source read tools",
            variable=self.allow_source_read_variable,
        ).grid(row=6, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Allow source write/refactor tools",
            variable=self.allow_source_write_variable,
        ).grid(row=7, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Allow arbitrary eval tools",
            variable=self.allow_eval_arbitrary_variable,
        ).grid(row=8, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Allow test execution tools",
            variable=self.allow_test_execution_variable,
        ).grid(row=9, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Allow IDE state read tools",
            variable=self.allow_ide_read_variable,
        ).grid(row=10, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Allow IDE state write tools",
            variable=self.allow_ide_write_variable,
        ).grid(row=11, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Enable commit tool",
            variable=self.allow_commit_variable,
        ).grid(row=12, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Enable tracing tools",
            variable=self.allow_tracing_variable,
        ).grid(row=13, column=0, sticky="w")
        ttk.Checkbutton(
            body_frame,
            text="Require GemStone AST backend",
            variable=self.require_gemstone_ast_variable,
        ).grid(row=14, column=0, sticky="w")

        self.risk_note_label = ttk.Label(
            body_frame,
            textvariable=self.risk_note_variable,
            wraplength=440,
            justify="left",
        )
        self.risk_note_label.grid(row=15, column=0, sticky="w", pady=(12, 0))

        button_frame = ttk.Frame(body_frame)
        button_frame.grid(row=16, column=0, sticky="e", pady=(16, 0))
        ttk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_dialog,
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            button_frame,
            text="Apply",
            command=self.apply_configuration,
        ).grid(row=0, column=1)
        body_frame.columnconfigure(0, weight=1)

    def compute_risk_note(self):
        source_write = self.allow_source_write_variable.get()
        eval_arbitrary = self.allow_eval_arbitrary_variable.get()
        test_execution = self.allow_test_execution_variable.get()
        commit = self.allow_commit_variable.get()
        lines = []
        if source_write and eval_arbitrary and commit:
            lines.append(
                'Code: AI can write, compile, execute, and permanently install code changes.'
            )
        elif source_write and eval_arbitrary:
            lines.append('Code: AI can write, compile, and execute Smalltalk code freely.')
        elif eval_arbitrary:
            lines.append('Code: AI can execute arbitrary Smalltalk code.')
        elif source_write and commit:
            lines.append('Code: AI can compile and permanently install method changes.')
        elif source_write:
            lines.append('Code: AI can compile method changes (lost on abort without commit).')
        if eval_arbitrary and commit:
            lines.append('Data: AI can read and permanently modify client data.')
        elif eval_arbitrary:
            lines.append('Data: AI can read and modify client data in memory.')
        elif source_write and test_execution and commit:
            lines.append(
                'Data: AI can read and permanently modify client data'
                ' by writing and running a custom test.'
            )
        elif source_write and test_execution:
            lines.append(
                'Data: AI can read and modify client data in memory'
                ' by writing and running a custom test.'
            )
        elif test_execution and commit:
            lines.append(
                'Data: Existing tests may expose or permanently modify client data they touch.'
            )
        elif test_execution:
            lines.append(
                'Data: Existing tests may expose or modify client data they happen to touch.'
            )
        if lines:
            return '\n'.join(lines)
        return '\u2713 Read-only code access \u2014 client data is not reachable.'

    def update_risk_note(self, *_):
        note = self.compute_risk_note()
        self.risk_note_variable.set(note)
        is_safe = note.startswith('\u2713')
        self.risk_note_label.configure(foreground='#006600' if is_safe else '#AA4400')

    def apply_configuration(self):
        port_text = self.port_variable.get().strip()
        if not port_text:
            messagebox.showerror("Invalid MCP configuration", "Port cannot be empty.")
            return
        if not port_text.isdigit():
            messagebox.showerror(
                "Invalid MCP configuration",
                "Port must be a positive integer.",
            )
            return
        mcp_port = int(port_text)
        if mcp_port <= 0:
            messagebox.showerror(
                "Invalid MCP configuration",
                "Port must be greater than zero.",
            )
            return
        mcp_host = self.host_variable.get().strip()
        if not mcp_host:
            messagebox.showerror(
                "Invalid MCP configuration",
                "Host cannot be empty.",
            )
            return
        mcp_http_path = self.path_variable.get().strip()
        if not mcp_http_path.startswith("/"):
            messagebox.showerror(
                "Invalid MCP configuration",
                "HTTP path must start with /.",
            )
            return
        self.result = McpRuntimeConfig(
            allow_source_read=self.allow_source_read_variable.get(),
            allow_source_write=self.allow_source_write_variable.get(),
            allow_eval_arbitrary=self.allow_eval_arbitrary_variable.get(),
            allow_test_execution=self.allow_test_execution_variable.get(),
            allow_ide_read=self.allow_ide_read_variable.get(),
            allow_ide_write=self.allow_ide_write_variable.get(),
            allow_commit=self.allow_commit_variable.get(),
            allow_tracing=self.allow_tracing_variable.get(),
            require_gemstone_ast=self.require_gemstone_ast_variable.get(),
            mcp_host=mcp_host,
            mcp_port=mcp_port,
            mcp_http_path=mcp_http_path,
        )
        self.destroy()

    def cancel_dialog(self):
        self.result = None
        self.destroy()


class MainMenu(tk.Menu):
    def __init__(self, parent, event_queue, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.event_queue = event_queue
        self.file_menu = tk.Menu(self, tearoff=0)
        self.session_menu = tk.Menu(self, tearoff=0)
        self.mcp_menu = tk.Menu(self, tearoff=0)

        self._create_menus()
        self._subscribe_events()

    def _create_menus(self):
        # File Menu
        self.add_cascade(label="File", menu=self.file_menu)
        self.update_file_menu()

        # Session Menu
        self.add_cascade(label="Session", menu=self.session_menu)
        self.update_session_menu()
        self.add_cascade(label="MCP", menu=self.mcp_menu)
        self.update_mcp_menu()

    def _subscribe_events(self):
        self.event_queue.subscribe("LoggedInSuccessfully", self.update_menus)
        self.event_queue.subscribe("LoggedOut", self.update_menus)
        self.event_queue.subscribe("McpBusyStateChanged", self.update_menus)
        self.event_queue.subscribe("McpServerStateChanged", self.update_menus)

    def update_menus(self, gemstone_session_record=None, **kwargs):
        self.update_session_menu()
        self.update_file_menu()
        self.update_mcp_menu()

    def update_session_menu(self):
        self.session_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            is_busy = self.parent.integrated_session_state.is_mcp_busy()
            menu_state = self.parent.action_gate.state_for('session', is_busy=is_busy)
            self.session_menu.add_command(
                label="Commit",
                command=self.parent.commit,
                state=menu_state,
            )
            self.session_menu.add_command(
                label="Abort",
                command=self.parent.abort,
                state=menu_state,
            )
            self.session_menu.add_command(
                label="Logout",
                command=self.parent.logout,
                state=menu_state,
            )
        else:
            self.session_menu.add_command(
                label="Login", command=self.parent.show_login_screen
            )

    def update_mcp_menu(self):
        self.mcp_menu.delete(0, tk.END)
        mcp_state = self.parent.embedded_mcp_server_status()
        start_state = tk.NORMAL
        if mcp_state["running"] or mcp_state["starting"] or mcp_state["stopping"]:
            start_state = tk.DISABLED
        stop_state = tk.NORMAL
        if (
            not mcp_state["running"]
            and not mcp_state["starting"]
            and not mcp_state["stopping"]
        ):
            stop_state = tk.DISABLED
        if mcp_state["stopping"]:
            stop_state = tk.DISABLED
        is_busy = self.parent.integrated_session_state.is_mcp_busy()
        if not self.parent.action_gate.allows('mcp_stop', is_busy=is_busy):
            stop_state = tk.DISABLED
        configure_state = tk.NORMAL
        if mcp_state["starting"] or mcp_state["stopping"]:
            configure_state = tk.DISABLED
        self.mcp_menu.add_command(
            label="Start MCP",
            command=self.start_mcp_server,
            state=start_state,
        )
        self.mcp_menu.add_command(
            label="Stop MCP",
            command=self.stop_mcp_server,
            state=stop_state,
        )
        self.mcp_menu.add_separator()
        self.mcp_menu.add_command(
            label="Configure MCP",
            command=self.configure_mcp_server,
            state=configure_state,
        )

    def update_file_menu(self):
        self.file_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            is_busy = self.parent.integrated_session_state.is_mcp_busy()
            run_command_state = self.parent.action_gate.state_for('run', is_busy=is_busy)
            breakpoints_state = self.parent.action_gate.state_for(
                'breakpoints',
                is_busy=is_busy,
            )
            self.file_menu.add_command(label="Find", command=self.show_find_dialog)
            self.file_menu.add_command(
                label="Implementors",
                command=self.show_find_implementors_dialog,
            )
            self.file_menu.add_command(
                label="Senders",
                command=self.show_find_senders_dialog,
            )
            self.file_menu.add_command(
                label="Run",
                command=self.show_run_dialog,
                state=run_command_state,
            )
            self.file_menu.add_command(
                label="Breakpoints",
                command=self.show_breakpoints_dialog,
                state=breakpoints_state,
            )
            self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

    def show_find_dialog(self):
        self.parent.open_find_dialog()

    def show_find_implementors_dialog(self):
        self.parent.open_implementors_dialog()

    def show_find_senders_dialog(self):
        self.parent.open_senders_dialog()

    def show_run_dialog(self):
        self.parent.open_run_tab()

    def show_breakpoints_dialog(self):
        self.parent.open_breakpoints_dialog()

    def start_mcp_server(self):
        self.parent.start_mcp_server_from_menu()

    def stop_mcp_server(self):
        self.parent.stop_mcp_server_from_menu()

    def configure_mcp_server(self):
        self.parent.configure_mcp_server_from_menu()


class FindDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        search_type="class",
        search_query="",
        run_search=False,
        match_mode=None,
        reference_target=None,
        sender_source_class_name=None,
    ):
        super().__init__(parent)
        self.title("Find")
        self.geometry("720x560")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent
        self.sender_source_class_name = sender_source_class_name
        self.method_reference_results = []
        self.navigation_method_results = []
        self.reference_method_selectors = []
        self.sender_tracing_selector = None
        self.static_sender_results = []
        self.sender_entries_by_navigation_result = {}
        self.last_reference_method_query = None
        self.last_reference_method_match_mode = None
        self.max_test_discovery_elapsed_ms = 120000
        self.status_var = tk.StringVar(value="")
        self.search_intent_var = tk.StringVar(value="")
        self.result_action_var = tk.StringVar(value="")
        self.find_operation_running = False
        self.find_stop_requested = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(7, weight=1)

        self.search_type = tk.StringVar(value="class")
        self.match_mode = tk.StringVar(value="contains")
        self.reference_target = tk.StringVar(value="class")
        ttk.Label(self, text="Search Type:").grid(
            row=0,
            column=0,
            padx=10,
            pady=5,
            sticky="w",
        )
        self.search_type_frame = ttk.Frame(self)
        self.search_type_frame.grid(
            row=0,
            column=1,
            columnspan=5,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.class_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="Class",
            variable=self.search_type,
            value="class",
        )
        self.class_radio.pack(side="left", padx=(0, 8))
        self.method_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="Method",
            variable=self.search_type,
            value="method",
        )
        self.method_radio.pack(side="left", padx=(0, 8))
        self.reference_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="References",
            variable=self.search_type,
            value="reference",
        )
        self.reference_radio.pack(side="left", padx=(0, 8))

        ttk.Label(self, text="Match:").grid(
            row=1,
            column=0,
            padx=10,
            pady=5,
            sticky="w",
        )
        self.match_mode_frame = ttk.Frame(self)
        self.match_mode_frame.grid(
            row=1,
            column=1,
            columnspan=2,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.match_contains_radio = ttk.Radiobutton(
            self.match_mode_frame,
            text="Contains",
            variable=self.match_mode,
            value="contains",
        )
        self.match_contains_radio.pack(side="left", padx=(0, 8))
        self.match_exact_radio = ttk.Radiobutton(
            self.match_mode_frame,
            text="Exact",
            variable=self.match_mode,
            value="exact",
        )
        self.match_exact_radio.pack(side="left")

        self.reference_target_label = ttk.Label(
            self,
            text="Reference target:",
        )
        self.reference_target_label.grid(
            row=1,
            column=3,
            padx=(10, 6),
            pady=5,
            sticky="e",
        )
        self.reference_target_frame = ttk.Frame(self)
        self.reference_target_frame.grid(
            row=1,
            column=4,
            columnspan=2,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.reference_target_class_radio = ttk.Radiobutton(
            self.reference_target_frame,
            text="Class",
            variable=self.reference_target,
            value="class",
        )
        self.reference_target_class_radio.pack(side="left", padx=(0, 8))
        self.reference_target_method_radio = ttk.Radiobutton(
            self.reference_target_frame,
            text="Method",
            variable=self.reference_target,
            value="method",
        )
        self.reference_target_method_radio.pack(side="left")

        ttk.Label(self, text="Find what:").grid(
            row=2,
            column=0,
            padx=10,
            pady=10,
            sticky="w",
        )
        self.find_entry = ttk.Entry(self)
        self.find_entry.grid(
            row=2,
            column=1,
            columnspan=5,
            padx=10,
            pady=10,
            sticky="ew",
        )
        self.find_entry.bind(
            "<KeyRelease>",
            lambda *_: self.update_search_context_fields(),
        )

        ttk.Label(self, text="Search intent:").grid(
            row=3,
            column=0,
            padx=10,
            pady=(0, 2),
            sticky="w",
        )
        self.search_intent_label = ttk.Label(
            self,
            textvariable=self.search_intent_var,
            anchor="w",
        )
        self.search_intent_label.grid(
            row=3,
            column=1,
            columnspan=5,
            padx=10,
            pady=(0, 2),
            sticky="ew",
        )

        ttk.Label(self, text="Result action:").grid(
            row=4,
            column=0,
            padx=10,
            pady=(0, 2),
            sticky="w",
        )
        self.result_action_label = ttk.Label(
            self,
            textvariable=self.result_action_var,
            anchor="w",
        )
        self.result_action_label.grid(
            row=4,
            column=1,
            columnspan=5,
            padx=10,
            pady=(0, 2),
            sticky="ew",
        )

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=5, column=0, columnspan=6, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)
        self.button_frame.grid_columnconfigure(2, weight=1)
        self.button_frame.grid_columnconfigure(3, weight=1)
        self.button_frame.grid_columnconfigure(4, weight=1)

        self.find_button = ttk.Button(
            self.button_frame,
            text="Find",
            command=self.find_text,
        )
        self.find_button.grid(row=0, column=0, padx=5)

        self.stop_button = ttk.Button(
            self.button_frame,
            text="Stop",
            command=self.request_stop_find,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=1, padx=5)

        self.narrow_button = ttk.Button(
            self.button_frame,
            text="Narrow With Tracing",
            command=self.narrow_senders_with_tracing,
        )
        self.narrow_button.grid(row=0, column=2, padx=5)

        self.narrow_to_source_class_button = ttk.Button(
            self.button_frame,
            text="Narrow to Source Class",
            command=self.narrow_to_source_class_button_clicked,
        )
        self.narrow_to_source_class_button.grid(row=0, column=3, padx=5)

        self.cancel_button = ttk.Button(
            self.button_frame,
            text="Cancel",
            command=self.destroy,
        )
        self.cancel_button.grid(row=0, column=4, padx=5)

        self.filter_frame = ttk.Frame(self)
        self.filter_frame.grid(
            row=6,
            column=0,
            columnspan=6,
            padx=10,
            pady=(0, 4),
            sticky="ew",
        )
        ttk.Label(self.filter_frame, text="Filter by class (regex):").pack(
            side="left", padx=(0, 4)
        )
        self.class_regex_entry = ttk.Entry(self.filter_frame, width=20)
        self.class_regex_entry.pack(side="left", padx=(0, 12))
        ttk.Label(self.filter_frame, text="Filter by category (regex):").pack(
            side="left", padx=(0, 4)
        )
        self.category_regex_entry = ttk.Entry(self.filter_frame, width=20)
        self.category_regex_entry.pack(side="left", padx=(0, 12))
        self.apply_regex_filter_button = ttk.Button(
            self.filter_frame,
            text="Apply Filter",
            command=self.apply_regex_filter_button_clicked,
        )
        self.apply_regex_filter_button.pack(side="left")

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.grid(
            row=7,
            column=0,
            columnspan=6,
            padx=10,
            pady=(10, 4),
            sticky="nsew",
        )
        self.results_listbox.bind("<Double-Button-1>", self.on_result_double_click)

        self.status_label = ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
        )
        self.status_label.grid(
            row=8,
            column=0,
            columnspan=6,
            padx=10,
            pady=(0, 10),
            sticky="ew",
        )

        configuration = self.resolved_search_configuration(
            search_type,
            match_mode,
            reference_target,
        )
        self.search_type.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.match_mode.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.reference_target.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.search_type.set(configuration["search_type"])
        self.match_mode.set(configuration["match_mode"])
        self.reference_target.set(configuration["reference_target"])
        if search_query:
            self.find_entry.delete(0, tk.END)
            self.find_entry.insert(0, search_query)
        self.update_mode_controls()
        self.set_find_operation_state(False)
        self.update_search_context_fields()
        if run_search:
            self.find_text()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def resolved_search_configuration(
        self,
        search_type,
        match_mode,
        reference_target,
    ):
        configuration = {
            "search_type": "class",
            "match_mode": "contains",
            "reference_target": "class",
        }
        if search_type in ["class", "method", "reference"]:
            configuration["search_type"] = search_type
        if search_type == "class_reference":
            configuration["search_type"] = "reference"
            configuration["reference_target"] = "class"
            configuration["match_mode"] = "exact"
        if search_type == "implementor":
            configuration["search_type"] = "method"
            configuration["match_mode"] = "exact"
        if search_type == "sender":
            configuration["search_type"] = "reference"
            configuration["reference_target"] = "method"
            configuration["match_mode"] = "exact"
        if match_mode in ["exact", "contains"]:
            configuration["match_mode"] = match_mode
        if reference_target in ["class", "method"]:
            configuration["reference_target"] = reference_target
        if configuration["search_type"] == "reference":
            configuration["match_mode"] = "exact"
        return configuration

    def update_mode_controls(self):
        search_type = self.search_type.get()
        reference_mode_is_selected = search_type == "reference"
        if reference_mode_is_selected and self.match_mode.get() != "exact":
            self.match_mode.set("exact")
            return
        reference_target_is_method = self.reference_target.get() == "method"
        tracing_controls_visible = (
            reference_mode_is_selected and reference_target_is_method
        )
        contains_match_state = tk.NORMAL
        exact_match_state = tk.NORMAL
        if reference_mode_is_selected:
            contains_match_state = tk.DISABLED
        if self.find_operation_running:
            contains_match_state = tk.DISABLED
            exact_match_state = tk.DISABLED
        self.match_contains_radio.config(state=contains_match_state)
        self.match_exact_radio.config(state=exact_match_state)
        if reference_mode_is_selected:
            self.reference_target_label.grid()
            self.reference_target_frame.grid()
        else:
            self.reference_target_label.grid_remove()
            self.reference_target_frame.grid_remove()
        if tracing_controls_visible:
            self.narrow_button.grid()
            self.narrow_to_source_class_button.grid()
            self.filter_frame.grid()
            self.status_label.grid()
        else:
            self.narrow_button.grid_remove()
            self.narrow_to_source_class_button.grid_remove()
            self.filter_frame.grid_remove()
            self.status_label.grid_remove()
            self.status_var.set("")
        self.update_trace_narrow_state()
        self.update_search_context_fields()

    def update_trace_narrow_state(self):
        source_class_known = self.sender_source_class_name is not None
        can_trace = bool(self.sender_tracing_selector) and source_class_known
        can_narrow_to_source = source_class_known
        if self.search_type.get() != "reference":
            can_trace = False
            can_narrow_to_source = False
        if self.reference_target.get() != "method":
            can_trace = False
            can_narrow_to_source = False
        if self.find_operation_running:
            can_trace = False
            can_narrow_to_source = False
        self.narrow_button.config(state=tk.NORMAL if can_trace else tk.DISABLED)
        self.narrow_to_source_class_button.config(
            state=tk.NORMAL if can_narrow_to_source else tk.DISABLED
        )

    def set_find_operation_state(self, is_running):
        self.find_operation_running = is_running
        self.find_button.config(state=tk.DISABLED if is_running else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if is_running else tk.DISABLED)
        self.cancel_button.config(state=tk.DISABLED if is_running else tk.NORMAL)
        mode_control_state = tk.DISABLED if is_running else tk.NORMAL
        self.find_entry.config(state=mode_control_state)
        self.class_radio.config(state=mode_control_state)
        self.method_radio.config(state=mode_control_state)
        self.reference_radio.config(state=mode_control_state)
        contains_match_state = mode_control_state
        if not is_running and self.search_type.get() == "reference":
            contains_match_state = tk.DISABLED
        self.match_contains_radio.config(state=contains_match_state)
        self.match_exact_radio.config(state=mode_control_state)
        self.reference_target_class_radio.config(state=mode_control_state)
        self.reference_target_method_radio.config(state=mode_control_state)
        self.update_trace_narrow_state()
        self.update_search_context_fields()

    def request_stop_find(self):
        if self.find_operation_running:
            self.find_stop_requested = True
            self.status_var.set("Stopping find...")

    def find_should_stop(self):
        if not self.find_operation_running:
            return False
        self.update_idletasks()
        try:
            self.update()
        except tk.TclError:
            return True
        return self.find_stop_requested

    def finish_stopped_find(self):
        self.status_var.set("Find stopped. Showing partial results.")
        self.sender_tracing_selector = None

    def format_method_navigation_label(
        self,
        class_name,
        show_instance_side,
        method_selector,
    ):
        class_side_label = ""
        if not show_instance_side:
            class_side_label = " class"
        return "%s%s>>%s" % (
            class_name,
            class_side_label,
            method_selector,
        )

    def class_match_query_pattern(self, query_text, match_mode):
        escaped_query = re.escape(query_text)
        if match_mode == "exact":
            return "^%s$" % escaped_query
        return escaped_query

    def class_names_for_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        class_pattern = self.class_match_query_pattern(
            query_text,
            match_mode,
        )
        return list(
            self.gemstone_session_record.find_class_names_matching(
                class_pattern,
                should_stop=should_stop,
            )
        )

    def selector_names_for_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        if match_mode == "exact":
            return [query_text]
        return list(
            self.gemstone_session_record.find_selectors_matching(
                query_text,
                should_stop=should_stop,
            )
        )

    def references_for_class_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        class_names = [query_text]
        reference_results = []
        for class_name in class_names:
            if should_stop is not None and should_stop():
                return self.unique_sorted_navigation_results(reference_results)
            reference_results += list(
                self.gemstone_session_record.find_class_references(class_name)
            )
        return self.unique_sorted_navigation_results(reference_results)

    def references_for_method_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        selector_names = [query_text]
        sender_entries = []
        for selector_name in selector_names:
            if should_stop is not None and should_stop():
                (
                    sender_results,
                    sender_entries_by_result,
                ) = self.record_sender_entries_for_navigation(sender_entries)
                return (
                    sender_results,
                    selector_names,
                    sender_entries_by_result,
                )
            sender_entries += list(
                self.gemstone_session_record.sender_entries_for_method(
                    selector_name,
                    include_category_details=True,
                )
            )
        sender_results, sender_entries_by_result = (
            self.record_sender_entries_for_navigation(sender_entries)
        )
        return (
            sender_results,
            selector_names,
            sender_entries_by_result,
        )

    def unique_sorted_navigation_results(self, method_results):
        unique_result_by_key = {}
        for class_name, show_instance_side, method_selector in method_results:
            result_key = (
                class_name,
                show_instance_side,
                method_selector,
            )
            unique_result_by_key[result_key] = result_key
        return sorted(unique_result_by_key.values())

    def activity_message_for_search(
        self,
        search_type,
        match_mode,
        reference_target,
        search_query,
    ):
        if search_type == "class":
            if match_mode == "exact":
                return "Finding class %s..." % search_query
            return "Finding classes matching %s..." % search_query
        if search_type == "method":
            if match_mode == "exact":
                return "Finding implementors of %s..." % search_query
            return "Finding methods matching %s..." % search_query
        if reference_target == "class":
            return "Finding references to class %s..." % search_query
        return "Finding references to method %s..." % search_query

    def search_intent_text(
        self,
        search_type,
        match_mode,
        reference_target,
        normalized_search_query,
    ):
        if not normalized_search_query:
            return 'Enter text to search.'
        if search_type == 'class':
            if match_mode == 'exact':
                return 'Class exactly "%s".' % normalized_search_query
            return 'Classes containing "%s".' % normalized_search_query
        if search_type == 'method':
            if match_mode == 'exact':
                return 'Implementors of method "%s".' % normalized_search_query
            return 'Methods containing selector "%s".' % normalized_search_query
        if reference_target == 'class':
            return 'References to class "%s" (exact).' % normalized_search_query
        if self.sender_source_class_name is not None:
            return 'Senders of %s>>%s.' % (self.sender_source_class_name, normalized_search_query)
        return 'Senders of "%s" (all implementors).' % normalized_search_query

    def result_action_text(self, search_type, match_mode, reference_target):
        if self.find_operation_running:
            return "Search in progress. Click Stop to cancel."
        if search_type == "class":
            return "Double-click a class to navigate."
        if search_type == "method":
            if match_mode == "exact":
                return "Double-click an implementor to open the method."
            return "Double-click a selector to find implementors (exact)."
        if reference_target == "method":
            return "Double-click a reference to open the caller method."
        return "Double-click a reference to open the method."

    def update_search_context_fields(self):
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == "reference":
            match_mode = "exact"
        reference_target = self.reference_target.get()
        normalized_search_query = self.find_entry.get().strip()
        self.search_intent_var.set(
            self.search_intent_text(
                search_type,
                match_mode,
                reference_target,
                normalized_search_query,
            )
        )
        self.result_action_var.set(
            self.result_action_text(
                search_type,
                match_mode,
                reference_target,
            )
        )

    def display_results(self, results):
        self.results_listbox.delete(0, tk.END)
        for result in results:
            self.results_listbox.insert(tk.END, result)
        self.results_listbox.grid()

    def populate_navigation_results(self, method_results):
        self.navigation_method_results = list(method_results)
        self.display_results(
            [
                self.format_method_navigation_label(
                    class_name,
                    show_instance_side,
                    method_selector,
                )
                for class_name, show_instance_side, method_selector in (
                    self.navigation_method_results
                )
            ]
        )

    def record_sender_entries_for_navigation(self, sender_entries):
        sender_results = [
            (
                sender_entry['class_name'],
                sender_entry['show_instance_side'],
                sender_entry['method_selector'],
            )
            for sender_entry in sender_entries
        ]
        sender_entries_by_result = {}
        for sender_entry in sender_entries:
            sender_result = (
                sender_entry['class_name'],
                sender_entry['show_instance_side'],
                sender_entry['method_selector'],
            )
            sender_result_is_recorded = sender_result in sender_entries_by_result
            if not sender_result_is_recorded:
                sender_entries_by_result[sender_result] = dict(sender_entry)
        return (
            self.unique_sorted_navigation_results(sender_results),
            sender_entries_by_result,
        )

    def sender_entry_for_result(self, sender_result):
        sender_entry = self.sender_entries_by_navigation_result.get(sender_result)
        if sender_entry is not None:
            return dict(sender_entry)
        class_name, show_instance_side, method_selector = sender_result
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'method_selector': method_selector,
            'class_category': None,
            'method_category': None,
            'method_category_is_extension': False,
            'extension_category_name': None,
        }

    def sender_entries_for_navigation_results(self, sender_results):
        return [
            self.sender_entry_for_result(sender_result)
            for sender_result in sender_results
        ]

    def normalized_sender_filter_values(self, filter_values):
        if filter_values is None:
            return []
        return [
            value.strip().lower()
            for value in filter_values
            if isinstance(value, str) and value.strip()
        ]

    def sender_text_matches_filters(self, sender_text, filter_values):
        if not filter_values:
            return True
        if not isinstance(sender_text, str):
            return False
        normalized_sender_text = sender_text.strip().lower()
        if not normalized_sender_text:
            return False
        return any(
            filter_value in normalized_sender_text for filter_value in filter_values
        )

    def sender_matches_class_category_filters(
        self,
        sender_entry,
        class_category_filters,
        include_extension_method_category_for_class_category,
    ):
        if not class_category_filters:
            return True
        category_candidates = []
        class_category = sender_entry.get('class_category')
        if isinstance(class_category, str) and class_category.strip():
            category_candidates.append(class_category.strip().lower())
        if include_extension_method_category_for_class_category:
            extension_category_name = sender_entry.get('extension_category_name')
            if (
                isinstance(extension_category_name, str)
                and extension_category_name.strip()
            ):
                category_candidates.append(
                    extension_category_name.strip().lower()
                )
        if not category_candidates:
            return False
        return any(
            filter_value in category_candidate
            for filter_value in class_category_filters
            for category_candidate in category_candidates
        )

    def sender_entry_matches_filters(
        self,
        sender_entry,
        class_category_filters,
        class_name_filters,
        method_selector_filters,
        method_category_filters,
        include_extension_method_category_for_class_category,
    ):
        if not self.sender_matches_class_category_filters(
            sender_entry,
            class_category_filters,
            include_extension_method_category_for_class_category,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('class_name'),
            class_name_filters,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('method_selector'),
            method_selector_filters,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('method_category'),
            method_category_filters,
        ):
            return False
        return True

    def apply_sender_filters(
        self,
        class_category_filters=None,
        class_name_filters=None,
        method_selector_filters=None,
        method_category_filters=None,
        include_extension_method_category_for_class_category=True,
        reasoning_note='',
    ):
        if self.search_type.get() != 'reference' or self.reference_target.get() != 'method':
            return {
                'ok': False,
                'error': {
                    'message': (
                        'Sender filtering requires Find in method-reference mode.'
                    )
                },
            }
        normalized_class_category_filters = self.normalized_sender_filter_values(
            class_category_filters
        )
        normalized_class_name_filters = self.normalized_sender_filter_values(
            class_name_filters
        )
        normalized_method_selector_filters = self.normalized_sender_filter_values(
            method_selector_filters
        )
        normalized_method_category_filters = self.normalized_sender_filter_values(
            method_category_filters
        )
        baseline_sender_results = list(self.navigation_method_results)
        if not baseline_sender_results:
            baseline_sender_results = list(self.static_sender_results)
        filtered_sender_results = []
        for sender_result in baseline_sender_results:
            sender_entry = self.sender_entry_for_result(sender_result)
            sender_matches_filters = self.sender_entry_matches_filters(
                sender_entry,
                normalized_class_category_filters,
                normalized_class_name_filters,
                normalized_method_selector_filters,
                normalized_method_category_filters,
                include_extension_method_category_for_class_category,
            )
            if sender_matches_filters:
                filtered_sender_results.append(sender_result)
        self.populate_navigation_results(filtered_sender_results)
        displayed_sender_entries = self.sender_entries_for_navigation_results(
            filtered_sender_results
        )
        summary_text = 'Filtered senders: %s of %s displayed references.' % (
            len(filtered_sender_results),
            len(baseline_sender_results),
        )
        if reasoning_note:
            summary_text += ' ' + reasoning_note.strip()
        self.status_var.set(summary_text)
        return {
            'ok': True,
            'displayed_sender_count': len(filtered_sender_results),
            'filtered_out_sender_count': (
                len(baseline_sender_results) - len(filtered_sender_results)
            ),
            'displayed_senders': displayed_sender_entries,
            'reasoning_note': reasoning_note,
        }

    def sender_filter_state_for_mcp(self):
        is_sender_reference_search = (
            self.search_type.get() == 'reference'
            and self.reference_target.get() == 'method'
            and self.last_reference_method_query is not None
        )
        displayed_sender_entries = self.sender_entries_for_navigation_results(
            self.navigation_method_results
        )
        static_sender_entries = self.sender_entries_for_navigation_results(
            self.static_sender_results
        )
        return {
            'is_open': True,
            'is_sender_reference_search': is_sender_reference_search,
            'total_static_sender_count': len(self.static_sender_results),
            'displayed_sender_count': len(self.navigation_method_results),
            'displayed_senders': displayed_sender_entries,
            'static_senders': static_sender_entries,
            'sender_selector_query': self.last_reference_method_query,
            'sender_source_class_name': self.sender_source_class_name,
        }

    def source_class_category(self):
        if self.sender_source_class_name is None:
            return None
        for result in self.static_sender_results:
            entry = self.sender_entry_for_result(result)
            if entry.get('class_name') == self.sender_source_class_name:
                return entry.get('class_category')
        return None

    def narrow_to_source_class_category(self):
        if self.sender_source_class_name is None:
            return {
                'ok': False,
                'error': {'message': 'No source class context recorded for this sender search.'},
            }
        category = self.source_class_category()
        if category is None:
            return {
                'ok': False,
                'error': {
                    'message': 'Could not determine class category for %s from sender results.' % self.sender_source_class_name,
                },
            }
        return self.apply_sender_filters(
            class_category_filters=[category],
            reasoning_note='Narrowed to class category "%s" of source class %s.' % (
                category, self.sender_source_class_name,
            ),
        )

    def narrow_to_source_class_button_clicked(self):
        result = self.narrow_to_source_class_category()
        if not result.get('ok'):
            messagebox.showerror('Narrow to Source Class', result['error']['message'])

    def apply_regex_filter_button_clicked(self):
        result = self.apply_regex_sender_filters(
            class_regex=self.class_regex_entry.get(),
            category_regex=self.category_regex_entry.get(),
        )
        if not result.get('ok'):
            messagebox.showerror('Apply Filter', result['error']['message'])

    def apply_regex_sender_filters(self, class_regex='', category_regex=''):
        if self.search_type.get() != 'reference' or self.reference_target.get() != 'method':
            return {
                'ok': False,
                'error': {'message': 'Sender filtering requires Find in method-reference mode.'},
            }
        baseline_sender_results = list(self.navigation_method_results)
        if not baseline_sender_results:
            baseline_sender_results = list(self.static_sender_results)
        filtered_sender_results = []
        for sender_result in baseline_sender_results:
            sender_entry = self.sender_entry_for_result(sender_result)
            if not self.sender_entry_matches_regex_filters(sender_entry, class_regex, category_regex):
                continue
            filtered_sender_results.append(sender_result)
        self.populate_navigation_results(filtered_sender_results)
        parts = []
        if class_regex:
            parts.append('class~/%s/' % class_regex)
        if category_regex:
            parts.append('category~/%s/' % category_regex)
        filter_desc = ', '.join(parts) if parts else '(none)'
        self.status_var.set(
            'Filtered senders: %s of %s displayed. Filter: %s' % (
                len(filtered_sender_results),
                len(baseline_sender_results),
                filter_desc,
            )
        )
        return {
            'ok': True,
            'displayed_sender_count': len(filtered_sender_results),
            'filtered_out_sender_count': len(baseline_sender_results) - len(filtered_sender_results),
        }

    def sender_entry_matches_regex_filters(self, sender_entry, class_regex, category_regex):
        if class_regex:
            class_name = sender_entry.get('class_name') or ''
            try:
                if not re.search(class_regex, class_name, re.IGNORECASE):
                    return False
            except re.error:
                return False
        if category_regex:
            category = sender_entry.get('class_category') or sender_entry.get('method_category') or ''
            try:
                if not re.search(category_regex, category, re.IGNORECASE):
                    return False
            except re.error:
                return False
        return True

    def update_sender_status_for_method_references(
        self,
        selector_names,
        static_reference_count,
        match_mode,
    ):
        if self.search_type.get() != "reference":
            self.status_var.set("")
            return
        if self.reference_target.get() != "method":
            self.status_var.set("")
            return
        self.status_var.set("Static references: %s methods." % static_reference_count)

    def current_reference_method_selector_for_tracing(
        self,
        selector_names,
        normalized_search_query,
        match_mode,
    ):
        return normalized_search_query

    def find_text(self):
        if self.find_operation_running:
            return
        search_query = self.find_entry.get()
        normalized_search_query = search_query.strip()
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == 'reference':
            match_mode = 'exact'
            if self.match_mode.get() != 'exact':
                self.match_mode.set('exact')
        reference_target = self.reference_target.get()
        self.update_search_context_fields()
        self.navigation_method_results = []
        self.method_reference_results = []
        self.reference_method_selectors = []
        self.sender_tracing_selector = None
        self.sender_entries_by_navigation_result = {}
        should_run_search = bool(normalized_search_query)
        self.find_stop_requested = False
        self.set_find_operation_state(should_run_search)
        if should_run_search:
            self.parent.begin_foreground_activity(
                self.activity_message_for_search(
                    search_type,
                    match_mode,
                    reference_target,
                    normalized_search_query,
                )
            )

        try:
            if not should_run_search:
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                self.display_results([])
                self.status_var.set('')
                return
            if search_type == 'class':
                class_names = self.class_names_for_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.display_results(class_names)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            if search_type == 'method':
                if match_mode == 'exact':
                    implementor_results = list(
                        self.gemstone_session_record.find_implementors_of_method(
                            normalized_search_query
                        )
                    )
                    if self.find_should_stop():
                        self.display_results([])
                        self.finish_stopped_find()
                        return
                    self.navigation_method_results = [
                        (
                            class_name,
                            not is_meta,
                            normalized_search_query,
                        )
                        for class_name, is_meta in implementor_results
                    ]
                    self.static_sender_results = []
                    self.sender_entries_by_navigation_result = {}
                    self.populate_navigation_results(self.navigation_method_results)
                    if self.find_stop_requested:
                        self.finish_stopped_find()
                    else:
                        self.status_var.set('')
                    return
                selector_names = self.selector_names_for_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.display_results(selector_names)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            if reference_target == 'class':
                class_reference_results = self.references_for_class_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.method_reference_results = list(class_reference_results)
                self.populate_navigation_results(class_reference_results)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            (
                method_reference_results,
                selector_names,
                sender_entries_by_result,
            ) = self.references_for_method_query(
                normalized_search_query,
                match_mode,
                should_stop=self.find_should_stop,
            )
            self.reference_method_selectors = selector_names
            self.static_sender_results = list(method_reference_results)
            self.sender_entries_by_navigation_result = dict(sender_entries_by_result)
            self.last_reference_method_query = normalized_search_query
            self.last_reference_method_match_mode = match_mode
            if self.find_stop_requested:
                self.sender_tracing_selector = None
                self.populate_navigation_results(method_reference_results)
                self.finish_stopped_find()
                return
            self.sender_tracing_selector = (
                self.current_reference_method_selector_for_tracing(
                    selector_names,
                    normalized_search_query,
                    match_mode,
                )
            )
            self.populate_navigation_results(method_reference_results)
            self.update_sender_status_for_method_references(
                selector_names,
                len(self.static_sender_results),
                match_mode,
            )
        finally:
            if should_run_search:
                self.parent.end_foreground_activity()
            self.set_find_operation_state(False)
            self.update_search_context_fields()

    def choose_tests_for_tracing(self, method_name):
        test_selection_dialog = CoveringTestsSearchDialog(
            self,
            method_name,
            self.max_test_discovery_elapsed_ms,
        )
        discovery_workflow = CoveringTestsDiscoveryWorkflow(
            self.gemstone_session_record,
            method_name,
            self.max_test_discovery_elapsed_ms,
            self.merged_sender_test_plan,
        )

        def run_search_attempt():
            test_selection_dialog.set_searching_state()
            discovery_workflow.run_search_attempt()

        def monitor_search():
            if not test_selection_dialog.winfo_exists():
                return
            if test_selection_dialog.stop_search_requested:
                if not discovery_workflow.cancelled():
                    test_selection_dialog.set_stopping_for_cancel_state()
            if test_selection_dialog.use_results_requested:
                if discovery_workflow.searching():
                    test_selection_dialog.set_stopping_for_use_results_state()

            search_outcome = discovery_workflow.advance(
                test_selection_dialog.stop_search_requested,
                test_selection_dialog.use_results_requested,
                test_selection_dialog.add_or_update_candidate_test,
            )
            if search_outcome["phase"] == "searching":
                self.after(50, monitor_search)
                return
            if search_outcome["phase"] == "cancelled":
                test_selection_dialog.destroy()
                return
            if search_outcome["phase"] == "error":
                test_selection_dialog.destroy()
                return
            if search_outcome["phase"] == "empty":
                test_selection_dialog.set_ready_state(
                    timed_out=False,
                    summary_message="Search finished without results.",
                )
            if search_outcome["phase"] == "ready":
                accumulated_plan = search_outcome["plan"]
                test_selection_dialog.add_candidate_tests(
                    accumulated_plan.get("candidate_tests", [])
                )
                test_selection_dialog.set_metrics_from_test_plan(accumulated_plan)
                summary_message = ""
                if search_outcome["used_results"]:
                    summary_message = "Using the results found so far."
                if search_outcome["timed_out"]:
                    summary_message = (
                        "Search timed out. You can continue with Search Further."
                    )
                test_selection_dialog.set_ready_state(
                    timed_out=search_outcome["timed_out"],
                    summary_message=summary_message,
                )
            if test_selection_dialog.winfo_exists():
                if test_selection_dialog.search_further_requested:
                    test_selection_dialog.search_further_requested = False
                    run_search_attempt()
                self.after(50, monitor_search)

        run_search_attempt()
        self.after(50, monitor_search)
        self.wait_window(test_selection_dialog)

        if discovery_workflow.latest_error() is not None:
            raise discovery_workflow.latest_error()
        if discovery_workflow.cancelled():
            self.status_var.set("Test discovery stopped.")
            return None
        if test_selection_dialog.selected_tests is None:
            return None
        return test_selection_dialog.selected_tests

    def observed_sender_key(self, observed_sender):
        return (
            observed_sender["caller_class_name"],
            observed_sender["caller_show_instance_side"],
            observed_sender["caller_method_selector"],
        )

    def merge_sender_test_plans(self, current_plan, new_plan):
        return self.merged_sender_test_plan(
            current_plan,
            new_plan,
        )

    def merged_sender_test_plan(self, current_plan, new_plan):
        max_elapsed_ms = self.max_test_discovery_elapsed_ms

        def candidate_test_key(candidate_test):
            return (
                candidate_test["test_case_class_name"],
                candidate_test["test_method_selector"],
            )

        if current_plan is None:
            merged_plan = dict(new_plan)
            merged_plan["candidate_tests"] = list(new_plan.get("candidate_tests", []))
            merged_plan["sender_edges"] = list(new_plan.get("sender_edges", []))
            merged_plan["candidate_test_count"] = len(merged_plan["candidate_tests"])
            merged_plan["sender_edge_count"] = len(merged_plan["sender_edges"])
            return merged_plan

        merged_plan = dict(current_plan)
        candidate_tests_by_key = {}
        for candidate_test in current_plan.get("candidate_tests", []):
            candidate_tests_by_key[candidate_test_key(candidate_test)] = dict(
                candidate_test
            )
        for candidate_test in new_plan.get("candidate_tests", []):
            current_candidate_test_key = candidate_test_key(candidate_test)
            if current_candidate_test_key in candidate_tests_by_key:
                existing_candidate_test = candidate_tests_by_key[
                    current_candidate_test_key
                ]
                if candidate_test.get("depth", 0) < existing_candidate_test.get(
                    "depth",
                    0,
                ):
                    candidate_tests_by_key[current_candidate_test_key] = dict(
                        candidate_test
                    )
            if current_candidate_test_key not in candidate_tests_by_key:
                candidate_tests_by_key[current_candidate_test_key] = dict(
                    candidate_test
                )
        merged_candidate_tests = sorted(
            candidate_tests_by_key.values(),
            key=lambda candidate_test: (
                candidate_test.get("depth", 0),
                candidate_test["test_case_class_name"],
                candidate_test["test_method_selector"],
            ),
        )

        sender_edges_by_key = {}
        for sender_edge in current_plan.get("sender_edges", []) + new_plan.get(
            "sender_edges", []
        ):
            sender_edge_key = (
                sender_edge["from_selector"],
                sender_edge["to_class_name"],
                sender_edge["to_method_selector"],
                sender_edge["to_show_instance_side"],
                sender_edge["depth"],
            )
            sender_edges_by_key[sender_edge_key] = dict(sender_edge)
        merged_sender_edges = list(sender_edges_by_key.values())

        merged_plan["candidate_tests"] = merged_candidate_tests
        merged_plan["candidate_test_count"] = len(merged_candidate_tests)
        merged_plan["sender_edges"] = merged_sender_edges
        merged_plan["sender_edge_count"] = len(merged_sender_edges)
        merged_plan["visited_selector_count"] = max(
            current_plan.get("visited_selector_count", 0),
            new_plan.get("visited_selector_count", 0),
        )
        merged_plan["sender_search_truncated"] = current_plan.get(
            "sender_search_truncated", False
        ) or new_plan.get("sender_search_truncated", False)
        merged_plan["selector_limit_reached"] = current_plan.get(
            "selector_limit_reached", False
        ) or new_plan.get("selector_limit_reached", False)
        merged_plan["elapsed_limit_reached"] = new_plan.get(
            "elapsed_limit_reached",
            False,
        )
        merged_plan["elapsed_ms"] = current_plan.get("elapsed_ms", 0) + new_plan.get(
            "elapsed_ms",
            0,
        )
        merged_plan["max_elapsed_ms"] = max_elapsed_ms
        merged_plan["stopped_by_user"] = new_plan.get("stopped_by_user", False)
        return merged_plan

    def narrow_senders_with_tracing(self):
        if self.search_type.get() != "reference":
            return
        if self.reference_target.get() != "method":
            return
        reference_query = self.find_entry.get().strip()
        if not reference_query:
            messagebox.showwarning(
                "Narrow References",
                "Enter a method selector first.",
                parent=self,
            )
            return
        query_is_out_of_date = (
            self.last_reference_method_query != reference_query
            or self.last_reference_method_match_mode != self.match_mode.get()
        )
        if query_is_out_of_date:
            self.find_text()
        method_selector = self.sender_tracing_selector
        if not method_selector:
            messagebox.showwarning(
                "Narrow References",
                (
                    "Tracing requires an exact selector or a contains "
                    "query that matches one selector."
                ),
                parent=self,
            )
            return
        try:
            selected_tests = self.choose_tests_for_tracing(method_selector)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                "Narrow References",
                str(error),
                parent=self,
            )
            return
        if selected_tests is None:
            return
        source_class = self.sender_source_class_name
        trace_description = (
            '%s>>%s' % (source_class, method_selector)
            if source_class is not None
            else method_selector
        )
        self.status_var.set(
            "Tracing %s and running %s selected tests..."
            % (trace_description, len(selected_tests))
        )
        self.update_idletasks()
        try:
            evidence_result = (
                self.gemstone_session_record.collect_sender_evidence_from_tests(
                    method_selector,
                    selected_tests,
                    max_traced_senders=250,
                    max_observed_results=500,
                    receiver_class_name=source_class,
                )
            )
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                "Narrow References",
                str(error),
                parent=self,
            )
            self.status_var.set("")
            return
        observed_sender_entries = evidence_result["observed"]["observed_senders"]
        observed_sender_keys = {
            self.observed_sender_key(observed_sender)
            for observed_sender in observed_sender_entries
        }
        narrowed_sender_results = [
            sender_result
            for sender_result in self.static_sender_results
            if sender_result in observed_sender_keys
        ]
        self.populate_navigation_results(narrowed_sender_results)
        trace_result = evidence_result.get("trace") or {}
        fallback_note = trace_result.get('fallback_reason', '')
        summary_text = "Observed senders of %s: %s of %s static references." % (
            trace_description,
            len(narrowed_sender_results),
            len(self.static_sender_results),
        )
        if fallback_note:
            summary_text += ' (%s)' % fallback_note
        self.status_var.set(summary_text)

    def on_result_double_click(self, event):
        selection = self.results_listbox.curselection()
        if not selection:
            pass
            return
        selected_index = selection[0]
        selected_text = self.results_listbox.get(selected_index)
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == "method" and match_mode == "contains":
            self.find_entry.delete(0, tk.END)
            self.find_entry.insert(0, selected_text)
            self.match_mode.set("exact")
            self.find_text()
            self.update_search_context_fields()
            return
        parent = self.parent
        self.destroy()
        if search_type == "class":
            parent.handle_find_selection(search_type == "class", selected_text)
            return
        has_navigation_result = selected_index < len(self.navigation_method_results)
        if has_navigation_result:
            (
                class_name,
                show_instance_side,
                method_selector,
            ) = self.navigation_method_results[selected_index]
            parent.handle_sender_selection(
                class_name,
                show_instance_side,
                method_selector,
            )


class CoveringTestsDiscoveryWorkflow:
    def __init__(
        self,
        gemstone_session_record,
        method_name,
        max_elapsed_ms,
        merge_sender_test_plan,
    ):
        self.gemstone_session_record = gemstone_session_record
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.merge_sender_test_plan = merge_sender_test_plan
        self.should_stop = threading.Event()
        self.pending_candidate_tests = queue.Queue()
        self.accumulated_plan = None
        self.search_state = {
            "is_searching": False,
            "latest_result": None,
            "latest_error": None,
            "attempt_processed": False,
            "cancel_requested": False,
            "use_results_requested_for_attempt": False,
            "search_started": False,
        }

    def record_discovered_test(self, candidate_test):
        self.pending_candidate_tests.put(dict(candidate_test))

    def run_search_attempt(self):
        self.search_state["is_searching"] = True
        self.search_state["latest_result"] = None
        self.search_state["latest_error"] = None
        self.search_state["attempt_processed"] = False
        self.search_state["cancel_requested"] = False
        self.search_state["use_results_requested_for_attempt"] = False
        self.search_state["search_started"] = True
        self.should_stop.clear()

        def discover_tests():
            try:
                self.search_state["latest_result"] = (
                    self.gemstone_session_record.plan_sender_evidence_tests(
                        self.method_name,
                        max_depth=2,
                        max_nodes=500,
                        max_senders_per_selector=200,
                        max_test_methods=200,
                        max_elapsed_ms=self.max_elapsed_ms,
                        should_stop=self.should_stop.is_set,
                        on_candidate_test=self.record_discovered_test,
                    )
                )
            except (GemstoneDomainException, GemstoneError) as error:
                self.search_state["latest_error"] = error
            finally:
                self.search_state["is_searching"] = False

        search_thread = threading.Thread(
            target=discover_tests,
            daemon=True,
        )
        search_thread.start()

    def flush_discovered_tests(self, on_candidate_test):
        keep_flushing = True
        while keep_flushing:
            discovered_test = None
            try:
                discovered_test = self.pending_candidate_tests.get_nowait()
            except queue.Empty:
                keep_flushing = False
            if discovered_test is not None:
                on_candidate_test(discovered_test)

    def request_cancel(self):
        self.search_state["cancel_requested"] = True
        self.should_stop.set()

    def request_use_results(self):
        self.search_state["use_results_requested_for_attempt"] = True
        self.should_stop.set()

    def searching(self):
        return self.search_state["is_searching"]

    def latest_error(self):
        return self.search_state["latest_error"]

    def cancelled(self):
        return self.search_state["cancel_requested"]

    def advance(self, stop_requested, use_results_requested, on_candidate_test):
        self.flush_discovered_tests(on_candidate_test)
        if stop_requested:
            self.request_cancel()
        if use_results_requested:
            self.request_use_results()

        if self.search_state["is_searching"]:
            return {"phase": "searching"}
        if not self.search_state["search_started"]:
            return {"phase": "idle"}
        if self.search_state["attempt_processed"]:
            return {"phase": "idle"}
        self.search_state["attempt_processed"] = True

        if self.search_state["cancel_requested"]:
            return {"phase": "cancelled"}
        if self.search_state["latest_error"] is not None:
            return {
                "phase": "error",
                "error": self.search_state["latest_error"],
            }
        if self.search_state["latest_result"] is None:
            return {"phase": "empty"}

        self.accumulated_plan = self.merge_sender_test_plan(
            self.accumulated_plan,
            self.search_state["latest_result"],
        )
        result_stopped_by_user = self.search_state["latest_result"].get(
            "stopped_by_user",
            False,
        )
        used_results_requested = self.search_state["use_results_requested_for_attempt"]
        if result_stopped_by_user and not used_results_requested:
            return {"phase": "cancelled"}
        return {
            "phase": "ready",
            "plan": self.accumulated_plan,
            "timed_out": self.search_state["latest_result"].get(
                "elapsed_limit_reached",
                False,
            ),
            "used_results": used_results_requested,
        }


class CoveringTestsSearchDialog(tk.Toplevel):
    def __init__(self, parent, method_name, max_elapsed_ms):
        super().__init__(parent)
        self.title("Trace Narrowing Tests")
        self.geometry("760x520")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.selected_tests = None
        self.was_cancelled = True
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.is_searching = False
        self.is_timed_out = False
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.candidate_tests_by_key = {}
        self.candidate_test_order = []
        self.checkbox_variables_by_key = {}
        self.checkbox_widgets_by_key = {}
        self.visited_selector_count = 0
        self.elapsed_ms = 0
        self.summary_message = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.summary_label = ttk.Label(
            self,
            text="",
            justify="left",
        )
        self.summary_label.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=10,
            pady=(10, 6),
            sticky="w",
        )

        self.progress_bar = ttk.Progressbar(
            self,
            mode="indeterminate",
            length=360,
        )
        self.progress_bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(0, 6),
        )

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=10)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.scrollbar.grid(row=2, column=1, sticky="ns", padx=(0, 10))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.tests_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.tests_frame,
            anchor="nw",
        )
        self.tests_frame.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.update_canvas_window_width)

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=10)
        self.select_all_button = ttk.Button(
            self.buttons,
            text="Select All",
            command=self.select_all_tests,
        )
        self.select_all_button.grid(row=0, column=0, padx=(0, 4))
        self.select_none_button = ttk.Button(
            self.buttons,
            text="Select None",
            command=self.select_no_tests,
        )
        self.select_none_button.grid(row=0, column=1, padx=(0, 10))
        self.run_selected_button = ttk.Button(
            self.buttons,
            text="Run Selected While Tracing",
            command=self.run_selected_tests,
        )
        self.run_selected_button.grid(row=0, column=2, padx=(0, 4))
        self.use_results_button = ttk.Button(
            self.buttons,
            text="Use Results So Far",
            command=self.request_use_results,
        )
        self.use_results_button.grid(row=0, column=3, padx=(0, 4))
        self.stop_search_button = ttk.Button(
            self.buttons,
            text="Stop Searching For Tests",
            command=self.request_stop_search,
        )
        self.stop_search_button.grid(row=0, column=4, padx=(0, 4))
        self.search_further_button = ttk.Button(
            self.buttons,
            text="Search Further",
            command=self.request_search_further,
        )
        self.search_further_button.grid(row=0, column=5, padx=(0, 4))
        self.cancel_button = ttk.Button(
            self.buttons,
            text="Cancel",
            command=self.cancel_dialog,
        )
        self.cancel_button.grid(row=0, column=6)
        self.protocol("WM_DELETE_WINDOW", self.cancel_dialog)
        self.set_searching_state()

    def candidate_test_key(self, candidate_test):
        return (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
        )

    def summary_text(self):
        candidate_count = len(self.candidate_test_order)
        if self.is_searching:
            return (
                "Searching for candidate tests for %s... "
                "Found: %s, explored selectors: %s."
            ) % (
                self.method_name,
                candidate_count,
                self.visited_selector_count,
            )
        if self.is_timed_out:
            return (
                "Search reached %ss timeout. Found: %s, explored selectors: %s. "
                "Select tests to run now or choose Search Further."
            ) % (
                int(self.max_elapsed_ms / 1000),
                candidate_count,
                self.visited_selector_count,
            )
        return ("Candidate tests for %s: %s (explored selectors: %s).") % (
            self.method_name,
            candidate_count,
            self.visited_selector_count,
        )

    def refresh_summary(self):
        summary_text = self.summary_text()
        if self.summary_message:
            summary_text = "%s %s" % (summary_text, self.summary_message)
        self.summary_label.configure(text=summary_text)

    def format_test_label(self, candidate_test):
        return "%s>>%s (depth %s via %s)" % (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
            candidate_test.get("depth", "?"),
            candidate_test.get("reached_from_selector", "?"),
        )

    def update_scroll_region(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_canvas_window_width(self, event):
        self.canvas.itemconfigure(
            self.canvas_window,
            width=event.width,
        )

    def selection_controls_enabled(self):
        has_tests = len(self.candidate_test_order) > 0
        return has_tests and not self.is_searching

    def update_button_states(self):
        selection_controls_enabled = self.selection_controls_enabled()
        select_button_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        run_button_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        self.select_all_button.configure(state=select_button_state)
        self.select_none_button.configure(state=select_button_state)
        self.run_selected_button.configure(state=run_button_state)
        use_results_state = tk.NORMAL if self.is_searching else tk.DISABLED
        stop_search_state = tk.NORMAL if self.is_searching else tk.DISABLED
        self.use_results_button.configure(state=use_results_state)
        self.stop_search_button.configure(state=stop_search_state)
        search_further_state = tk.DISABLED
        if self.is_timed_out and not self.is_searching:
            search_further_state = tk.NORMAL
        self.search_further_button.configure(state=search_further_state)
        checkbox_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        for checkbox_widget in self.checkbox_widgets_by_key.values():
            checkbox_widget.configure(state=checkbox_state)

    def set_searching_state(self):
        self.is_searching = True
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.summary_message = ""
        self.progress_bar.start(10)
        self.update_button_states()
        self.refresh_summary()

    def set_stopping_for_use_results_state(self):
        self.summary_message = "Stopping search to use the current results..."
        self.refresh_summary()

    def set_stopping_for_cancel_state(self):
        self.summary_message = "Stopping search and cancelling..."
        self.refresh_summary()

    def set_ready_state(self, timed_out=False, summary_message=""):
        self.is_searching = False
        self.is_timed_out = timed_out
        self.summary_message = summary_message
        self.progress_bar.stop()
        self.update_button_states()
        self.refresh_summary()

    def set_metrics_from_test_plan(self, test_plan):
        self.visited_selector_count = test_plan.get(
            "visited_selector_count",
            self.visited_selector_count,
        )
        self.elapsed_ms = test_plan.get("elapsed_ms", self.elapsed_ms)
        self.refresh_summary()

    def add_or_update_candidate_test(self, candidate_test):
        candidate_key = self.candidate_test_key(candidate_test)
        has_candidate = candidate_key in self.candidate_tests_by_key
        if has_candidate:
            existing_candidate = self.candidate_tests_by_key[candidate_key]
            candidate_depth = candidate_test.get("depth", 0)
            existing_depth = existing_candidate.get("depth", 0)
            if candidate_depth < existing_depth:
                self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
                checkbutton = self.checkbox_widgets_by_key[candidate_key]
                checkbutton.configure(text=self.format_test_label(candidate_test))
        if not has_candidate:
            self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
            self.candidate_test_order.append(candidate_key)
            row_index = len(self.candidate_test_order) - 1
            default_checked_count = 20
            is_default_checked = row_index < default_checked_count
            selected = tk.BooleanVar(value=is_default_checked)
            self.checkbox_variables_by_key[candidate_key] = selected
            checkbutton = ttk.Checkbutton(
                self.tests_frame,
                text=self.format_test_label(candidate_test),
                variable=selected,
            )
            self.checkbox_widgets_by_key[candidate_key] = checkbutton
            checkbutton.grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=4,
                pady=2,
            )
            self.update_scroll_region()
        self.update_button_states()
        self.refresh_summary()

    def add_candidate_tests(self, candidate_tests):
        for candidate_test in candidate_tests:
            self.add_or_update_candidate_test(candidate_test)

    def selected_candidate_tests(self):
        selected_tests = []
        for candidate_key in self.candidate_test_order:
            selected_variable = self.checkbox_variables_by_key[candidate_key]
            if selected_variable.get():
                selected_tests.append(dict(self.candidate_tests_by_key[candidate_key]))
        return selected_tests

    def select_all_tests(self):
        for selected in self.checkbox_variables_by_key.values():
            selected.set(True)

    def select_no_tests(self):
        for selected in self.checkbox_variables_by_key.values():
            selected.set(False)

    def request_use_results(self):
        if self.is_searching:
            self.use_results_requested = True
            self.set_stopping_for_use_results_state()

    def request_stop_search(self):
        if self.is_searching:
            self.stop_search_requested = True
            self.set_stopping_for_cancel_state()

    def request_search_further(self):
        if not self.is_searching and self.is_timed_out:
            self.search_further_requested = True
            self.summary_message = ""
            self.refresh_summary()

    def cancel_dialog(self):
        if self.is_searching:
            self.request_stop_search()
        if not self.is_searching:
            self.destroy()

    def run_selected_tests(self):
        selected_tests = self.selected_candidate_tests()
        if not selected_tests:
            messagebox.showwarning(
                "Trace Narrowing",
                "Select at least one test.",
                parent=self,
            )
            return
        self.selected_tests = selected_tests
        self.was_cancelled = False
        self.destroy()


class CoveringTestsBrowseDialog(tk.Toplevel):
    def __init__(self, browser_window, method_name, max_elapsed_ms=120000):
        super().__init__(browser_window)
        self.title("Covering Tests")
        self.geometry("760x520")
        self.transient(browser_window)
        self.wait_visibility()
        self.grab_set()

        self.browser_window = browser_window
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.candidate_tests_by_key = {}
        self.candidate_test_keys_in_order = []
        self.candidate_test_index_by_key = {}
        self.visited_selector_count = 0
        self.summary_message = ""
        self.discovery_workflow = CoveringTestsDiscoveryWorkflow(
            browser_window.gemstone_session_record,
            method_name,
            max_elapsed_ms,
            self.merged_sender_test_plan,
        )
        self.is_searching = False
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.summary_label = ttk.Label(
            self,
            text="",
            justify="left",
        )
        self.summary_label.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=10,
            pady=(10, 6),
            sticky="w",
        )

        self.progress_bar = ttk.Progressbar(
            self,
            mode="indeterminate",
            length=360,
        )
        self.progress_bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(0, 6),
        )

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind("<Double-Button-1>", self.on_result_double_click)
        self.results_listbox.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=(10, 0),
            pady=(0, 8),
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.results_listbox.yview,
        )
        self.scrollbar.grid(
            row=2,
            column=1,
            sticky="ns",
            padx=(0, 10),
            pady=(0, 8),
        )
        self.results_listbox.configure(yscrollcommand=self.scrollbar.set)

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(0, 10))
        self.use_results_button = ttk.Button(
            self.buttons,
            text="Use Results So Far",
            command=self.request_use_results,
        )
        self.use_results_button.grid(row=0, column=0, padx=(0, 4))
        self.stop_search_button = ttk.Button(
            self.buttons,
            text="Stop Searching For Tests",
            command=self.request_stop_search,
        )
        self.stop_search_button.grid(row=0, column=1, padx=(0, 4))
        self.search_further_button = ttk.Button(
            self.buttons,
            text="Search Further",
            command=self.request_search_further,
        )
        self.search_further_button.grid(row=0, column=2, padx=(0, 4))
        self.close_button = ttk.Button(
            self.buttons,
            text="Close",
            command=self.close_dialog,
        )
        self.close_button.grid(row=0, column=3)
        self.protocol("WM_DELETE_WINDOW", self.close_dialog)

        self.run_search_attempt()
        self.after(50, self.monitor_search)

    def candidate_test_key(self, candidate_test):
        return (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
        )

    def merged_sender_test_plan(self, current_plan, new_plan):
        if current_plan is None:
            merged_plan = dict(new_plan)
            merged_plan["candidate_tests"] = list(new_plan.get("candidate_tests", []))
            merged_plan["sender_edges"] = list(new_plan.get("sender_edges", []))
            merged_plan["candidate_test_count"] = len(merged_plan["candidate_tests"])
            merged_plan["sender_edge_count"] = len(merged_plan["sender_edges"])
            return merged_plan

        merged_plan = dict(current_plan)
        candidate_tests_by_key = {}
        for candidate_test in current_plan.get("candidate_tests", []):
            candidate_tests_by_key[self.candidate_test_key(candidate_test)] = dict(
                candidate_test
            )
        for candidate_test in new_plan.get("candidate_tests", []):
            current_candidate_test_key = self.candidate_test_key(candidate_test)
            if current_candidate_test_key in candidate_tests_by_key:
                existing_candidate_test = candidate_tests_by_key[
                    current_candidate_test_key
                ]
                if candidate_test.get("depth", 0) < existing_candidate_test.get(
                    "depth",
                    0,
                ):
                    candidate_tests_by_key[current_candidate_test_key] = dict(
                        candidate_test
                    )
            if current_candidate_test_key not in candidate_tests_by_key:
                candidate_tests_by_key[current_candidate_test_key] = dict(
                    candidate_test
                )
        merged_candidate_tests = sorted(
            candidate_tests_by_key.values(),
            key=lambda candidate_test: (
                candidate_test.get("depth", 0),
                candidate_test["test_case_class_name"],
                candidate_test["test_method_selector"],
            ),
        )

        sender_edges_by_key = {}
        for sender_edge in current_plan.get("sender_edges", []) + new_plan.get(
            "sender_edges", []
        ):
            sender_edge_key = (
                sender_edge["from_selector"],
                sender_edge["to_class_name"],
                sender_edge["to_method_selector"],
                sender_edge["to_show_instance_side"],
                sender_edge["depth"],
            )
            sender_edges_by_key[sender_edge_key] = dict(sender_edge)
        merged_sender_edges = list(sender_edges_by_key.values())

        merged_plan["candidate_tests"] = merged_candidate_tests
        merged_plan["candidate_test_count"] = len(merged_candidate_tests)
        merged_plan["sender_edges"] = merged_sender_edges
        merged_plan["sender_edge_count"] = len(merged_sender_edges)
        merged_plan["visited_selector_count"] = max(
            current_plan.get("visited_selector_count", 0),
            new_plan.get("visited_selector_count", 0),
        )
        merged_plan["sender_search_truncated"] = current_plan.get(
            "sender_search_truncated", False
        ) or new_plan.get("sender_search_truncated", False)
        merged_plan["selector_limit_reached"] = current_plan.get(
            "selector_limit_reached", False
        ) or new_plan.get("selector_limit_reached", False)
        merged_plan["elapsed_limit_reached"] = new_plan.get(
            "elapsed_limit_reached",
            False,
        )
        merged_plan["elapsed_ms"] = current_plan.get("elapsed_ms", 0) + new_plan.get(
            "elapsed_ms",
            0,
        )
        merged_plan["max_elapsed_ms"] = self.max_elapsed_ms
        merged_plan["stopped_by_user"] = new_plan.get("stopped_by_user", False)
        return merged_plan

    def format_test_label(self, candidate_test):
        return "%s>>%s (depth %s via %s)" % (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
            candidate_test.get("depth", "?"),
            candidate_test.get("reached_from_selector", "?"),
        )

    def summary_text(self):
        candidate_count = len(self.candidate_test_keys_in_order)
        if self.is_searching:
            return (
                "Searching for covering tests for %s... "
                "Found: %s, explored selectors: %s."
            ) % (
                self.method_name,
                candidate_count,
                self.visited_selector_count,
            )
        if self.is_timed_out:
            return (
                "Search reached %ss timeout. Found: %s, explored selectors: %s."
            ) % (
                int(self.max_elapsed_ms / 1000),
                candidate_count,
                self.visited_selector_count,
            )
        return ("Covering tests for %s: %s (explored selectors: %s).") % (
            self.method_name,
            candidate_count,
            self.visited_selector_count,
        )

    def refresh_summary(self):
        summary_text = self.summary_text()
        if self.summary_message:
            summary_text = "%s %s" % (summary_text, self.summary_message)
        self.summary_label.configure(text=summary_text)

    def update_button_states(self):
        use_results_state = tk.NORMAL if self.is_searching else tk.DISABLED
        stop_search_state = tk.NORMAL if self.is_searching else tk.DISABLED
        search_further_state = (
            tk.NORMAL if self.is_timed_out and not self.is_searching else tk.DISABLED
        )
        self.use_results_button.configure(state=use_results_state)
        self.stop_search_button.configure(state=stop_search_state)
        self.search_further_button.configure(state=search_further_state)
        self.results_listbox.configure(state=tk.NORMAL)

    def add_or_update_candidate_test(self, candidate_test):
        candidate_key = self.candidate_test_key(candidate_test)
        has_candidate = candidate_key in self.candidate_tests_by_key
        if has_candidate:
            existing_candidate = self.candidate_tests_by_key[candidate_key]
            candidate_depth = candidate_test.get("depth", 0)
            existing_depth = existing_candidate.get("depth", 0)
            if candidate_depth < existing_depth:
                self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
                candidate_index = self.candidate_test_index_by_key[candidate_key]
                self.results_listbox.delete(candidate_index)
                self.results_listbox.insert(
                    candidate_index,
                    self.format_test_label(candidate_test),
                )
        if not has_candidate:
            candidate_index = len(self.candidate_test_keys_in_order)
            self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
            self.candidate_test_keys_in_order.append(candidate_key)
            self.candidate_test_index_by_key[candidate_key] = candidate_index
            self.results_listbox.insert(
                tk.END,
                self.format_test_label(candidate_test),
            )
        self.refresh_summary()

    def run_search_attempt(self):
        self.is_searching = True
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.summary_message = ""
        self.progress_bar.start(10)
        self.update_button_states()
        self.refresh_summary()
        self.discovery_workflow.run_search_attempt()

    def set_ready_state(self, timed_out=False, summary_message=""):
        self.is_searching = False
        self.is_timed_out = timed_out
        self.summary_message = summary_message
        self.progress_bar.stop()
        self.update_button_states()
        self.refresh_summary()

    def add_candidate_tests(self, candidate_tests):
        for candidate_test in candidate_tests:
            self.add_or_update_candidate_test(candidate_test)

    def monitor_search(self):
        if not self.winfo_exists():
            return
        if self.stop_search_requested and self.discovery_workflow.searching():
            self.summary_message = "Stopping search and closing..."
            self.refresh_summary()
        if self.use_results_requested and self.discovery_workflow.searching():
            self.summary_message = "Stopping search to use the current results..."
            self.refresh_summary()

        search_outcome = self.discovery_workflow.advance(
            self.stop_search_requested,
            self.use_results_requested,
            self.add_or_update_candidate_test,
        )

        if search_outcome["phase"] == "searching":
            self.after(50, self.monitor_search)
            return
        if search_outcome["phase"] == "cancelled":
            self.destroy()
            return
        if search_outcome["phase"] == "error":
            messagebox.showerror(
                "Covering Tests",
                str(search_outcome["error"]),
                parent=self,
            )
            self.set_ready_state(
                timed_out=False,
                summary_message="Search failed.",
            )
        if search_outcome["phase"] == "empty":
            self.set_ready_state(
                timed_out=False,
                summary_message="Search finished without results.",
            )
        if search_outcome["phase"] == "ready":
            accumulated_plan = search_outcome["plan"]
            self.visited_selector_count = max(
                self.visited_selector_count,
                accumulated_plan.get("visited_selector_count", 0),
            )
            self.add_candidate_tests(accumulated_plan.get("candidate_tests", []))
            summary_message = ""
            if search_outcome["used_results"]:
                summary_message = "Using the results found so far."
            if search_outcome["timed_out"]:
                summary_message = (
                    "Search timed out. You can continue with Search Further."
                )
            self.set_ready_state(
                timed_out=search_outcome["timed_out"],
                summary_message=summary_message,
            )

        if self.winfo_exists():
            if self.search_further_requested:
                self.search_further_requested = False
                self.run_search_attempt()
            self.after(50, self.monitor_search)

    def request_use_results(self):
        if self.is_searching:
            self.use_results_requested = True

    def request_stop_search(self):
        if self.is_searching:
            self.stop_search_requested = True
        if not self.is_searching:
            self.destroy()

    def request_search_further(self):
        if not self.is_searching and self.is_timed_out:
            self.search_further_requested = True
            self.summary_message = ""
            self.refresh_summary()

    def close_dialog(self):
        if self.is_searching:
            self.stop_search_requested = True
        if not self.is_searching:
            self.destroy()

    def on_result_double_click(self, event):
        if self.is_searching:
            return
        selection = self.results_listbox.curselection()
        if not selection:
            return
        selected_index = selection[0]
        candidate_key = self.candidate_test_keys_in_order[selected_index]
        candidate_test = self.candidate_tests_by_key[candidate_key]
        self.browser_window.application.handle_sender_selection(
            candidate_test["test_case_class_name"],
            True,
            candidate_test["test_method_selector"],
        )


class BreakpointsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.gemstone_session_record = parent.gemstone_session_record
        self.breakpoint_entries_by_id = {}
        self.title("Breakpoints")
        self.geometry("760x320")
        self.transient(parent)
        if parent.winfo_viewable():
            self.wait_visibility()
        self.grab_set()

        self.breakpoint_list = ttk.Treeview(
            self,
            columns=("Class", "Side", "Selector", "Offset", "Step Point"),
            show="headings",
            height=10,
        )
        self.breakpoint_list.heading("Class", text="Class")
        self.breakpoint_list.heading("Side", text="Side")
        self.breakpoint_list.heading("Selector", text="Method")
        self.breakpoint_list.heading("Offset", text="Offset")
        self.breakpoint_list.heading("Step Point", text="Step Point")
        self.breakpoint_list.column("Class", width=180, anchor="w")
        self.breakpoint_list.column("Side", width=80, anchor="center")
        self.breakpoint_list.column("Selector", width=220, anchor="w")
        self.breakpoint_list.column("Offset", width=100, anchor="e")
        self.breakpoint_list.column("Step Point", width=100, anchor="e")
        self.breakpoint_list.bind("<Double-1>", self.on_breakpoint_double_click)
        self.breakpoint_list.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="nsew",
            padx=10,
            pady=(10, 6),
        )

        self.clear_selected_button = ttk.Button(
            self,
            text="Clear Selected",
            command=self.clear_selected_breakpoint,
        )
        self.clear_selected_button.grid(
            row=1,
            column=0,
            padx=(10, 5),
            pady=(0, 10),
            sticky="w",
        )
        self.clear_all_button = ttk.Button(
            self,
            text="Clear All",
            command=self.clear_all_breakpoints,
        )
        self.clear_all_button.grid(
            row=1,
            column=1,
            padx=5,
            pady=(0, 10),
            sticky="w",
        )
        self.close_button = ttk.Button(
            self,
            text="Close",
            command=self.destroy,
        )
        self.close_button.grid(
            row=1,
            column=2,
            padx=(5, 10),
            pady=(0, 10),
            sticky="e",
        )
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(0, weight=1)

        self.refresh_breakpoints()

    def refresh_breakpoints(self):
        self.breakpoint_entries_by_id = {}
        for row_id in self.breakpoint_list.get_children():
            self.breakpoint_list.delete(row_id)
        breakpoint_entries = self.gemstone_session_record.list_breakpoints()
        for breakpoint_entry in breakpoint_entries:
            side_label = "instance"
            if not breakpoint_entry["show_instance_side"]:
                side_label = "class"
            self.breakpoint_entries_by_id[breakpoint_entry["breakpoint_id"]] = (
                breakpoint_entry
            )
            self.breakpoint_list.insert(
                "",
                "end",
                iid=breakpoint_entry["breakpoint_id"],
                values=(
                    breakpoint_entry["class_name"],
                    side_label,
                    breakpoint_entry["method_selector"],
                    breakpoint_entry["source_offset"],
                    breakpoint_entry["step_point"],
                ),
            )

    def on_breakpoint_double_click(self, event):
        breakpoint_id = self.selected_breakpoint_id()
        if breakpoint_id is None:
            return
        breakpoint_entry = self.breakpoint_entries_by_id.get(breakpoint_id)
        if breakpoint_entry is None:
            return
        try:
            self.parent.handle_sender_selection(
                breakpoint_entry["class_name"],
                breakpoint_entry["show_instance_side"],
                breakpoint_entry["method_selector"],
            )
            if self.parent.browser_tab:
                self.parent.notebook.select(self.parent.browser_tab)
            self.destroy()
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))

    def selected_breakpoint_id(self):
        selection = self.breakpoint_list.selection()
        if not selection:
            return None
        return selection[0]

    def clear_selected_breakpoint(self):
        breakpoint_id = self.selected_breakpoint_id()
        if breakpoint_id is None:
            return
        try:
            self.gemstone_session_record.clear_breakpoint(breakpoint_id)
            self.refresh_breakpoints()
            self.parent.event_queue.publish("MethodsChanged")
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))

    def clear_all_breakpoints(self):
        try:
            self.gemstone_session_record.clear_all_breakpoints()
            self.refresh_breakpoints()
            self.parent.event_queue.publish("MethodsChanged")
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))


class Swordfish(tk.Tk):
    @classmethod
    def new_argument_parser(cls, default_mode="ide"):
        argument_parser = argparse.ArgumentParser(
            description="Run Swordfish IDE and MCP server."
        )
        default_headless_mcp = default_mode == "mcp-headless"
        argument_parser.add_argument(
            "stone_name",
            nargs="?",
            default="gs64stone",
            help="GemStone stone name to prefill in login form.",
        )
        argument_parser.add_argument(
            "--headless-mcp",
            action="store_true",
            default=default_headless_mcp,
            help="Run MCP only (headless, no GUI).",
        )
        argument_parser.add_argument(
            "--mode",
            default=None,
            choices=["ide", "mcp-headless"],
            help=argparse.SUPPRESS,
        )
        argument_parser.add_argument(
            "--transport",
            default="stdio",
            choices=["stdio", "streamable-http"],
            help="MCP transport type for --headless-mcp mode.",
        )
        argument_parser.add_argument(
            "--mcp-host",
            default="127.0.0.1",
            help="Host interface for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--mcp-port",
            default=8000,
            type=int,
            help="TCP port for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--mcp-http-path",
            default="/mcp",
            help="HTTP path for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--allow-source-read",
            action="store_true",
            dest="allow_source_read",
            default=True,
            help="Enable source read tools (enabled by default).",
        )
        argument_parser.add_argument(
            "--disallow-source-read",
            action="store_false",
            dest="allow_source_read",
            help="Disable source read tools.",
        )
        argument_parser.add_argument(
            "--allow-source-write",
            action="store_true",
            help="Enable source write/refactor tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-eval-arbitrary",
            action="store_true",
            help="Enable gs_eval and gs_debug_eval (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-ide-read",
            action="store_true",
            dest="allow_ide_read",
            default=True,
            help="Enable IDE state read tools (enabled by default).",
        )
        argument_parser.add_argument(
            "--disallow-ide-read",
            action="store_false",
            dest="allow_ide_read",
            help="Disable IDE state read tools.",
        )
        argument_parser.add_argument(
            "--allow-ide-write",
            action="store_true",
            help="Enable IDE navigation/write tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-test-execution",
            action="store_true",
            help="Enable test execution tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-commit",
            action="store_true",
            help="Enable gs_commit tool (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-tracing",
            action="store_true",
            help="Enable gs_tracer_* and evidence tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--require-gemstone-ast",
            action="store_true",
            help=(
                "Require real GemStone AST backend for refactoring tools. "
                "When enabled, heuristic refactorings are blocked."
            ),
        )
        return argument_parser

    @classmethod
    def validate_arguments(cls, argument_parser, arguments):
        if arguments.mcp_port <= 0:
            argument_parser.error("--mcp-port must be greater than zero.")
        if not arguments.mcp_http_path.startswith("/"):
            argument_parser.error("--mcp-http-path must start with /.")

    @classmethod
    def run(cls, default_mode="ide"):
        argument_parser = cls.new_argument_parser(default_mode=default_mode)
        arguments = argument_parser.parse_args()
        cls.validate_arguments(argument_parser, arguments)
        argument_tokens = sys.argv[1:]
        configuration_store = McpConfigurationStore()
        runtime_config = configuration_store.merged_config_from_arguments(
            arguments,
            argument_tokens=argument_tokens,
        )
        run_headless_mcp = arguments.headless_mcp
        if arguments.mode == "mcp-headless":
            run_headless_mcp = True
        if arguments.mode == "ide":
            run_headless_mcp = False
        if run_headless_mcp:
            mcp_server_controller = McpServerController(
                integrated_session_state=None,
                runtime_config=runtime_config,
                configuration_store=configuration_store,
            )
            mcp_server_controller.run(arguments.transport)
            return
        app = cls(
            default_stone_name=arguments.stone_name,
            start_embedded_mcp=False,
            mcp_runtime_config=runtime_config,
            mcp_configuration_store=configuration_store,
        )
        app.mainloop()

    def __init__(
        self,
        default_stone_name="gs64stone",
        start_embedded_mcp=False,
        mcp_runtime_config=None,
        mcp_configuration_store=None,
    ):
        super().__init__()
        self.action_gate = ActionGate()
        self.busy_coordinator = BusyCoordinator()
        self.event_queue = EventQueue(self)
        self.integrated_session_state = current_integrated_session_state()
        self.integrated_session_state.attach_ide_gui(
            ide_gui=self,
            ide_navigation_action=self.perform_mcp_ide_navigation_action,
        )
        self.title("Swordfish")
        self.geometry("800x600")
        self.default_stone_name = default_stone_name

        self.notebook = None
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.graph_tab = None
        self.uml_tab = None
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.collaboration_status_text = tk.StringVar(value="")
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False
        self.foreground_activity_message = ""

        self.gemstone_session_record = None
        self.last_mcp_busy_state = None
        self.last_mcp_server_running_state = None
        self.last_mcp_server_starting_state = None
        self.last_mcp_server_stopping_state = None
        self.last_mcp_server_error_message = None
        self.last_mcp_config_save_error_message = None
        if mcp_runtime_config is None:
            mcp_runtime_config = McpRuntimeConfig()
        self.mcp_runtime_config = mcp_runtime_config.copy()
        self.mcp_server_controller = McpServerController(
            self.integrated_session_state,
            self.mcp_runtime_config,
            configuration_store=mcp_configuration_store,
        )

        self.event_queue.subscribe("LoggedInSuccessfully", self.show_main_app)
        self.event_queue.subscribe("LoggedOut", self.show_login_screen)
        self.event_queue.subscribe(
            "McpBusyStateChanged",
            self.handle_mcp_busy_state_changed,
        )
        self.event_queue.subscribe(
            "McpServerStateChanged",
            self.handle_mcp_server_state_changed,
        )
        self.event_queue.subscribe(
            "ModelRefreshRequested",
            self.handle_model_refresh_requested,
        )
        self.event_queue.subscribe(
            "McpIdeNavigationRequested",
            self.handle_mcp_ide_navigation_requested,
        )
        self.event_queue.subscribe(
            "OpenRunWindow",
            self.handle_open_run_window,
        )
        self.integrated_session_state.subscribe_mcp_busy_state(
            self.publish_mcp_busy_state_event,
        )
        self.integrated_session_state.subscribe_model_refresh_requests(
            self.publish_model_refresh_requested_event,
        )
        self.mcp_server_controller.subscribe_server_state(
            self.publish_mcp_server_state_event,
        )

        self.create_menu()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(**self.mcp_server_controller.status())
        if start_embedded_mcp:
            self.start_mcp_server(report_errors=False)
        self.show_login_screen()
        self.refresh_collaboration_status()

    @property
    def is_logged_in(self):
        return self.gemstone_session_record is not None

    def create_menu(self):
        self.menu_bar = MainMenu(self, self.event_queue)
        self.config(menu=self.menu_bar)

    def embedded_mcp_server_status(self):
        return self.mcp_server_controller.status()

    def start_mcp_server(self, report_errors=True):
        started = self.mcp_server_controller.start()
        if not started and report_errors:
            messagebox.showinfo(
                "MCP",
                "MCP is already running or starting.",
            )
        return started

    def stop_mcp_server(self):
        stopped = self.mcp_server_controller.stop()
        if not stopped:
            messagebox.showinfo(
                "MCP",
                "MCP is already stopped.",
            )
        return stopped

    def start_mcp_server_from_menu(self):
        self.begin_foreground_activity("Starting MCP server...")
        try:
            self.start_mcp_server(report_errors=True)
            self.menu_bar.update_menus()
        finally:
            self.end_foreground_activity()

    def stop_mcp_server_from_menu(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Stop MCP after the current MCP operation finishes.",
            )
            return
        self.begin_foreground_activity("Stopping MCP server...")
        try:
            self.stop_mcp_server()
            self.menu_bar.update_menus()
        finally:
            self.end_foreground_activity()

    def configure_mcp_server_from_menu(self):
        dialog = McpConfigurationDialog(self, self.mcp_runtime_config)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.mcp_runtime_config = dialog.result.copy()
        self.mcp_server_controller.update_runtime_config(self.mcp_runtime_config)
        try:
            self.mcp_server_controller.save_configuration()
            self.last_mcp_config_save_error_message = None
        except DomainException as error:
            self.last_mcp_config_save_error_message = str(error)
            messagebox.showerror(
                "MCP Configuration",
                str(error),
            )
        self.menu_bar.update_menus()
        self.refresh_collaboration_status()

    def commit(self):
        self.gemstone_session_record.commit()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish("Committed")
        self.publish_model_change_events("transaction")

    def abort(self):
        self.gemstone_session_record.abort()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish("Aborted")
        self.publish_model_change_events("transaction")

    def logout(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Logout is disabled while MCP is running an operation.",
            )
            return
        self.gemstone_session_record.log_out()
        self.gemstone_session_record = None
        self.integrated_session_state.detach_ide_session()
        self.event_queue.publish("LoggedOut")

    def clear_widgets(self):
        for widget in self.winfo_children():
            if widget != self.menu_bar:
                widget.destroy()
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.graph_tab = None
        self.uml_tab = None
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False

    def show_login_screen(self):
        self.clear_widgets()
        self.collaboration_status_text.set("")
        self.foreground_activity_message = ""
        self.last_mcp_server_stopping_state = None
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        self.login_frame = LoginFrame(
            self,
            default_stone_name=self.default_stone_name,
        )
        self.login_frame.grid(row=0, column=0, sticky="nsew")

    def show_main_app(self, gemstone_session_record):
        self.gemstone_session_record = gemstone_session_record
        self.gemstone_session_record.set_integrated_session_state(
            self.integrated_session_state
        )
        self.gemstone_session_record.change_event_publisher = (
            self.publish_model_change_events
        )
        self.integrated_session_state.attach_ide_session(
            self.gemstone_session_record.gemstone_session
        )

        self.clear_widgets()

        self.create_notebook()
        self.add_browser_tab()
        self.create_collaboration_status_bar()

    def publish_model_change_events(self, change_kind):
        if change_kind == "packages":
            self.event_queue.publish("PackagesChanged")
            self.event_queue.publish("ClassesChanged")
            return
        if change_kind == "classes":
            self.event_queue.publish("ClassesChanged")
            self.event_queue.publish("SelectedClassChanged")
            return
        if change_kind == "methods":
            self.event_queue.publish("MethodsChanged")
            self.event_queue.publish("SelectedCategoryChanged")
            self.event_queue.publish("MethodSelected")
            return
        if change_kind == "transaction":
            self.event_queue.publish("PackagesChanged")
            self.event_queue.publish("ClassesChanged")
            self.event_queue.publish("MethodsChanged")

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def create_collaboration_status_bar(self):
        self.collaboration_status_frame = ttk.Frame(self)
        self.collaboration_status_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=6,
            pady=(2, 4),
        )
        self.collaboration_status_frame.columnconfigure(0, weight=1)
        self.collaboration_status_label = ttk.Label(
            self.collaboration_status_frame,
            textvariable=self.collaboration_status_text,
            anchor="w",
        )
        self.collaboration_status_label.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.mcp_activity_indicator = ttk.Progressbar(
            self.collaboration_status_frame,
            mode="indeterminate",
            length=110,
        )
        self.mcp_activity_indicator.grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )
        self.set_mcp_activity_indicator_visibility(False)
        self.rowconfigure(1, weight=0)

    def set_mcp_activity_indicator_visibility(self, visible):
        if self.mcp_activity_indicator is None:
            self.mcp_activity_indicator_visible = False
            return
        indicator_is_managed = self.mcp_activity_indicator.winfo_manager() == "grid"
        if visible:
            if not indicator_is_managed:
                self.mcp_activity_indicator.grid()
            self.mcp_activity_indicator.step(1)
            self.mcp_activity_indicator.start(10)
            if not self.mcp_activity_indicator_visible:
                self.event_queue.publish(
                    "UiActivityIndicatorChanged",
                    is_visible=True,
                )
            self.mcp_activity_indicator_visible = True
            return
        if indicator_is_managed:
            self.mcp_activity_indicator.stop()
            self.mcp_activity_indicator.configure(value=0)
            self.mcp_activity_indicator.grid_remove()
        if self.mcp_activity_indicator_visible:
            self.mcp_activity_indicator_visible = False
            self.event_queue.publish(
                "UiActivityIndicatorChanged",
                is_visible=False,
            )
            return
        self.mcp_activity_indicator_visible = False

    def begin_foreground_activity(self, message):
        self.foreground_activity_message = message
        self.event_queue.publish(
            "UiActivityChanged",
            is_active=True,
            message=message,
        )
        self.collaboration_status_text.set(message)
        self.set_mcp_activity_indicator_visibility(True)
        try:
            self.config(cursor="watch")
        except tk.TclError:
            pass
        self.update_idletasks()

    def end_foreground_activity(self):
        self.foreground_activity_message = ""
        self.event_queue.publish(
            "UiActivityChanged",
            is_active=False,
            message="",
        )
        try:
            self.config(cursor="")
        except tk.TclError:
            pass
        self.refresh_collaboration_status()

    def publish_mcp_busy_state_event(self, is_busy=False, operation_name=""):
        busy_lease_token = self.busy_coordinator.lease_for_state(
            is_busy=is_busy,
            operation_name=operation_name,
        )
        self.event_queue.publish(
            "McpBusyStateChanged",
            is_busy=is_busy,
            operation_name=operation_name,
            busy_lease_token=busy_lease_token,
        )

    def publish_mcp_server_state_event(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url="",
        configured_endpoint_url="",
        restart_required_for_config=False,
        last_error_message="",
    ):
        self.event_queue.publish(
            "McpServerStateChanged",
            running=running,
            starting=starting,
            stopping=stopping,
            endpoint_url=endpoint_url,
            configured_endpoint_url=configured_endpoint_url,
            restart_required_for_config=restart_required_for_config,
            last_error_message=last_error_message,
        )

    def publish_model_refresh_requested_event(self, change_kind=""):
        self.event_queue.publish(
            "ModelRefreshRequested",
            change_kind=change_kind,
        )

    def process_pending_model_refresh_requests(self):
        pending_change_kinds = (
            self.integrated_session_state.consume_model_refresh_requests()
        )
        if not self.is_logged_in:
            return
        for change_kind in pending_change_kinds:
            self.publish_model_change_events(change_kind)

    def apply_collaboration_read_only_state(self, read_only):
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.browser_tab.editor_area_widget.set_read_only(read_only)
        if self.run_tab is not None and self.run_tab.winfo_exists():
            self.run_tab.set_read_only(read_only)

    def refresh_collaboration_status(self):
        if not self.winfo_exists():
            return
        mcp_busy = self.integrated_session_state.is_mcp_busy()
        mcp_server_status = self.mcp_server_controller.status()
        mcp_server_running = mcp_server_status["running"]
        mcp_server_starting = mcp_server_status["starting"]
        mcp_server_stopping = mcp_server_status["stopping"]
        self.apply_collaboration_read_only_state(
            self.action_gate.read_only_for('ide_write', is_busy=mcp_busy)
        )
        self.set_mcp_activity_indicator_visibility(
            bool(self.foreground_activity_message)
            or mcp_busy
            or mcp_server_starting
            or mcp_server_stopping
        )
        if self.foreground_activity_message:
            self.collaboration_status_text.set(self.foreground_activity_message)
        elif mcp_busy:
            operation_name = (
                self.integrated_session_state.current_mcp_operation_name() or "unknown"
            )
            self.collaboration_status_text.set(
                "MCP busy: %s. IDE write/run/debug actions are read-only."
                % operation_name
            )
        elif mcp_server_stopping:
            self.collaboration_status_text.set("Stopping MCP server...")
        elif mcp_server_starting:
            self.collaboration_status_text.set("Starting MCP server...")
        elif mcp_server_running:
            runtime_message = "IDE ready. MCP running at %s." % (
                mcp_server_status["endpoint_url"]
            )
            if mcp_server_status.get("restart_required_for_config"):
                runtime_message = (
                    runtime_message
                    + " MCP config changed; stop and start MCP to apply latest settings."
                )
            self.collaboration_status_text.set(runtime_message)
        elif self.is_logged_in:
            self.collaboration_status_text.set("IDE ready. Embedded MCP is stopped.")
        else:
            self.collaboration_status_text.set("")

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name="",
        busy_lease_token=None,
    ):
        if not self.busy_coordinator.is_current_lease(busy_lease_token):
            return
        self.last_mcp_busy_state = is_busy
        self.refresh_collaboration_status()

    def handle_mcp_server_state_changed(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url="",
        configured_endpoint_url="",
        restart_required_for_config=False,
        last_error_message="",
    ):
        self.last_mcp_server_running_state = running
        self.last_mcp_server_starting_state = starting
        self.last_mcp_server_stopping_state = stopping
        if (
            last_error_message
            and last_error_message != self.last_mcp_server_error_message
        ):
            self.last_mcp_server_error_message = last_error_message
            messagebox.showerror(
                "MCP Startup Failed",
                last_error_message,
            )
        if not last_error_message:
            self.last_mcp_server_error_message = None
        self.refresh_collaboration_status()

    def handle_open_run_window(self, source=''):
        self.open_run_tab()
        self.run_tab.present_source(source, run_immediately=False)

    def handle_model_refresh_requested(self, change_kind=""):
        self.process_pending_model_refresh_requests()
        self.refresh_collaboration_status()

    def validated_oop_label_for_navigation(self, oop_value):
        oop_label = ""
        if isinstance(oop_value, int):
            oop_label = str(oop_value)
        if isinstance(oop_value, str):
            oop_label = oop_value.strip()
        if not oop_label.isdigit():
            raise DomainException("oop labels must contain digits only.")
        if int(oop_label) <= 0:
            raise DomainException("oop labels must be positive integers.")
        return oop_label

    def gemstone_object_is_nil(self, gemstone_object):
        try:
            nil_value = gemstone_object.isNil().to_py
            if isinstance(nil_value, bool):
                return nil_value
            return False
        except (GemstoneError, AttributeError):
            return False

    def gemstone_object_for_oop_label(self, oop_label):
        if not self.is_logged_in:
            raise DomainException("No active GemStone session in the IDE.")
        normalized_oop_label = self.validated_oop_label_for_navigation(oop_label)
        source_candidates = [
            f"Object _objectForOop: {normalized_oop_label}",
            f"System objectForOop: {normalized_oop_label}",
        ]
        resolved_object = None
        resolved = False
        last_error = None
        for source_code in source_candidates:
            try:
                candidate_object = self.gemstone_session_record.resolve_object(
                    source_code
                )
                if self.gemstone_object_is_nil(candidate_object):
                    last_error = DomainException(
                        f"Oop {normalized_oop_label} resolved to nil."
                    )
                if not self.gemstone_object_is_nil(candidate_object):
                    resolved_object = candidate_object
                    resolved = True
            except (DomainException, GemstoneDomainException, GemstoneError) as error:
                last_error = error
            if resolved:
                return resolved_object
        if last_error is None:
            last_error = DomainException(
                f"Unable to resolve oop {normalized_oop_label}."
            )
        raise last_error

    def open_graph_for_oop_labels(self, oop_labels, clear_existing=False):
        if not self.is_logged_in:
            return {
                "ok": False,
                "error": {"message": "No active GemStone session in the IDE."},
                "opened_oops": [],
                "unresolved_oops": [],
            }
        if clear_existing:
            tab_exists = self.graph_tab is not None and self.graph_tab.winfo_exists()
            if tab_exists:
                self.graph_tab.clear_graph()
        opened_oops = []
        unresolved_oops = []
        for oop_label in oop_labels:
            normalized_oop_label = ""
            opened_object = None
            failure_message = ""
            try:
                normalized_oop_label = self.validated_oop_label_for_navigation(
                    oop_label
                )
                opened_object = self.gemstone_object_for_oop_label(normalized_oop_label)
            except (DomainException, GemstoneDomainException, GemstoneError) as error:
                failure_message = str(error)
            if opened_object is not None:
                self.open_graph_inspector_for_object(opened_object)
                opened_oops.append(normalized_oop_label)
            if opened_object is None:
                unresolved_label = str(oop_label)
                if normalized_oop_label:
                    unresolved_label = normalized_oop_label
                unresolved_oops.append(
                    {
                        "oop": unresolved_label,
                        "message": failure_message or "Unable to resolve oop.",
                    }
                )
        return {
            "ok": len(opened_oops) > 0,
            "opened_oops": opened_oops,
            "unresolved_oops": unresolved_oops,
            "graph_tab_open": self.graph_tab is not None
            and self.graph_tab.winfo_exists(),
        }

    def method_context_payload(self, method_context):
        if method_context is None:
            return None
        try:
            class_name, show_instance_side, method_symbol = method_context
        except (TypeError, ValueError):
            return None
        return {
            "class_name": class_name,
            "show_instance_side": show_instance_side,
            "method_symbol": method_symbol,
        }

    def text_widget_selection_state(self, text_widget):
        empty_selection_state = {
            "has_selection": False,
            "selection_start": None,
            "selection_end": None,
            "selected_text": "",
            "cursor_index": None,
        }
        if text_widget is None:
            return empty_selection_state
        try:
            if not text_widget.winfo_exists():
                return empty_selection_state
        except AttributeError:
            return empty_selection_state
        editable_text = EditableText(text_widget, self)
        selection_start, selection_end = editable_text.selected_range()
        selected_text = ""
        if selection_start is not None:
            try:
                selected_text = text_widget.get(selection_start, selection_end)
            except tk.TclError:
                selection_start = None
                selection_end = None
                selected_text = ""
        cursor_index = None
        try:
            cursor_index = text_widget.index(tk.INSERT)
        except tk.TclError:
            cursor_index = None
        return {
            "has_selection": selection_start is not None,
            "selection_start": selection_start,
            "selection_end": selection_end,
            "selected_text": selected_text,
            "cursor_index": cursor_index,
        }

    def browser_editor_state(self):
        if self.browser_tab is None or not self.browser_tab.winfo_exists():
            return None
        method_editor = self.browser_tab.editor_area_widget
        selected_editor_tab_id = ""
        try:
            selected_editor_tab_id = method_editor.editor_notebook.select()
        except tk.TclError:
            selected_editor_tab_id = ""
        active_editor_tab_label = None
        method_context = None
        selection_state = self.text_widget_selection_state(None)
        if selected_editor_tab_id:
            try:
                active_editor_tab_label = method_editor.editor_notebook.tab(
                    selected_editor_tab_id,
                    "text",
                )
            except tk.TclError:
                active_editor_tab_label = None
            selected_editor_tab = None
            try:
                selected_editor_tab = method_editor.editor_notebook.nametowidget(
                    selected_editor_tab_id
                )
            except tk.TclError:
                selected_editor_tab = None
            code_panel = None
            if selected_editor_tab is not None:
                code_panel = getattr(selected_editor_tab, "code_panel", None)
            if code_panel is not None:
                method_context = self.method_context_payload(
                    code_panel.method_context()
                )
                selection_state = self.text_widget_selection_state(
                    code_panel.text_editor
                )
        return {
            "active_editor_tab_label": active_editor_tab_label,
            "method_context": method_context,
            "selection": selection_state,
        }

    def debugger_source_state(self):
        if self.debugger_tab is None or not self.debugger_tab.winfo_exists():
            return None
        selected_frame = self.debugger_tab.get_selected_stack_frame()
        selected_frame_payload = None
        method_context = None
        if selected_frame is not None:
            selected_frame_payload = {
                "level": selected_frame.level,
                "class_name": selected_frame.class_name,
                "method_name": selected_frame.method_name,
                "step_point_offset": selected_frame.step_point_offset,
            }
            method_context = self.method_context_payload(
                self.debugger_tab.frame_method_context(selected_frame)
            )
        debugger_code_panel = getattr(self.debugger_tab, "code_panel", None)
        debugger_text_widget = None
        if debugger_code_panel is not None:
            debugger_text_widget = getattr(debugger_code_panel, "text_editor", None)
        selection_state = self.text_widget_selection_state(debugger_text_widget)
        return {
            "running": self.debugger_tab.is_running,
            "selected_frame": selected_frame_payload,
            "method_context": method_context,
            "selection": selection_state,
        }

    def run_source_state(self):
        if self.run_tab is None or not self.run_tab.winfo_exists():
            return None
        return {
            "selection": self.text_widget_selection_state(self.run_tab.source_text),
        }

    def mcp_runtime_state_for_ai(self):
        mcp_server_status = self.mcp_server_controller.status()
        return {
            "running": mcp_server_status["running"],
            "starting": mcp_server_status["starting"],
            "stopping": mcp_server_status["stopping"],
            "endpoint_url": mcp_server_status["endpoint_url"],
            "configured_endpoint_url": mcp_server_status["configured_endpoint_url"],
            "restart_required_for_config": mcp_server_status.get(
                "restart_required_for_config",
                False,
            ),
            "config_file_path": self.mcp_server_controller.configuration_store.config_file_path(),
            "last_save_error_message": self.last_mcp_config_save_error_message,
            "desired_runtime_config": self.mcp_runtime_config.to_dict(),
        }

    def current_ide_view_state(self):
        active_tab_id = None
        active_tab_label = None
        active_tab_kind = 'none'
        if self.notebook is not None and self.notebook.winfo_exists():
            try:
                active_tab_id = self.notebook.select()
            except tk.TclError:
                active_tab_id = None
            if active_tab_id:
                try:
                    active_tab_label = self.notebook.tab(active_tab_id, 'text')
                except tk.TclError:
                    active_tab_label = None
        if self.browser_tab is not None and active_tab_id == str(self.browser_tab):
            active_tab_kind = 'browser'
        if self.run_tab is not None and active_tab_id == str(self.run_tab):
            active_tab_kind = 'run'
        if self.debugger_tab is not None and active_tab_id == str(self.debugger_tab):
            active_tab_kind = 'debugger'
        if self.inspector_tab is not None and active_tab_id == str(self.inspector_tab):
            active_tab_kind = 'inspect'
        if self.graph_tab is not None and active_tab_id == str(self.graph_tab):
            active_tab_kind = 'graph'
        if self.uml_tab is not None and active_tab_id == str(self.uml_tab):
            active_tab_kind = 'uml'
        if active_tab_kind == 'none' and active_tab_label:
            active_tab_kind = active_tab_label.lower()

        browser_state = None
        if self.is_logged_in:
            class_view_mode = None
            if self.browser_tab is not None and self.browser_tab.winfo_exists():
                class_view_mode = (
                    'hierarchy'
                    if self.browser_tab.classes_widget.selected_tab_is_hierarchy()
                    else 'list'
                )
            browser_state = {
                'browse_mode': self.gemstone_session_record.browse_mode,
                'selected_package': self.gemstone_session_record.selected_package,
                'selected_dictionary': self.gemstone_session_record.selected_dictionary,
                'selected_class': self.gemstone_session_record.selected_class,
                'selected_method_category': (
                    self.gemstone_session_record.selected_method_category
                ),
                'selected_method_symbol': self.gemstone_session_record.selected_method_symbol,
                'show_instance_side': self.gemstone_session_record.show_instance_side,
                'class_view_mode': class_view_mode,
            }

        debugger_state = self.debugger_source_state()
        active_source_view = None
        if active_tab_kind == 'browser':
            browser_editor_state = self.browser_editor_state()
            active_source_view = {
                'kind': 'browser_method_source',
                'state': browser_editor_state,
            }
        if active_tab_kind == 'debugger':
            active_source_view = {
                'kind': 'debugger_method_source',
                'state': debugger_state,
            }
        if active_tab_kind == 'run':
            active_source_view = {
                'kind': 'run_source',
                'state': self.run_source_state(),
            }
        return {
            'ok': True,
            'is_logged_in': self.is_logged_in,
            'active_tab': {
                'label': active_tab_label,
                'kind': active_tab_kind,
            },
            'browser_state': browser_state,
            'debugger_state': debugger_state,
            'active_source_view': active_source_view,
            'find_dialog_state': self.find_dialog_state_for_mcp(),
            'mcp_runtime': self.mcp_runtime_state_for_ai(),
        }

    def active_find_dialog(self):
        find_dialog = None
        child_windows = list(self.winfo_children())
        for child_window in child_windows:
            child_is_find_dialog = isinstance(child_window, FindDialog)
            child_window_exists = False
            if child_is_find_dialog:
                try:
                    child_window_exists = bool(child_window.winfo_exists())
                except tk.TclError:
                    child_window_exists = False
            if child_is_find_dialog and child_window_exists:
                find_dialog = child_window
        return find_dialog

    def find_dialog_state_for_mcp(self):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'is_open': False,
                'is_sender_reference_search': False,
                'total_static_sender_count': 0,
                'displayed_sender_count': 0,
                'displayed_senders': [],
                'static_senders': [],
                'sender_selector_query': None,
                'sender_source_class_name': None,
            }
        return find_dialog.sender_filter_state_for_mcp()

    def validated_sender_filter_values(self, filter_values, argument_name):
        if filter_values is None:
            return []
        if not isinstance(filter_values, list):
            raise DomainException('%s must be a list of strings or None.' % argument_name)
        validated_values = []
        for index, filter_value in enumerate(filter_values):
            if not isinstance(filter_value, str):
                raise DomainException('%s[%s] must be a string.' % (argument_name, index))
            normalized_filter_value = filter_value.strip()
            if normalized_filter_value:
                validated_values.append(normalized_filter_value)
        return validated_values

    def filter_active_find_dialog_senders(
        self,
        class_category_filters=None,
        class_name_filters=None,
        method_selector_filters=None,
        method_category_filters=None,
        include_extension_method_category_for_class_category=True,
        reasoning_note='',
    ):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'ok': False,
                'error': {'message': 'No open Find dialog in the IDE.'},
            }
        return find_dialog.apply_sender_filters(
            class_category_filters=class_category_filters,
            class_name_filters=class_name_filters,
            method_selector_filters=method_selector_filters,
            method_category_filters=method_category_filters,
            include_extension_method_category_for_class_category=(
                include_extension_method_category_for_class_category
            ),
            reasoning_note=reasoning_note,
        )

    def narrow_find_dialog_senders_to_source_class_category(self):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'ok': False,
                'error': {'message': 'No open Find dialog in the IDE.'},
            }
        return find_dialog.narrow_to_source_class_category()

    def execute_mcp_ide_navigation_action(self, action_name, action_parameters=None):
        if action_parameters is None:
            action_parameters = {}
        if action_name == "open_graph_for_oops":
            oop_labels = action_parameters.get("oop_labels")
            if not isinstance(oop_labels, list):
                return {
                    "ok": False,
                    "error": {"message": "oop_labels must be a list."},
                }
            clear_existing = action_parameters.get("clear_existing", False)
            if not isinstance(clear_existing, bool):
                return {
                    "ok": False,
                    "error": {"message": "clear_existing must be a boolean."},
                }
            return self.open_graph_for_oop_labels(
                oop_labels,
                clear_existing=clear_existing,
            )
        if action_name == "select_class":
            class_name = action_parameters.get("class_name")
            if not isinstance(class_name, str):
                return {
                    "ok": False,
                    "error": {"message": "class_name must be a string."},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    "ok": False,
                    "error": {"message": "class_name cannot be empty."},
                }
            show_instance_side = action_parameters.get("show_instance_side", True)
            if not isinstance(show_instance_side, bool):
                return {
                    "ok": False,
                    "error": {"message": "show_instance_side must be a boolean."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            try:
                self.handle_find_selection(show_instance_side, class_name)
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return {
                "ok": True,
                "class_name": class_name,
                "show_instance_side": show_instance_side,
            }
        if action_name == "open_method":
            class_name = action_parameters.get("class_name")
            if not isinstance(class_name, str):
                return {
                    "ok": False,
                    "error": {"message": "class_name must be a string."},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    "ok": False,
                    "error": {"message": "class_name cannot be empty."},
                }
            method_symbol = action_parameters.get("method_symbol")
            if not isinstance(method_symbol, str):
                return {
                    "ok": False,
                    "error": {"message": "method_symbol must be a string."},
                }
            method_symbol = method_symbol.strip()
            if not method_symbol:
                return {
                    "ok": False,
                    "error": {"message": "method_symbol cannot be empty."},
                }
            show_instance_side = action_parameters.get("show_instance_side", True)
            if not isinstance(show_instance_side, bool):
                return {
                    "ok": False,
                    "error": {"message": "show_instance_side must be a boolean."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            try:
                self.handle_sender_selection(
                    class_name,
                    show_instance_side,
                    method_symbol,
                )
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return {
                "ok": True,
                "class_name": class_name,
                "show_instance_side": show_instance_side,
                "method_symbol": method_symbol,
            }
        if action_name == "open_debugger_for_exception":
            exception = action_parameters.get("exception")
            if exception is None:
                return {
                    "ok": False,
                    "error": {"message": "exception is required."},
                }
            ask_before_open = action_parameters.get("ask_before_open", False)
            if not isinstance(ask_before_open, bool):
                return {
                    "ok": False,
                    "error": {"message": "ask_before_open must be a boolean."},
                }
            return self.open_debugger_for_mcp_exception(
                exception,
                ask_before_open=ask_before_open,
            )
        if action_name == "open_run_window":
            source = action_parameters.get("source", "")
            if not isinstance(source, str):
                return {
                    "ok": False,
                    "error": {"message": "source must be a string."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            self.event_queue.publish("OpenRunWindow", source=source)
            return {
                "ok": True,
                "source": source,
            }
        if action_name == "filter_senders_in_find_dialog":
            try:
                class_category_filters = self.validated_sender_filter_values(
                    action_parameters.get("class_category_filters"),
                    "class_category_filters",
                )
                class_name_filters = self.validated_sender_filter_values(
                    action_parameters.get("class_name_filters"),
                    "class_name_filters",
                )
                method_selector_filters = self.validated_sender_filter_values(
                    action_parameters.get("method_selector_filters"),
                    "method_selector_filters",
                )
                method_category_filters = self.validated_sender_filter_values(
                    action_parameters.get("method_category_filters"),
                    "method_category_filters",
                )
                include_extension_method_category_for_class_category = (
                    action_parameters.get(
                        "include_extension_method_category_for_class_category",
                        True,
                    )
                )
                if not isinstance(
                    include_extension_method_category_for_class_category,
                    bool,
                ):
                    raise DomainException(
                        "include_extension_method_category_for_class_category must be a boolean."
                    )
                reasoning_note = action_parameters.get("reasoning_note", "")
                if not isinstance(reasoning_note, str):
                    raise DomainException("reasoning_note must be a string.")
            except DomainException as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return self.filter_active_find_dialog_senders(
                class_category_filters=class_category_filters,
                class_name_filters=class_name_filters,
                method_selector_filters=method_selector_filters,
                method_category_filters=method_category_filters,
                include_extension_method_category_for_class_category=(
                    include_extension_method_category_for_class_category
                ),
                reasoning_note=reasoning_note,
            )
        if action_name == "query_current_view":
            return self.current_ide_view_state()
        if action_name == "query_find_dialog_state":
            return {'ok': True, **self.find_dialog_state_for_mcp()}
        if action_name == "narrow_senders_to_source_class_category":
            return self.narrow_find_dialog_senders_to_source_class_category()
        return {
            "ok": False,
            "error": {"message": f"Unknown IDE navigation action: {action_name}."},
        }

    def handle_mcp_ide_navigation_requested(
        self,
        action_name="",
        action_parameters=None,
        response_holder=None,
        completion_event=None,
    ):
        response = self.execute_mcp_ide_navigation_action(
            action_name,
            action_parameters,
        )
        if response_holder is not None:
            response_holder["response"] = response
        if completion_event is not None:
            completion_event.set()

    def perform_mcp_ide_navigation_action(self, action_name, action_parameters=None):
        if action_parameters is None:
            action_parameters = {}
        in_ui_thread = threading.get_ident() == self.event_queue.root_thread_ident
        if in_ui_thread:
            return self.execute_mcp_ide_navigation_action(
                action_name,
                action_parameters,
            )
        response_holder = {}
        completion_event = threading.Event()
        self.event_queue.publish(
            "McpIdeNavigationRequested",
            action_name=action_name,
            action_parameters=action_parameters,
            response_holder=response_holder,
            completion_event=completion_event,
        )
        completed = completion_event.wait(timeout=5.0)
        if not completed:
            return {
                "ok": False,
                "error": {"message": "IDE navigation request timed out."},
            }
        response = response_holder.get("response")
        if isinstance(response, dict):
            return response
        return {
            "ok": False,
            "error": {"message": "IDE navigation request returned no response."},
        }

    def synchronise_collaboration_state(self):
        if not self.winfo_exists():
            return
        self.process_pending_model_refresh_requests()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(**self.mcp_server_controller.status())
        self.refresh_collaboration_status()

    def destroy(self):
        self.mcp_server_controller.clear_subscribers(self)
        self.integrated_session_state.clear_subscribers(self)
        self.event_queue.clear_subscribers(self)
        self.mcp_server_controller.stop()
        self.integrated_session_state.detach_ide_gui()
        self.event_queue.close()
        super().destroy()

    def add_browser_tab(self):
        if self.browser_tab:
            self.browser_tab.destroy()
        self.browser_tab = BrowserWindow(self.notebook, self)
        self.notebook.add(self.browser_tab, text="Browser")

    def open_debugger(self, exception):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Debugging is disabled while MCP is running an operation.",
            )
            return
        self.open_debugger_with_optional_confirmation(
            exception,
            ask_before_open=False,
        )

    def open_debugger_with_optional_confirmation(
        self,
        exception,
        ask_before_open=False,
    ):
        if ask_before_open:
            response = messagebox.askquestion(
                "Open Debugger",
                "MCP requested opening a debugger for a failure. Open it now?",
                icon="warning",
                type="okcancel",
            )
            if response == "cancel":
                return False
        if self.debugger_tab:
            if self.debugger_tab.is_running:
                response = messagebox.askquestion(
                    "Debugger Already Open",
                    "A debugger is already open. Replace it with a new one?",
                    icon="warning",
                    type="okcancel",
                )
                if response == "cancel":
                    return False
            self.debugger_tab.destroy()

        self.add_debugger_tab(exception)
        self.select_debugger_tab()
        return True

    def open_debugger_for_mcp_exception(
        self,
        exception,
        ask_before_open=False,
    ):
        if not self.is_logged_in:
            return {
                "ok": False,
                "error": {"message": "No active GemStone session in the IDE."},
            }
        debugger_opened = self.open_debugger_with_optional_confirmation(
            exception,
            ask_before_open=ask_before_open,
        )
        if not debugger_opened:
            return {
                "ok": False,
                "cancelled": True,
                "error": {"message": "Debugger opening cancelled by user."},
            }
        return {
            "ok": True,
            "debugger_opened": True,
        }

    def add_debugger_tab(self, exception):
        self.debugger_tab = DebuggerWindow(
            self.notebook,
            self,
            self.gemstone_session_record,
            self.event_queue,
            exception,
        )
        self.notebook.add(self.debugger_tab, text="Debugger")

    def select_debugger_tab(self):
        self.notebook.select(self.debugger_tab)
        # if self.debugger_tab:
        #     self.notebook.select(self.debugger_tab)
        #     self.debugger_tab.top_frame.lift()
        #     self.debugger_tab.forget(self.debugger_tab.top_frame)
        #     self.debugger_tab.add(self.debugger_tab.top_frame)
        #     self.debugger_tab.event_generate('<Configure>')
        #     self.debugger_tab.update()

    def handle_find_selection(self, show_instance_side, class_name):
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")

    def handle_implementor_selection(
        self, method_symbol, class_name, show_instance_side
    ):
        self.gemstone_session_record.jump_to_method(
            class_name, show_instance_side, method_symbol
        )
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish("MethodSelected")

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        self.gemstone_session_record.jump_to_method(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish("MethodSelected")

    def open_run_tab(self):
        if self.run_tab is None or not self.run_tab.winfo_exists():
            self.run_tab = RunTab(self.notebook, self)
            self.notebook.add(self.run_tab, text='Run')
        self.run_tab.set_read_only(self.integrated_session_state.is_mcp_busy())
        self.notebook.select(self.run_tab)

    def run_code(self, source=''):
        self.open_run_tab()
        run_immediately = bool(source and source.strip())
        self.run_tab.present_source(source, run_immediately=run_immediately)

    def open_inspector_for_object(self, inspected_object):
        self.close_inspector_tab()
        self.inspector_tab = InspectorTab(
            self.notebook,
            self,
            an_object=inspected_object,
            graph_inspect_action=self.open_graph_inspector_for_object,
        )
        self.notebook.add(self.inspector_tab, text="Inspect")
        self.notebook.select(self.inspector_tab)

    def open_graph_inspector_for_object(self, inspected_object):
        tab_is_missing = self.graph_tab is None or not self.graph_tab.winfo_exists()
        if tab_is_missing:
            self.graph_tab = GraphTab(self.notebook, self)
            self.notebook.add(self.graph_tab, text="Graph")
        self.notebook.select(self.graph_tab)
        self.graph_tab.add_object(inspected_object)

    def browse_object_class(self, inspected_object):
        if inspected_object is None:
            return
        class_name = ""
        show_instance_side = True
        try:
            is_behavior = inspected_object.isBehavior().to_py
            if is_behavior:
                class_name = inspected_object.asString().to_py
                show_instance_side = False
            if not is_behavior:
                class_name = inspected_object.gemstone_class().asString().to_py
        except (GemstoneError, AttributeError):
            class_name = ""
        class_name = " ".join(class_name.split()) if isinstance(class_name, str) else ""
        if not class_name:
            return
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.notebook.select(self.browser_tab)
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")

    def add_method_for_class(self, class_name, show_instance_side=True):
        if not class_name:
            return None
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.notebook.select(self.browser_tab)
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")
        return self.browser_tab.methods_widget.add_method()

    def open_uml_for_class(self, class_name):
        if not class_name:
            return
        tab_is_missing = self.uml_tab is None or not self.uml_tab.winfo_exists()
        if tab_is_missing:
            self.uml_tab = UmlTab(self.notebook, self)
            self.notebook.add(self.uml_tab, text="UML")
        self.notebook.select(self.uml_tab)
        self.uml_tab.add_class(class_name)

    def pin_method_in_uml(self, class_name, show_instance_side, method_selector):
        if not class_name or not method_selector:
            return
        tab_is_missing = self.uml_tab is None or not self.uml_tab.winfo_exists()
        if tab_is_missing:
            self.uml_tab = UmlTab(self.notebook, self)
            self.notebook.add(self.uml_tab, text="UML")
        self.notebook.select(self.uml_tab)
        self.uml_tab.pin_method(
            class_name,
            show_instance_side,
            method_selector,
        )

    def close_inspector_tab(self):
        has_open_tab = (
            self.inspector_tab is not None and self.inspector_tab.winfo_exists()
        )
        if not has_open_tab:
            self.inspector_tab = None
            return
        try:
            self.notebook.forget(self.inspector_tab)
        except tk.TclError:
            pass
        self.inspector_tab.destroy()
        self.inspector_tab = None

    def close_graph_tab(self):
        tab_exists = self.graph_tab is not None and self.graph_tab.winfo_exists()
        if not tab_exists:
            self.graph_tab = None
            return
        try:
            self.notebook.forget(self.graph_tab)
        except tk.TclError:
            pass
        self.graph_tab.destroy()
        self.graph_tab = None

    def close_uml_tab(self):
        tab_exists = self.uml_tab is not None and self.uml_tab.winfo_exists()
        if not tab_exists:
            self.uml_tab = None
            return
        try:
            self.notebook.forget(self.uml_tab)
        except tk.TclError:
            pass
        self.uml_tab.destroy()
        self.uml_tab = None

    def open_find_dialog(
        self,
        search_type='class',
        search_query='',
        run_search=False,
        match_mode=None,
        reference_target=None,
        sender_source_class_name=None,
    ):
        return FindDialog(
            self,
            search_type=search_type,
            search_query=search_query,
            run_search=run_search,
            match_mode=match_mode,
            reference_target=reference_target,
            sender_source_class_name=sender_source_class_name,
        )

    def open_find_dialog_for_class(self, class_name):
        selected_class_name = (class_name or "").strip()
        if not selected_class_name:
            return None
        return self.open_find_dialog(
            search_type="reference",
            search_query=selected_class_name,
            run_search=True,
            match_mode="exact",
            reference_target="class",
        )

    def open_implementors_dialog(self, method_symbol=None):
        initial_selector = (method_symbol or "").strip()
        return self.open_find_dialog(
            search_type="method",
            search_query=initial_selector,
            run_search=bool(initial_selector),
            match_mode="exact",
        )

    def open_senders_dialog(self, method_symbol=None, source_class_name=None):
        initial_selector = (method_symbol or '').strip()
        return self.open_find_dialog(
            search_type='reference',
            search_query=initial_selector,
            run_search=bool(initial_selector),
            match_mode='exact',
            reference_target='method',
            sender_source_class_name=source_class_name,
        )

    def open_breakpoints_dialog(self):
        if self.gemstone_session_record is None:
            return
        BreakpointsDialog(self)


class RunTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.last_exception = None
        self.current_text_menu = None
        self.ui_context = UiContext('run-tab')

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(5, weight=1)

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.button_frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(
            self.button_frame,
            text="Run",
            command=self.run_code_from_editor,
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5))

        self.debug_button = ttk.Button(
            self.button_frame,
            text="Debug",
            command=self.open_debugger,
        )
        self.debug_button.grid(row=0, column=1, sticky="w", padx=(0, 5))

        self.close_button = ttk.Button(
            self.button_frame,
            text="Close",
            command=self.close_tab,
        )
        self.close_button.grid(row=0, column=3, sticky="e")

        self.source_label = ttk.Label(self, text="Source Code:")
        self.source_label.grid(row=1, column=0, sticky="w", padx=10, pady=(5, 0))

        self.source_editor_frame = ttk.Frame(self)
        self.source_editor_frame.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=10,
            pady=(0, 10),
        )
        self.source_editor_frame.rowconfigure(0, weight=1)
        self.source_editor_frame.columnconfigure(1, weight=1)
        self.source_text = tk.Text(
            self.source_editor_frame,
            height=10,
            undo=True,
        )
        self.editable_source = EditableText(self.source_text, self)
        self.source_line_number_column = CodeLineNumberColumn(
            self.source_editor_frame,
            self.source_text,
        )
        self.source_line_number_column.line_numbers_text.grid(
            row=0,
            column=0,
            sticky="ns",
        )
        self.source_text.grid(
            row=0,
            column=1,
            sticky="nsew",
        )

        self.status_bar = ttk.Frame(self)
        self.status_bar.grid(row=3, column=0, sticky="ew", padx=10)
        self.status_bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(self.status_bar, text="Ready")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.source_cursor_position_label = ttk.Label(
            self.status_bar,
            text="Ln 1, Col 1",
        )
        self.source_cursor_position_label.grid(
            row=0,
            column=1,
            sticky="e",
        )

        self.result_label = ttk.Label(self, text="Result:")
        self.result_label.grid(row=4, column=0, sticky="nw", padx=10, pady=(10, 0))

        self.result_text = tk.Text(self, height=7, state="disabled")
        self.editable_result = EditableText(self.result_text, self)
        self.result_text.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.configure_text_actions()
        self.source_cursor_position_indicator = TextCursorPositionIndicator(
            self.source_text,
            self.source_cursor_position_label,
        )
        self.application.event_queue.subscribe(
            "McpBusyStateChanged",
            self.handle_mcp_busy_state_changed,
            ui_context=self.ui_context,
        )
        self.set_read_only(self.is_read_only())

    def configure_text_actions(self):
        self.source_text.bind("<Control-a>", self.select_all_source_text)
        self.source_text.bind("<Control-A>", self.select_all_source_text)
        self.source_text.bind("<Control-c>", self.copy_source_selection)
        self.source_text.bind("<Control-C>", self.copy_source_selection)
        self.source_text.bind("<Control-v>", self.paste_into_source_text)
        self.source_text.bind("<Control-V>", self.paste_into_source_text)
        self.source_text.bind("<Control-z>", self.undo_source_text)
        self.source_text.bind("<Control-Z>", self.undo_source_text)
        self.source_text.bind(
            "<KeyPress>", self.replace_selected_source_text_before_typing, add="+"
        )
        self.source_text.bind("<Button-3>", self.open_source_text_menu)

        self.result_text.bind("<Control-a>", self.select_all_result_text)
        self.result_text.bind("<Control-A>", self.select_all_result_text)
        self.result_text.bind("<Control-c>", self.copy_result_selection)
        self.result_text.bind("<Control-C>", self.copy_result_selection)
        self.result_text.bind("<Button-3>", self.open_result_text_menu)

        self.source_text.bind("<Button-1>", self.close_text_menu, add="+")
        self.result_text.bind("<Button-1>", self.close_text_menu, add="+")

    def is_read_only(self):
        is_busy = self.application.integrated_session_state.is_mcp_busy()
        action_gate = getattr(self.application, 'action_gate', None)
        if action_gate is None:
            return is_busy
        return action_gate.read_only_for('run_editor_source', is_busy=is_busy)

    def set_read_only(self, read_only):
        source_text_state = tk.NORMAL
        run_button_state = tk.NORMAL
        debug_button_state = tk.NORMAL
        if read_only:
            source_text_state = tk.DISABLED
            run_button_state = tk.DISABLED
            debug_button_state = tk.DISABLED
        configure_widget_if_alive(self.source_text, state=source_text_state)
        configure_widget_if_alive(self.run_button, state=run_button_state)
        configure_widget_if_alive(self.debug_button, state=debug_button_state)

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name="",
        busy_lease_token=None,
    ):
        busy_coordinator = getattr(self.application, 'busy_coordinator', None)
        if busy_coordinator is not None:
            if not busy_coordinator.is_current_lease(busy_lease_token):
                return
        self.set_read_only(is_busy)

    def select_all_source_text(self, event=None):
        self.editable_source.select_all()
        return "break"

    def copy_source_selection(self, event=None):
        self.editable_source.copy_selection()
        return "break"

    def paste_into_source_text(self, event=None):
        self.editable_source.paste()
        return "break"

    def undo_source_text(self, event=None):
        self.editable_source.undo()
        return "break"

    def replace_selected_source_text_before_typing(self, event):
        self.editable_source.delete_selection_before_typing(event)

    def select_all_result_text(self, event=None):
        self.editable_result.select_all()
        return "break"

    def copy_result_selection(self, event=None):
        self.editable_result.copy_selection()
        return "break"

    def open_source_text_menu(self, event):
        self.source_text.mark_set(tk.INSERT, f"@{event.x},{event.y}")
        self.show_text_menu_for_widget(
            event,
            self.source_text,
            allow_paste=True,
            allow_undo=True,
            include_run_actions=True,
        )

    def open_result_text_menu(self, event):
        self.result_text.mark_set(tk.INSERT, f"@{event.x},{event.y}")
        self.show_text_menu_for_widget(
            event,
            self.result_text,
            allow_paste=False,
            allow_undo=False,
            include_run_actions=False,
        )

    def selected_source_text(self):
        start_index, end_index = self.editable_source.selected_range()
        if start_index is None:
            return ""
        return self.source_text.get(start_index, end_index)

    def editable_text_for_widget(self, text_widget):
        if text_widget is self.source_text:
            return self.editable_source
        if text_widget is self.result_text:
            return self.editable_result
        return EditableText(text_widget, self)

    def run_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text="MCP is busy. Run is disabled.")
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text="Select source text to run")
            return
        self.status_label.config(text="Running selection...")
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity("Running selected source...")
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def inspect_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text="MCP is busy. Inspect is disabled.")
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text="Select source text to inspect")
            return
        self.status_label.config(text="Inspecting selection...")
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity("Inspecting selected source...")
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
                self.application.open_inspector_for_object(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def graph_inspect_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text="MCP is busy. Graph inspect is disabled.")
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text="Select source text to graph inspect")
            return
        self.status_label.config(text="Graph inspecting selection...")
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity(
            "Graph inspecting selected source..."
        )
        try:
            try:
                result = self.gemstone_session_record.run_code(selected_text)
                self.on_run_complete(result)
                self.application.open_graph_inspector_for_object(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def show_text_menu_for_widget(
        self,
        event,
        text_widget,
        allow_paste,
        allow_undo,
        include_run_actions,
    ):
        if self.current_text_menu is not None:
            self.current_text_menu.unpost()

        self.current_text_menu = tk.Menu(self, tearoff=0)
        editable_text = self.editable_text_for_widget(text_widget)
        read_only = self.is_read_only()
        paste_command_state = tk.NORMAL
        undo_command_state = tk.NORMAL
        if read_only and text_widget is self.source_text:
            paste_command_state = tk.DISABLED
            undo_command_state = tk.DISABLED
        self.current_text_menu.add_command(
            label="Select All",
            command=editable_text.select_all,
        )
        self.current_text_menu.add_command(
            label="Copy",
            command=editable_text.copy_selection,
        )
        if allow_paste:
            self.current_text_menu.add_command(
                label="Paste",
                command=editable_text.paste,
                state=paste_command_state,
            )
        if allow_undo:
            self.current_text_menu.add_command(
                label="Undo",
                command=editable_text.undo,
                state=undo_command_state,
            )
        if include_run_actions:
            has_selection = bool(self.selected_source_text().strip())
            run_command_state = tk.NORMAL if has_selection else tk.DISABLED
            if self.is_read_only():
                run_command_state = tk.DISABLED
            self.current_text_menu.add_separator()
            self.current_text_menu.add_command(
                label="Run",
                command=self.run_selected_source_text,
                state=run_command_state,
            )
            self.current_text_menu.add_command(
                label="Inspect",
                command=self.inspect_selected_source_text,
                state=run_command_state,
            )
            self.current_text_menu.add_command(
                label="Graph Inspect",
                command=self.graph_inspect_selected_source_text,
                state=run_command_state,
            )
        add_close_command_to_popup_menu(self.current_text_menu)
        self.current_text_menu.bind(
            "<Escape>",
            lambda popup_event: self.close_text_menu(popup_event),
        )
        self.current_text_menu.post(event.x_root, event.y_root)

    def close_text_menu(self, event):
        if self.current_text_menu is not None:
            self.current_text_menu.unpost()
            self.current_text_menu = None

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record

    def present_source(self, source, run_immediately=False):
        source_text_was_disabled = self.source_text.cget("state") == tk.DISABLED
        if source_text_was_disabled:
            self.source_text.configure(state=tk.NORMAL)
        if source and source.strip():
            self.source_text.delete("1.0", tk.END)
            self.source_text.insert(tk.END, source)
            self.source_cursor_position_indicator.update_position()
        if source_text_was_disabled:
            self.source_text.configure(state=tk.DISABLED)
        if run_immediately:
            self.run_code_from_editor()

    def run_code_from_editor(self):
        if self.is_read_only():
            self.status_label.config(text="MCP is busy. Run is disabled.")
            return
        self.status_label.config(text="Running...")
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity("Running source...")
        try:
            try:
                code_to_run = self.source_text.get("1.0", "end-1c")
                result = self.gemstone_session_record.run_code(code_to_run)
                self.on_run_complete(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def on_run_complete(self, result):
        self.status_label.config(text="Completed successfully")
        self.clear_source_error_highlight()
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, result.asString().to_py)
        self.result_text.config(state="disabled")

    def on_run_error(self, exception):
        self.last_exception = exception
        error_text = str(exception)
        line_number, column_number = self.compile_error_location_for_exception(
            exception, error_text
        )
        self.show_source_error_highlight(line_number, column_number)
        self.show_error_in_result_panel(error_text, line_number, column_number)
        self.status_label.config(
            text=self.error_status_text(error_text, line_number, column_number)
        )

    def clear_source_error_highlight(self):
        self.source_text.tag_remove("compile_error_location", "1.0", tk.END)

    def source_text_line_count(self):
        return int(self.source_text.index("end-1c").split(".")[0])

    def source_text_line(self, line_number):
        if line_number < 1:
            return None
        line_count = self.source_text_line_count()
        if line_number > line_count:
            return None
        return self.source_text.get(f"{line_number}.0", f"{line_number}.end")

    def show_source_error_highlight(self, line_number, column_number):
        self.clear_source_error_highlight()
        if line_number is None:
            return

        source_line = self.source_text_line(line_number)
        if source_line is None:
            return

        start_index = f"{line_number}.0"
        end_index = f"{line_number}.end"
        if column_number is not None and column_number > 0:
            bounded_column_number = column_number
            if bounded_column_number > len(source_line) + 1:
                bounded_column_number = len(source_line) + 1
            start_index = f"{line_number}.{bounded_column_number - 1}"
            end_index = f"{line_number}.{bounded_column_number}"

        self.source_text.tag_configure(
            "compile_error_location",
            background="#ffe4e4",
            underline=True,
        )
        self.source_text.tag_add("compile_error_location", start_index, end_index)
        self.source_text.see(start_index)

    def show_error_in_result_panel(self, error_text, line_number, column_number):
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, error_text)
        if line_number is not None and column_number is not None:
            source_line = self.source_text_line(line_number)
            if source_line is None:
                source_line = ""
            caret_padding = ""
            if column_number > 1:
                caret_padding = " " * (column_number - 1)
            self.result_text.insert(
                tk.END, f"\nLine {line_number}, column {column_number}\n"
            )
            self.result_text.insert(tk.END, f"{source_line}\n")
            self.result_text.insert(tk.END, f"{caret_padding}^\n")
        self.result_text.config(state="disabled")

    def error_status_text(self, error_text, line_number, column_number):
        if line_number is not None and column_number is not None:
            return f"Error: {error_text} (line {line_number}, column {column_number})"
        return f"Error: {error_text}"

    def compile_error_location_for_exception(self, exception, error_text):
        line_number = None
        column_number = None

        line_number, column_number = (
            self.compile_error_location_from_structured_arguments(exception)
        )
        if line_number is None:
            line_number, column_number = self.compile_error_location_from_text(
                error_text
            )
            if line_number is None:
                message_text = self.compile_error_message_text(exception)
                line_number, column_number = self.compile_error_location_from_text(
                    message_text
                )

        return line_number, column_number

    def compile_error_message_text(self, exception):
        message_text = ""
        try:
            message_text = exception.message
        except (AttributeError, GemstoneError, TypeError):
            pass
        return message_text

    def compile_error_location_from_structured_arguments(self, exception):
        error_number = None
        try:
            error_number = exception.number
        except (AttributeError, GemstoneError, TypeError):
            pass
        if error_number != 1001:
            return None, None

        argument_values = self.compile_error_argument_values(exception)
        detail_rows = self.sequence_item(argument_values, 1)
        first_detail = self.sequence_item(detail_rows, 1)
        offset_value = self.sequence_item(first_detail, 2)
        source_text = self.sequence_item(argument_values, 2)

        offset_number = self.python_error_value(offset_value)
        source_value = self.python_error_value(source_text)
        if not isinstance(offset_number, int) or not isinstance(source_value, str):
            return None, None
        return self.line_and_column_for_offset(source_value, offset_number)

    def compile_error_argument_values(self, exception):
        argument_values = ()
        try:
            argument_values = exception.args
        except (AttributeError, GemstoneError, TypeError):
            pass
        return argument_values

    def compile_error_location_from_text(self, error_text):
        if not isinstance(error_text, str):
            return None, None

        line_number = None
        column_number = None

        full_match = re.search(
            r"line\s+(\d+)\s*[,;]?\s*column\s+(\d+)", error_text, re.IGNORECASE
        )
        if full_match:
            line_number = int(full_match.group(1))
            column_number = int(full_match.group(2))

        if line_number is None:
            inverted_match = re.search(
                r"column\s+(\d+)\s*[,;]?\s*line\s+(\d+)", error_text, re.IGNORECASE
            )
            if inverted_match:
                line_number = int(inverted_match.group(2))
                column_number = int(inverted_match.group(1))

        if line_number is None:
            line_only_match = re.search(r"line\s+(\d+)", error_text, re.IGNORECASE)
            if line_only_match:
                line_number = int(line_only_match.group(1))

        return line_number, column_number

    def sequence_item(self, sequence_value, one_based_index):
        if sequence_value is None:
            return None

        if isinstance(sequence_value, (list, tuple)):
            zero_based_index = one_based_index - 1
            if zero_based_index >= 0 and zero_based_index < len(sequence_value):
                return sequence_value[zero_based_index]
            return None

        size_value = self.python_error_value(
            self.message_send_result(sequence_value, "size")
        )
        if not isinstance(size_value, int):
            return None
        if one_based_index < 1 or one_based_index > size_value:
            return None
        return self.message_send_result(sequence_value, "at", one_based_index)

    def message_send_result(self, receiver, selector_name, *arguments):
        result = None
        if receiver is None:
            return result
        selector = getattr(receiver, selector_name, None)
        if selector is None:
            return result
        try:
            result = selector(*arguments)
        except (GemstoneError, TypeError, AttributeError):
            pass
        return result

    def python_error_value(self, candidate_value):
        if candidate_value is None:
            return None
        if isinstance(candidate_value, (int, str)):
            return candidate_value

        to_py_value = getattr(candidate_value, "to_py", None)
        if to_py_value is not None:
            if callable(to_py_value):
                try:
                    return to_py_value()
                except (GemstoneError, TypeError, AttributeError):
                    pass
            if not callable(to_py_value):
                return to_py_value

        as_string_result = self.message_send_result(candidate_value, "asString")
        as_string_value = getattr(as_string_result, "to_py", None)
        if callable(as_string_value):
            try:
                return as_string_value()
            except (GemstoneError, TypeError, AttributeError):
                return None
        if as_string_value is not None:
            return as_string_value
        return None

    def line_and_column_for_offset(self, source_text, one_based_offset):
        if one_based_offset < 1:
            return None, None

        bounded_offset = one_based_offset
        if bounded_offset > len(source_text):
            bounded_offset = len(source_text)
        if bounded_offset < 1:
            bounded_offset = 1

        source_before_error = source_text[: bounded_offset - 1]
        line_number = source_before_error.count("\n") + 1
        last_newline_index = source_before_error.rfind("\n")
        column_number = bounded_offset
        if last_newline_index >= 0:
            column_number = len(source_before_error) - last_newline_index
        return line_number, column_number

    def open_debugger(self):
        if self.is_read_only():
            self.status_label.config(text="MCP is busy. Debug is disabled.")
            return
        code_to_run = self.source_text.get("1.0", "end-1c")
        if not code_to_run.strip():
            self.status_label.config(text="No source to debug")
            return

        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity("Debugging source...")
        try:
            try:
                result = self.gemstone_session_record.run_code(code_to_run)
                self.on_run_complete(result)
                self.status_label.config(
                    text="Completed successfully; no debugger context",
                )
                return
            except (DomainException, GemstoneDomainException) as domain_exception:
                self.status_label.config(text=str(domain_exception))
                self.show_error_in_result_panel(str(domain_exception), None, None)
                return
            except GemstoneError as gemstone_exception:
                self.on_run_error(gemstone_exception)
                if self.is_compile_error(gemstone_exception):
                    return
                self.application.open_debugger(gemstone_exception)
        finally:
            self.application.end_foreground_activity()

    def is_compile_error(self, exception):
        error_number = None
        try:
            error_number = exception.number
        except (AttributeError, GemstoneError, TypeError):
            pass
        if error_number == 1001:
            return True

        error_text = str(exception).lower()
        return "compileerror" in error_text or "compile error" in error_text

    def close_tab(self):
        self.ui_context.invalidate()
        if self.application.run_tab is self:
            self.application.run_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()

    def destroy(self):
        self.ui_context.invalidate()
        self.application.event_queue.clear_subscribers(self)
        super().destroy()


class JsonResultDialog(tk.Toplevel):
    def __init__(self, parent, title, result_payload):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
        self.transient(parent)
        self.grab_set()
        self.focus_force()

        self.result_text = tk.Text(self, wrap="word")
        self.result_text.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        rendered_result = json.dumps(
            result_payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        self.result_text.insert("1.0", rendered_result)
        self.result_text.config(state="disabled")

        self.close_button = tk.Button(self, text="Close", command=self.destroy)
        self.close_button.pack(pady=10)


class FramedWidget(ttk.Frame):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, borderwidth=2, relief="sunken")
        self.browser_window = browser_window
        self.event_queue = event_queue
        self.grid(
            row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1
        )

    @property
    def gemstone_session_record(self):
        return self.browser_window.gemstone_session_record

    def destroy(self):
        super().destroy()
        self.event_queue.clear_subscribers(self)

    def show_test_result(self, result):
        if result["has_passed"]:
            messagebox.showinfo("Test Result", f"Passed ({result['run_count']} run)")
        else:
            lines = [
                f"Failures: {result['failure_count']}, Errors: {result['error_count']}"
            ]
            lines.extend(result["failures"])
            lines.extend(result["errors"])
            messagebox.showerror("Test Result", "\n".join(lines))


class InteractiveSelectionList(ttk.Frame):
    def __init__(self, parent, get_all_entries, get_selected_entry, set_selected_to):
        super().__init__(parent)

        self.get_all_entries = get_all_entries
        self.get_selected_entry = get_selected_entry
        self.set_selected_to = set_selected_to
        self.synchronizing_selection = False

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, columnspan=2, sticky="ew")

        # Packages listbox to show filtered packages with scrollbar
        self.selection_listbox = tk.Listbox(
            self, selectmode=tk.SINGLE, exportselection=False
        )
        self.selection_listbox.grid(row=1, column=0, sticky="nsew")

        self.scrollbar = tk.Scrollbar(
            self, orient="vertical", command=self.selection_listbox.yview
        )
        self.scrollbar.grid(row=1, column=1, sticky="ns")
        self.selection_listbox.config(yscrollcommand=self.scrollbar.set)

        # Configure weights for proper resizing
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Initial population of listbox
        self.repopulate()

        # Bind the listbox selection event
        self.selection_listbox.bind("<<ListboxSelect>>", self.handle_selection)

    def repopulate(self, origin=None):
        self.synchronizing_selection = True
        try:
            self.all_entries = self.get_all_entries()
            self.filter_var.set("")
            self.update_filter()

            selected_indices = self.selection_listbox.curselection()
            if selected_indices:
                index = selected_indices[0]
                if not self.selection_listbox.bbox(index):
                    self.selection_listbox.see(index)
        finally:
            self.synchronizing_selection = False

    def update_filter(self, *args):
        filter_text = self.filter_var.get().lower()
        self.selection_listbox.delete(0, tk.END)

        selected_entry = self.get_selected_entry()
        filtered_index = 0
        for entry in self.all_entries:
            if filter_text in entry.lower():
                self.selection_listbox.insert(tk.END, entry)
                if selected_entry and selected_entry == entry:
                    self.selection_listbox.selection_set(filtered_index)
                filtered_index += 1

    def handle_selection(self, event):
        if self.synchronizing_selection:
            return
        try:
            selected_listbox = event.widget
            selected_indices = selected_listbox.curselection()
            selected_index = selected_indices[-1]
            selected_entry = selected_listbox.get(selected_index)
            current_selected_entry = self.get_selected_entry()
            if selected_entry == current_selected_entry:
                return

            self.set_selected_to(selected_entry)
        except IndexError:
            pass


class PackageSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.selection_list = InteractiveSelectionList(
            self,
            self.get_all_groups,
            self.get_selected_group,
            self.select_group,
        )
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.browse_mode_var = tk.StringVar(
            value=self.gemstone_session_record.browse_mode
        )
        self.browse_mode_controls = ttk.Frame(self)
        self.browse_mode_controls.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(4, 0),
        )
        self.browse_mode_controls.columnconfigure(0, weight=1)
        self.browse_mode_controls.columnconfigure(1, weight=1)
        self.browse_mode_controls.columnconfigure(2, weight=1)
        self.dictionaries_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text="Dictionaries",
            variable=self.browse_mode_var,
            value="dictionaries",
            command=self.change_browse_mode,
        )
        self.categories_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text="Categories",
            variable=self.browse_mode_var,
            value="categories",
            command=self.change_browse_mode,
        )
        rowan_state = (
            tk.NORMAL if self.gemstone_session_record.rowan_installed else tk.DISABLED
        )
        self.rowan_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text="Rowan",
            variable=self.browse_mode_var,
            value="rowan",
            command=self.change_browse_mode,
            state=rowan_state,
        )
        self.dictionaries_radiobutton.grid(row=0, column=0, sticky="w")
        self.categories_radiobutton.grid(row=0, column=1, sticky="w")
        self.rowan_radiobutton.grid(row=0, column=2, sticky="e")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Initial population of listbox
        self.repopulate()

        # Subscribe to event_queue for any "Aborted" event
        self.event_queue.subscribe("PackagesChanged", self.repopulate)
        self.event_queue.subscribe("Committed", self.repopulate)
        self.event_queue.subscribe("Aborted", self.repopulate)
        self.event_queue.subscribe("SelectedClassChanged", self.repopulate)
        self.event_queue.subscribe("BrowseModeChanged", self.handle_browse_mode_changed)

    def change_browse_mode(self):
        selected_mode = self.browse_mode_var.get()
        try:
            self.gemstone_session_record.select_browse_mode(selected_mode)
        except DomainException as error:
            messagebox.showerror("Browse Mode", str(error))
            self.browse_mode_var.set(self.gemstone_session_record.browse_mode)
            return
        self.selection_list.repopulate()
        self.event_queue.publish("BrowseModeChanged", origin=self)
        # AI: Retain legacy event name for compatibility with dependent widgets.
        self.event_queue.publish("SelectedPackageChanged", origin=self)
        self.event_queue.publish("SelectedClassChanged", origin=self)
        self.event_queue.publish("SelectedCategoryChanged", origin=self)
        self.event_queue.publish("MethodSelected", origin=self)

    def handle_browse_mode_changed(self, origin=None):
        if origin is self:
            return
        rowan_state = (
            tk.NORMAL if self.gemstone_session_record.rowan_installed else tk.DISABLED
        )
        self.rowan_radiobutton.config(state=rowan_state)
        if (
            self.gemstone_session_record.browse_mode == "rowan"
            and not self.gemstone_session_record.rowan_installed
        ):
            self.gemstone_session_record.select_browse_mode("dictionaries")
        self.browse_mode_var.set(self.gemstone_session_record.browse_mode)
        self.selection_list.repopulate()

    def select_group(self, selected_group):
        self.gemstone_session_record.select_class_category(selected_group)
        self.event_queue.publish("SelectedPackageChanged", origin=self)

    def get_all_groups(self):
        return list(self.browser_window.gemstone_session_record.class_categories)

    def get_selected_group(self):
        return self.gemstone_session_record.selected_class_category()

    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()


class ClassSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.class_content_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.class_content_paned.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.class_definition_sash_fraction = 0.65

        self.class_selection_frame = ttk.Frame(self.class_content_paned)
        self.class_selection_frame.rowconfigure(0, weight=1)
        self.class_selection_frame.columnconfigure(0, weight=1)
        self.class_content_paned.add(self.class_selection_frame, weight=3)

        self.classes_notebook = ttk.Notebook(self.class_selection_frame)
        self.classes_notebook.grid(row=0, column=0, sticky="nsew")

        self.rowconfigure(0, weight=1, minsize=180)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.selection_list = InteractiveSelectionList(
            self.classes_notebook,
            self.get_all_classes,
            self.get_selected_class,
            self.select_class,
        )
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.classes_notebook.add(self.selection_list, text="List")

        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.hierarchy_frame.grid(row=0, column=0, sticky="nsew")
        self.classes_notebook.add(self.hierarchy_frame, text="Hierarchy")
        self.hierarchy_tree = ttk.Treeview(
            self.hierarchy_frame,
            columns=("class_category",),
            show="tree headings",
        )
        self.hierarchy_tree.grid(row=0, column=0, sticky="nsew")
        self.hierarchy_frame.rowconfigure(0, weight=1)
        self.hierarchy_frame.columnconfigure(0, weight=1)
        self.hierarchy_tree.heading("#0", text="Class")
        self.hierarchy_tree.heading("class_category", text="Class Category")
        self.hierarchy_tree.column("#0", width=260, anchor="w")
        self.hierarchy_tree.column("class_category", width=180, anchor="w")
        self.hierarchy_item_by_class_name = {}
        self.synchronizing_hierarchy_selection = False
        self.hierarchy_tree.bind("<<TreeviewSelect>>", self.repopulate_categories)
        self.hierarchy_tree.bind("<Button-3>", self.show_hierarchy_context_menu)
        self.classes_notebook.bind(
            "<<NotebookTabChanged>>",
            self.handle_classes_notebook_changed,
        )

        self.selection_var = tk.StringVar(
            value=(
                "instance"
                if self.gemstone_session_record.show_instance_side
                else "class"
            )
        )
        self.syncing_side_selection = False
        self.selection_var.trace_add(
            "write", lambda name, index, operation: self.switch_side()
        )
        self.class_controls_frame = ttk.Frame(self)
        self.class_controls_frame.grid(
            column=0,
            row=1,
            columnspan=2,
            sticky="ew",
            pady=(4, 0),
        )
        self.class_controls_frame.columnconfigure(0, weight=0)
        self.class_controls_frame.columnconfigure(1, weight=0)
        self.class_controls_frame.columnconfigure(2, weight=1)
        self.class_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text="Class",
            variable=self.selection_var,
            value="class",
        )
        self.instance_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text="Instance",
            variable=self.selection_var,
            value="instance",
        )
        self.instance_radiobutton.grid(column=0, row=0, sticky="w")
        self.class_radiobutton.grid(column=1, row=0, sticky="w")
        self.show_class_definition_var = tk.BooleanVar(value=False)
        self.show_class_definition_checkbox = tk.Checkbutton(
            self.class_controls_frame,
            text="Definition",
            variable=self.show_class_definition_var,
            command=self.toggle_class_definition,
        )
        self.show_class_definition_checkbox.grid(
            column=2,
            row=0,
            sticky="e",
        )
        self.class_definition_frame = ttk.Frame(self.class_content_paned)
        self.class_definition_frame.rowconfigure(0, weight=1)
        self.class_definition_frame.columnconfigure(1, weight=1)
        self.class_definition_text = tk.Text(
            self.class_definition_frame,
            wrap="word",
            width=1,
            height=8,
        )
        self.class_definition_line_number_column = CodeLineNumberColumn(
            self.class_definition_frame,
            self.class_definition_text,
        )
        self.class_definition_line_number_column.line_numbers_text.grid(
            column=0,
            row=0,
            sticky="ns",
        )
        self.class_definition_text.grid(
            column=1,
            row=0,
            sticky="nsew",
        )
        self.class_definition_cursor_position_label = ttk.Label(
            self.class_definition_frame,
            text="Ln 1, Col 1",
        )
        self.class_definition_cursor_position_label.grid(
            column=1,
            row=1,
            sticky="e",
            pady=(2, 0),
        )
        self.class_definition_cursor_position_indicator = TextCursorPositionIndicator(
            self.class_definition_text,
            self.class_definition_cursor_position_label,
        )
        self.class_definition_text.config(state="disabled")

        self.event_queue.subscribe("SelectedPackageChanged", self.repopulate)
        self.event_queue.subscribe("PackagesChanged", self.repopulate)
        self.event_queue.subscribe("ClassesChanged", self.repopulate)
        self.event_queue.subscribe("Committed", self.repopulate)
        self.event_queue.subscribe("Aborted", self.repopulate)
        self.event_queue.subscribe("SelectedClassChanged", self.repopulate)

        self.selection_list.selection_listbox.bind("<Button-3>", self.show_context_menu)
        self.current_context_menu = None
        self.context_menu_class_name = None

    def switch_side(self):
        if self.syncing_side_selection:
            return
        self.gemstone_session_record.select_instance_side(self.show_instance_side)
        self.event_queue.publish("SelectedClassChanged")

    @property
    def show_instance_side(self):
        return self.selection_var.get() == "instance"

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                selected_index = widget.curselection()[0]
                selected_class = widget.get(selected_index)
                self.select_class(
                    selected_class,
                    selection_source="list",
                )
                return
            if isinstance(widget, ttk.Treeview):
                if self.synchronizing_hierarchy_selection:
                    return
                selected_item_id = widget.selection()[0]
                selected_class = widget.item(selected_item_id, "text")
                class_values = widget.item(selected_item_id, "values")
                class_category = class_values[0] if class_values else ""
                current_class = self.gemstone_session_record.selected_class
                current_package = self.gemstone_session_record.selected_package
                selected_package = class_category or current_package
                if (
                    selected_class == current_class
                    and selected_package == current_package
                ):
                    return
                self.select_class(
                    selected_class,
                    selection_source="hierarchy",
                    class_category=class_category,
                )
        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            expected_side = (
                "instance"
                if self.gemstone_session_record.show_instance_side
                else "class"
            )
            if self.selection_var.get() != expected_side:
                self.syncing_side_selection = True
                self.selection_var.set(expected_side)
                self.syncing_side_selection = False
            self.selection_list.repopulate()
            if self.selected_tab_is_hierarchy():
                self.refresh_hierarchy_tree()
            self.refresh_class_definition()

    def selected_tab_is_hierarchy(self):
        selected_tab = self.classes_notebook.select()
        return selected_tab == str(self.hierarchy_frame)

    def handle_classes_notebook_changed(self, event):
        if event.widget.select() == str(self.hierarchy_frame):
            self.refresh_hierarchy_tree()

    def refresh_hierarchy_tree(self):
        self.synchronizing_hierarchy_selection = True
        try:
            self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
            self.hierarchy_item_by_class_name = {}
            class_names = self.get_all_classes()
            if not class_names:
                return
            class_definition_by_class_name = self.class_definition_map_for_classes(
                class_names,
            )
            superclass_by_class_name = {
                class_name: class_definition.get("superclass_name")
                for class_name, class_definition in class_definition_by_class_name.items()
            }
            children_by_parent_name = {}
            for class_name, superclass_name in superclass_by_class_name.items():
                parent_name = superclass_name
                if superclass_name not in superclass_by_class_name:
                    parent_name = None
                if parent_name not in children_by_parent_name:
                    children_by_parent_name[parent_name] = []
                children_by_parent_name[parent_name].append(class_name)
            for child_names in children_by_parent_name.values():
                child_names.sort()
            self.add_hierarchy_children(
                "",
                None,
                children_by_parent_name,
                class_definition_by_class_name,
            )
            self.reveal_selected_class_in_hierarchy()
        finally:
            self.synchronizing_hierarchy_selection = False

    def class_definition_map_for_classes(self, class_names):
        class_definition_by_class_name = {}
        classes_to_query = list(class_names)
        while classes_to_query:
            class_name = classes_to_query.pop()
            if class_name not in class_definition_by_class_name:
                class_definition = {
                    "class_name": class_name,
                    "superclass_name": None,
                    "package_name": "",
                }
                try:
                    fetched_class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        class_name,
                    )
                    class_definition.update(fetched_class_definition)
                except GemstoneDomainException:
                    pass
                superclass_name = class_definition.get("superclass_name")
                class_definition_by_class_name[class_name] = class_definition
                if (
                    superclass_name is not None
                    and superclass_name not in class_definition_by_class_name
                ):
                    classes_to_query.append(superclass_name)
        return class_definition_by_class_name

    def add_hierarchy_children(
        self,
        parent_item_id,
        parent_class_name,
        children_by_parent_name,
        class_definition_by_class_name,
    ):
        child_class_names = children_by_parent_name.get(parent_class_name, [])
        for child_class_name in child_class_names:
            class_definition = class_definition_by_class_name.get(
                child_class_name,
                {},
            )
            class_category = class_definition.get("package_name") or ""
            child_item_id = self.hierarchy_tree.insert(
                parent_item_id,
                "end",
                text=child_class_name,
                values=(class_category,),
            )
            self.hierarchy_item_by_class_name[child_class_name] = child_item_id
            self.add_hierarchy_children(
                child_item_id,
                child_class_name,
                children_by_parent_name,
                class_definition_by_class_name,
            )

    def reveal_selected_class_in_hierarchy(self):
        selected_class_name = self.gemstone_session_record.selected_class
        if not selected_class_name:
            return
        selected_item_id = self.hierarchy_item_by_class_name.get(selected_class_name)
        if selected_item_id is None:
            return
        parent_item_id = self.hierarchy_tree.parent(selected_item_id)
        while parent_item_id:
            self.hierarchy_tree.item(parent_item_id, open=True)
            parent_item_id = self.hierarchy_tree.parent(parent_item_id)
        self.hierarchy_tree.item(selected_item_id, open=True)
        self.hierarchy_tree.selection_set(selected_item_id)
        self.hierarchy_tree.focus(selected_item_id)
        self.hierarchy_tree.see(selected_item_id)

    def get_all_classes(self):
        selected_category = self.gemstone_session_record.selected_class_category()
        return list(
            self.browser_window.gemstone_session_record.get_classes_in_category(
                selected_category
            )
        )

    def get_selected_class(self):
        return self.gemstone_session_record.selected_class

    def select_class(
        self,
        selected_class,
        selection_source="list",
        class_category="",
    ):
        selected_package = self.gemstone_session_record.selected_package
        if (
            selection_source == "hierarchy"
            and self.gemstone_session_record.browse_mode == "categories"
        ):
            selected_package = class_category
            if not selected_package:
                try:
                    class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        selected_class,
                    )
                except (GemstoneDomainException, GemstoneError):
                    class_definition = {}
                selected_package = (
                    class_definition.get("package_name") or selected_package
                )
            if selected_package:
                self.gemstone_session_record.select_package(selected_package)
                self.selection_list.repopulate()
        self.gemstone_session_record.select_class(selected_class)
        if selection_source == "hierarchy":
            self.gemstone_session_record.select_method_category("all")
        self.refresh_class_definition()
        self.event_queue.publish("SelectedClassChanged", origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        selected_class_name = self.class_name_from_list_context_event(event)
        self.context_menu_class_name = selected_class_name
        has_selection = selected_class_name is not None
        if self.current_context_menu:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label="Add Class",
            command=self.add_class,
            state=write_command_state,
        )
        menu.add_command(
            label="Delete Class",
            command=self.delete_class,
            state=delete_command_state,
        )
        menu.add_command(
            label="References",
            command=self.find_references_for_selected_class,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_command(
            label="Add to UML",
            command=self.add_selected_class_to_uml,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_command(
            label="Run All Tests",
            command=self.run_all_tests,
            state=run_command_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def class_name_from_list_context_event(self, event):
        listbox = self.selection_list.selection_listbox
        if listbox.size() <= 0:
            return None
        selected_index = listbox.nearest(event.y)
        listbox.selection_clear(0, "end")
        listbox.selection_set(selected_index)
        return listbox.get(selected_index)

    def class_name_from_hierarchy_context_event(self, event):
        tree = self.hierarchy_tree
        selected_item_id = tree.identify_row(event.y)
        selected_items = tree.selection()
        if selected_item_id:
            clicked_item_is_selected = selected_item_id in selected_items
            if not clicked_item_is_selected:
                tree.selection_set(selected_item_id)
                selected_items = tree.selection()
            tree.focus(selected_item_id)
        if not selected_item_id and selected_items:
            selected_item_id = selected_items[0]
            tree.focus(selected_item_id)
        if not selected_item_id:
            return None
        return tree.item(selected_item_id, "text")

    def selected_class_names_from_hierarchy(self):
        selected_class_names = []
        for item_id in self.hierarchy_tree.selection():
            class_name = self.hierarchy_tree.item(item_id, "text")
            if class_name:
                selected_class_names.append(class_name)
        return selected_class_names

    def find_references_for_selected_class(self):
        class_name = self.context_menu_class_name
        if class_name is None:
            class_name = self.gemstone_session_record.selected_class
        if not class_name:
            return
        self.browser_window.application.open_find_dialog_for_class(class_name)

    def add_selected_class_to_uml(self):
        class_name = self.context_menu_class_name
        if class_name is None:
            class_name = self.gemstone_session_record.selected_class
        if not class_name:
            return
        self.browser_window.application.open_uml_for_class(class_name)

    def add_selected_hierarchy_classes_to_uml(self):
        selected_class_names = self.selected_class_names_from_hierarchy()
        if not selected_class_names:
            self.add_selected_class_to_uml()
            return
        for class_name in selected_class_names:
            self.browser_window.application.open_uml_for_class(class_name)

    def show_hierarchy_context_menu(self, event):
        selected_class_name = self.class_name_from_hierarchy_context_event(event)
        self.context_menu_class_name = selected_class_name
        selected_class_names = self.selected_class_names_from_hierarchy()
        has_selection = len(selected_class_names) > 0
        if self.current_context_menu:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="References",
            command=self.find_references_for_selected_class,
            state=tk.NORMAL if selected_class_name is not None else tk.DISABLED,
        )
        menu.add_command(
            label="Add to UML",
            command=self.add_selected_class_to_uml,
            state=tk.NORMAL if selected_class_name is not None else tk.DISABLED,
        )
        menu.add_command(
            label="Add Selected to UML",
            command=self.add_selected_hierarchy_classes_to_uml,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def add_class(self):
        selected_category = self.gemstone_session_record.selected_class_category()
        if not selected_category:
            category_label = "dictionary"
            if self.gemstone_session_record.browse_mode == "categories":
                category_label = "category"
            if self.gemstone_session_record.browse_mode == "rowan":
                category_label = "Rowan package"
            messagebox.showerror(
                "Add Class",
                "Select a %s first." % category_label,
            )
            return
        class_name = simpledialog.askstring("Add Class", "Class name:")
        if class_name is None:
            return
        class_name = class_name.strip()
        if not class_name:
            return
        superclass_name = simpledialog.askstring(
            "Add Class",
            "Superclass name:",
            initialvalue="Object",
        )
        if superclass_name is None:
            return
        superclass_name = superclass_name.strip()
        if not superclass_name:
            return
        try:
            self.gemstone_session_record.create_class(
                class_name=class_name,
                superclass_name=superclass_name,
            )
            self.gemstone_session_record.select_class(class_name)
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish("SelectedClassChanged", origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Add Class", str(error))

    def delete_class(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        selected_category = self.gemstone_session_record.selected_class_category()
        selected_category_label = "dictionary"
        if self.gemstone_session_record.browse_mode == "categories":
            selected_category_label = "category"
        if self.gemstone_session_record.browse_mode == "rowan":
            selected_category_label = "Rowan package"
        should_delete = messagebox.askyesno(
            "Delete Class",
            ("Delete class %s from %s %s? " "This cannot be undone.")
            % (
                class_name,
                selected_category_label,
                selected_category or "UserGlobals",
            ),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_class(
                class_name,
            )
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish("SelectedClassChanged", origin=self)
            self.event_queue.publish("SelectedCategoryChanged", origin=self)
            self.event_queue.publish("MethodSelected", origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Delete Class", str(error))

    def class_definition_is_visible(self):
        return str(self.class_definition_frame) in self.class_content_paned.panes()

    def remember_class_definition_sash_position(self):
        if not self.class_definition_is_visible():
            return
        paned_height = self.class_content_paned.winfo_height()
        if paned_height <= 0:
            return
        sash_position = self.class_content_paned.sashpos(0)
        sash_fraction = sash_position / paned_height
        self.class_definition_sash_fraction = max(0.2, min(0.8, sash_fraction))

    def restore_class_definition_sash_position(self):
        if not self.class_definition_is_visible():
            return
        paned_height = self.class_content_paned.winfo_height()
        if paned_height <= 0:
            return
        minimum_pane_height = 120
        desired_sash_position = int(paned_height * self.class_definition_sash_fraction)
        maximum_sash_position = paned_height - minimum_pane_height
        if maximum_sash_position < minimum_pane_height:
            desired_sash_position = paned_height // 2
        else:
            desired_sash_position = max(
                minimum_pane_height,
                min(maximum_sash_position, desired_sash_position),
            )
        self.class_content_paned.sashpos(0, desired_sash_position)

    def ensure_class_definition_is_visible(self):
        if not self.class_definition_is_visible():
            return
        self.class_content_paned.update_idletasks()
        self.restore_class_definition_sash_position()
        self.after(20, self.restore_class_definition_sash_position)

    def toggle_class_definition(self):
        if self.show_class_definition_var.get():
            if not self.class_definition_is_visible():
                self.class_content_paned.add(self.class_definition_frame, weight=2)
            self.ensure_class_definition_is_visible()
            self.refresh_class_definition()
            return
        self.class_definition_text.config(state="normal")
        self.class_definition_text.delete("1.0", tk.END)
        self.class_definition_text.config(state="disabled")
        self.remember_class_definition_sash_position()
        if self.class_definition_is_visible():
            self.class_content_paned.forget(self.class_definition_frame)

    def formatted_class_definition(self, class_definition):
        class_name = class_definition.get("class_name") or ""
        superclass_name = class_definition.get("superclass_name") or "Object"
        package_name = class_definition.get("package_name") or ""
        inst_var_names = class_definition.get("inst_var_names") or []
        class_var_names = class_definition.get("class_var_names") or []
        class_inst_var_names = class_definition.get("class_inst_var_names") or []
        pool_dictionary_names = class_definition.get("pool_dictionary_names") or []
        return (
            f"{superclass_name} subclass: '{class_name}'\n"
            f"    instVarNames: {self.symbol_array_literal(inst_var_names)}\n"
            f"    classVars: {self.symbol_array_literal(class_var_names)}\n"
            f"    classInstVars: {self.symbol_array_literal(class_inst_var_names)}\n"
            f"    poolDictionaries: {self.symbol_array_literal(pool_dictionary_names)}\n"
            f"    inDictionary: {package_name}"
        )

    def symbol_array_literal(self, symbol_names):
        if not symbol_names:
            return "#()"
        return "#(%s)" % " ".join(symbol_names)

    def refresh_class_definition(self):
        if not self.show_class_definition_var.get():
            return
        class_definition_text = ""
        selected_class = self.gemstone_session_record.selected_class
        if selected_class:
            try:
                class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                    selected_class,
                )
                class_definition_text = self.formatted_class_definition(
                    class_definition,
                )
            except (GemstoneDomainException, GemstoneError):
                class_definition_text = ""
        self.class_definition_text.config(state="normal")
        self.class_definition_text.delete("1.0", tk.END)
        self.class_definition_text.insert("1.0", class_definition_text)
        self.class_definition_text.config(state="disabled")
        self.class_definition_cursor_position_indicator.update_position()

    def run_all_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            "Running tests in %s..." % class_name
        )
        try:
            try:
                result = self.gemstone_session_record.run_gemstone_tests(class_name)
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror("Run All Tests", str(domain_exception))
            except GemstoneError as e:
                self.browser_window.application.open_debugger(e)
        finally:
            self.browser_window.application.end_foreground_activity()


class CategorySelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.selection_list = InteractiveSelectionList(
            self,
            self.get_all_categories,
            self.get_selected_category,
            self.select_category,
        )
        self.selection_list.grid(row=0, column=0, sticky="nsew")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.event_queue.subscribe("SelectedClassChanged", self.repopulate)
        self.event_queue.subscribe("SelectedPackageChanged", self.repopulate)
        self.event_queue.subscribe("ClassesChanged", self.repopulate)
        self.event_queue.subscribe("MethodsChanged", self.repopulate)
        self.event_queue.subscribe("Committed", self.repopulate)
        self.event_queue.subscribe("Aborted", self.repopulate)
        self.selection_list.selection_listbox.bind("<Button-3>", self.show_context_menu)

    def repopulate(self, origin=None):
        if origin is self:
            return
        self.selection_list.repopulate()

    def get_all_categories(self):
        if self.gemstone_session_record.selected_class:
            return ["all"] + list(
                self.gemstone_session_record.get_categories_in_class(
                    self.gemstone_session_record.selected_class,
                    self.gemstone_session_record.show_instance_side,
                )
            )
        return []

    def get_selected_category(self):
        return self.gemstone_session_record.selected_method_category

    def select_category(self, selected_category):
        self.gemstone_session_record.select_method_category(selected_category)
        self.event_queue.publish("SelectedCategoryChanged", origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            selected_index = listbox.nearest(event.y)
            listbox.selection_clear(0, "end")
            listbox.selection_set(selected_index)
        menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.DISABLED if read_only else tk.NORMAL
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label="Add Category",
            command=self.add_category,
            state=write_command_state,
        )
        menu.add_command(
            label="Delete Category",
            command=self.delete_category,
            state=delete_command_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def add_category(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            messagebox.showerror("Add Category", "Select a class first.")
            return
        category_name = simpledialog.askstring("Add Category", "Category name:")
        if category_name is None:
            return
        category_name = category_name.strip()
        if not category_name:
            return
        try:
            self.gemstone_session_record.create_method_category(
                selected_class,
                self.gemstone_session_record.show_instance_side,
                category_name,
            )
            self.gemstone_session_record.select_method_category(category_name)
            self.selection_list.repopulate()
            self.event_queue.publish("SelectedCategoryChanged", origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Add Category", str(error))

    def delete_category(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            return
        listbox = self.selection_list.selection_listbox
        selected_indices = listbox.curselection()
        if not selected_indices:
            return
        selected_category = listbox.get(selected_indices[0])
        if selected_category == "all":
            messagebox.showerror(
                "Delete Category", "The all category cannot be deleted."
            )
            return
        should_delete = messagebox.askyesno(
            "Delete Category",
            ("Delete category %s from class %s? " "This cannot be undone.")
            % (selected_category, selected_class),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_method_category(
                selected_class,
                self.gemstone_session_record.show_instance_side,
                selected_category,
            )
            remaining_categories = list(
                self.gemstone_session_record.get_categories_in_class(
                    selected_class,
                    self.gemstone_session_record.show_instance_side,
                )
            )
            if remaining_categories:
                self.gemstone_session_record.select_method_category(
                    remaining_categories[0]
                )
            else:
                self.gemstone_session_record.select_method_category(None)
                self.gemstone_session_record.select_method_symbol(None)
            self.selection_list.repopulate()
            self.event_queue.publish("SelectedCategoryChanged", origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Delete Category", str(error))


class MethodSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.method_content_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.method_content_paned.grid(row=0, column=0, sticky="nsew")
        self.method_hierarchy_sash_fraction = 0.65

        self.method_selection_frame = ttk.Frame(self.method_content_paned)
        self.method_selection_frame.rowconfigure(0, weight=1)
        self.method_selection_frame.columnconfigure(0, weight=1)
        self.method_content_paned.add(self.method_selection_frame, weight=3)

        self.selection_list = InteractiveSelectionList(
            self.method_selection_frame,
            self.get_all_methods,
            self.get_selected_method,
            self.select_method,
        )
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.controls_frame = ttk.Frame(self)
        self.controls_frame.grid(row=1, column=0, sticky="ew")
        self.controls_frame.columnconfigure(0, weight=1)
        self.show_method_hierarchy_var = tk.BooleanVar(value=False)
        self.show_method_hierarchy_checkbox = tk.Checkbutton(
            self.controls_frame,
            text="Inheritance",
            variable=self.show_method_hierarchy_var,
            command=self.toggle_method_hierarchy,
        )
        self.show_method_hierarchy_checkbox.grid(row=0, column=0, sticky="w")
        self.method_hierarchy_frame = ttk.Frame(self.method_content_paned)
        self.method_hierarchy_frame.rowconfigure(0, weight=1)
        self.method_hierarchy_frame.columnconfigure(0, weight=1)
        self.method_hierarchy_tree = ttk.Treeview(
            self.method_hierarchy_frame,
            show="tree",
        )
        self.method_hierarchy_tree.heading("#0", text="Class")
        self.method_hierarchy_tree.column("#0", width=240, anchor="w")
        self.method_hierarchy_tree.grid(row=0, column=0, sticky="nsew")
        self.method_hierarchy_tree.bind(
            "<<TreeviewSelect>>",
            self.method_hierarchy_selected,
        )
        self.syncing_method_hierarchy_selection = False

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe("SelectedPackageChanged", self.repopulate)
        self.event_queue.subscribe("SelectedClassChanged", self.repopulate)
        self.event_queue.subscribe("SelectedCategoryChanged", self.repopulate)
        self.event_queue.subscribe("ClassesChanged", self.repopulate)
        self.event_queue.subscribe("MethodsChanged", self.repopulate)
        self.event_queue.subscribe("Committed", self.repopulate)
        self.event_queue.subscribe("MethodSelected", self.repopulate)
        self.event_queue.subscribe("Aborted", self.repopulate)

        self.selection_list.selection_listbox.bind("<Button-3>", self.show_context_menu)

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_method = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_symbol(selected_method)
            self.selection_changed = False
            self.event_queue.publish("MethodSelected", origin=self)

        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()

    def get_all_methods(self):
        return self.gemstone_session_record.get_current_methods()

    def get_selected_method(self):
        return self.gemstone_session_record.selected_method_symbol

    def select_method(self, selected_method):
        self.gemstone_session_record.select_method_symbol(selected_method)
        if self.show_method_hierarchy_var.get():
            self.refresh_method_hierarchy()
        self.event_queue.publish("MethodSelected", origin=self)

    def new_method_argument_names(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        if selector_tokens:
            return [f"argument{index + 1}" for index in range(len(selector_tokens))]
        if self.is_binary_selector(method_selector):
            return ["argument1"]
        return []

    def keyword_selector_tokens(self, method_selector):
        if ":" not in method_selector:
            return []
        selector_parts = method_selector.split(":")
        if not selector_parts or selector_parts[-1] != "":
            return []
        keyword_tokens = []
        for selector_part in selector_parts[:-1]:
            is_valid_selector_part = re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]*",
                selector_part,
            )
            if is_valid_selector_part is None:
                return []
            keyword_tokens.append(f"{selector_part}:")
        return keyword_tokens

    def is_binary_selector(self, method_selector):
        if not method_selector:
            return False
        binary_characters = "+-*/\\~<>=@%,|&?!"
        return all(character in binary_characters for character in method_selector)

    def new_method_header(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        argument_names = self.new_method_argument_names(method_selector)
        if selector_tokens:
            return " ".join(
                [
                    f"{selector_tokens[token_index]} {argument_names[token_index]}"
                    for token_index in range(len(selector_tokens))
                ]
            )
        if self.is_binary_selector(method_selector):
            return f"{method_selector} {argument_names[0]}"
        return method_selector

    def new_method_source(self, method_selector):
        method_header = self.new_method_header(method_selector)
        return f"{method_header}\n    ^self"

    def add_method(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            messagebox.showerror("Add Method", "Select a class first.")
            return None
        method_selector = simpledialog.askstring("Add Method", "Method selector:")
        if method_selector is None:
            return None
        method_selector = method_selector.strip()
        if not method_selector:
            return None
        method_category = "as yet unclassified"
        show_instance_side = self.gemstone_session_record.show_instance_side
        try:
            method_source = self.new_method_source(method_selector)
            self.gemstone_session_record.create_method(
                selected_class,
                show_instance_side,
                method_source,
                method_category=method_category,
            )
            self.gemstone_session_record.select_method_category(method_category)
            self.gemstone_session_record.select_method_symbol(method_selector)
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()
            self.event_queue.publish("SelectedClassChanged", origin=self)
            self.event_queue.publish("SelectedCategoryChanged", origin=self)
            self.event_queue.publish("MethodSelected", origin=self)
            return method_selector
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Add Method", str(error))
        return None

    def toggle_method_hierarchy(self):
        if self.show_method_hierarchy_var.get():
            if not self.method_hierarchy_is_visible():
                self.method_content_paned.add(self.method_hierarchy_frame, weight=2)
            self.ensure_method_hierarchy_is_visible()
            self.refresh_method_hierarchy()
            return
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        self.remember_method_hierarchy_sash_position()
        if self.method_hierarchy_is_visible():
            self.method_content_paned.forget(self.method_hierarchy_frame)

    def method_hierarchy_is_visible(self):
        return str(self.method_hierarchy_frame) in self.method_content_paned.panes()

    def remember_method_hierarchy_sash_position(self):
        if not self.method_hierarchy_is_visible():
            return
        paned_height = self.method_content_paned.winfo_height()
        if paned_height <= 0:
            return
        sash_position = self.method_content_paned.sashpos(0)
        sash_fraction = sash_position / paned_height
        self.method_hierarchy_sash_fraction = max(0.2, min(0.8, sash_fraction))

    def restore_method_hierarchy_sash_position(self):
        if not self.method_hierarchy_is_visible():
            return
        paned_height = self.method_content_paned.winfo_height()
        if paned_height <= 0:
            return
        minimum_pane_height = 120
        desired_sash_position = int(paned_height * self.method_hierarchy_sash_fraction)
        maximum_sash_position = paned_height - minimum_pane_height
        if maximum_sash_position < minimum_pane_height:
            desired_sash_position = paned_height // 2
        else:
            desired_sash_position = max(
                minimum_pane_height,
                min(maximum_sash_position, desired_sash_position),
            )
        self.method_content_paned.sashpos(0, desired_sash_position)

    def ensure_method_hierarchy_is_visible(self):
        if not self.method_hierarchy_is_visible():
            return
        self.method_content_paned.update_idletasks()
        self.restore_method_hierarchy_sash_position()
        self.after(20, self.restore_method_hierarchy_sash_position)

    def refresh_method_hierarchy(self):
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        inheritance_entries = self.method_inheritance_entries()
        parent_item_id = ""
        selected_item_id = None
        selected_class = self.gemstone_session_record.selected_class
        for inheritance_entry in inheritance_entries:
            item_id = self.method_hierarchy_tree.insert(
                parent_item_id,
                "end",
                text=inheritance_entry["class_name"],
            )
            if inheritance_entry["class_name"] == selected_class:
                selected_item_id = item_id
            parent_item_id = item_id
        if selected_item_id is None and parent_item_id:
            selected_item_id = parent_item_id
        if selected_item_id:
            self.syncing_method_hierarchy_selection = True
            self.method_hierarchy_tree.selection_set(selected_item_id)
            self.method_hierarchy_tree.focus(selected_item_id)
            self.method_hierarchy_tree.see(selected_item_id)
            self.syncing_method_hierarchy_selection = False

    def method_inheritance_entries(self):
        selected_class = self.gemstone_session_record.selected_class
        method_selector = self.gemstone_session_record.selected_method_symbol
        show_instance_side = self.gemstone_session_record.show_instance_side
        if not selected_class or not method_selector:
            return []
        superclass_chain = self.superclass_chain_for_method_inheritance(
            selected_class,
        )
        inheritance_entries = []
        for class_name in superclass_chain:
            compiled_method = self.gemstone_session_record.get_method(
                class_name,
                show_instance_side,
                method_selector,
            )
            if compiled_method is not None:
                inheritance_entries.append(
                    {
                        "class_name": class_name,
                        "method_selector": method_selector,
                    },
                )
        return inheritance_entries

    def superclass_chain_for_method_inheritance(self, class_name):
        superclass_chain = []
        current_class_name = class_name
        while current_class_name:
            superclass_chain.append(current_class_name)
            try:
                class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                    current_class_name,
                )
            except GemstoneDomainException:
                class_definition = {}
            current_class_name = class_definition.get("superclass_name")
        superclass_chain.reverse()
        return superclass_chain

    def method_hierarchy_selected(self, event):
        if self.syncing_method_hierarchy_selection:
            return
        try:
            selected_item_id = event.widget.selection()[0]
        except IndexError:
            return
        selected_class = event.widget.item(selected_item_id, "text")
        selected_method = self.gemstone_session_record.selected_method_symbol
        if not selected_class or not selected_method:
            return
        show_instance_side = self.gemstone_session_record.show_instance_side
        if self.gemstone_session_record.gemstone_session is not None:
            self.gemstone_session_record.jump_to_method(
                selected_class,
                show_instance_side,
                selected_method,
            )
        else:
            selected_method_category = self.gemstone_session_record.gemstone_browser_session.get_method_category(
                selected_class,
                selected_method,
                show_instance_side,
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(selected_class)
            self.gemstone_session_record.select_method_category(
                selected_method_category,
            )
            self.gemstone_session_record.select_method_symbol(selected_method)
        self.event_queue.publish("SelectedClassChanged", origin=self)
        self.event_queue.publish("SelectedCategoryChanged", origin=self)
        self.event_queue.publish("MethodSelected", origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            idx = listbox.nearest(event.y)
            listbox.selection_clear(0, "end")
            listbox.selection_set(idx)
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label="Add Method",
            command=self.add_method,
            state=write_command_state,
        )
        menu.add_command(
            label="Delete Method",
            command=self.delete_method,
            state=delete_command_state,
        )
        menu.add_command(
            label="Show in UML",
            command=self.show_method_in_uml,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_separator()
        menu.add_command(
            label="Run Test",
            command=self.run_test,
            state=run_command_state,
        )
        menu.add_command(
            label="Debug Test",
            command=self.debug_test,
            state=run_command_state,
        )
        covering_tests_state = run_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label="Covering Tests",
            command=self.open_covering_tests,
            state=covering_tests_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def show_method_in_uml(self):
        class_name = self.gemstone_session_record.selected_class
        method_selector = self.gemstone_session_record.selected_method_symbol
        if not class_name or not method_selector:
            return
        self.browser_window.application.pin_method_in_uml(
            class_name,
            self.gemstone_session_record.show_instance_side,
            method_selector,
        )

    def delete_method(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        show_instance_side = self.gemstone_session_record.show_instance_side
        method_selector = listbox.get(selection[0])
        should_delete = messagebox.askyesno(
            "Delete Method",
            ("Delete %s>>%s? This cannot be undone.") % (class_name, method_selector),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_method(
                class_name,
                show_instance_side,
                method_selector,
            )
            self.selection_list.repopulate()
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()
            self.event_queue.publish("SelectedCategoryChanged", origin=self)
            self.event_queue.publish("MethodSelected", origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Delete Method", str(error))

    def run_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            "Running test %s>>%s..." % (class_name, method_selector)
        )
        try:
            try:
                result = self.gemstone_session_record.run_test_method(
                    class_name,
                    method_selector,
                )
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror("Run Test", str(domain_exception))
            except GemstoneError as e:
                self.browser_window.application.open_debugger(e)
        finally:
            self.browser_window.application.end_foreground_activity()

    def debug_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            "Debugging test %s>>%s..." % (class_name, method_selector)
        )
        try:
            try:
                self.gemstone_session_record.debug_test_method(
                    class_name,
                    method_selector,
                )
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror("Debug Test", str(domain_exception))
            except GemstoneError as e:
                self.browser_window.application.open_debugger(e)
        finally:
            self.browser_window.application.end_foreground_activity()

    def open_covering_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        method_selector = listbox.get(selection[0])
        CoveringTestsBrowseDialog(
            self.browser_window,
            method_selector,
        )


class NavigationHistory:
    def __init__(self, maximum_entries=200):
        self.maximum_entries = maximum_entries
        self.entries = []
        self.current_index = -1

    def current_entry(self):
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    def record(self, entry):
        if entry is None:
            return
        if self.current_entry() == entry:
            return
        if self.current_index < len(self.entries) - 1:
            self.entries = self.entries[: self.current_index + 1]
        self.entries.append(entry)
        overflow = len(self.entries) - self.maximum_entries
        if overflow > 0:
            self.entries = self.entries[overflow:]
        self.current_index = len(self.entries) - 1

    def can_go_back(self):
        return self.current_index > 0

    def can_go_forward(self):
        return 0 <= self.current_index < len(self.entries) - 1

    def go_back(self):
        if not self.can_go_back():
            return None
        self.current_index -= 1
        return self.current_entry()

    def go_forward(self):
        if not self.can_go_forward():
            return None
        self.current_index += 1
        return self.current_entry()

    def jump_to(self, history_index):
        if history_index < 0:
            return None
        if history_index >= len(self.entries):
            return None
        self.current_index = history_index
        return self.current_entry()

    def entries_with_current_marker(self):
        entry_details = []
        for index, entry in enumerate(self.entries):
            entry_details.append(
                {
                    "history_index": index,
                    "entry": entry,
                    "is_current": index == self.current_index,
                },
            )
        return entry_details


class DeduplicatedTabRegistry:
    def __init__(self, notebook):
        self.notebook = notebook
        self.tabs_by_key = {}
        self.key_by_tab_id = {}
        self.label_by_key = {}

    def register_tab(self, tab_key, tab_widget, tab_label=""):
        tab_id = str(tab_widget)
        self.tabs_by_key[tab_key] = tab_widget
        self.key_by_tab_id[tab_id] = tab_key
        self.label_by_key[tab_key] = tab_label

    def remove_key(self, tab_key):
        if tab_key not in self.tabs_by_key:
            return
        tab_widget = self.tabs_by_key.pop(tab_key)
        tab_id = str(tab_widget)
        if tab_id in self.key_by_tab_id:
            del self.key_by_tab_id[tab_id]
        if tab_key in self.label_by_key:
            del self.label_by_key[tab_key]

    def select_key(self, tab_key):
        if tab_key not in self.tabs_by_key:
            return False
        self.notebook.select(self.tabs_by_key[tab_key])
        return True

    def selected_key(self):
        selected_tab_id = self.notebook.select()
        if selected_tab_id in self.key_by_tab_id:
            return self.key_by_tab_id[selected_tab_id]
        return None

    def label_for_key(self, tab_key):
        if tab_key in self.label_by_key:
            return self.label_by_key[tab_key]
        return ""


class MethodEditor(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.current_menu = None
        self.method_navigation_history = NavigationHistory()
        self.history_choice_indices = []
        self.ui_context = UiContext('method-editor')

        self.navigation_bar = ttk.Frame(self)
        self.navigation_bar.grid(row=0, column=0, sticky="ew")
        self.navigation_bar.columnconfigure(0, weight=1)

        self.label_bar = tk.Label(self.navigation_bar, text="Method Editor", anchor="w")
        self.label_bar.grid(row=0, column=0, sticky="ew")

        self.back_button = ttk.Button(
            self.navigation_bar,
            text="Back",
            command=self.go_to_previous_method,
        )
        self.back_button.grid(row=0, column=1, padx=(6, 0))

        self.forward_button = ttk.Button(
            self.navigation_bar,
            text="Forward",
            command=self.go_to_next_method,
        )
        self.forward_button.grid(row=0, column=2, padx=(4, 0))

        self.history_combobox = ttk.Combobox(
            self.navigation_bar,
            state="readonly",
            width=44,
        )
        self.history_combobox.grid(row=0, column=3, padx=(6, 0), sticky="e")
        self.history_combobox.bind(
            "<<ComboboxSelected>>",
            self.jump_to_selected_history_entry,
        )

        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.editor_notebook.bind("<Motion>", self.on_tab_motion)
        self.editor_notebook.bind("<Leave>", self.on_tab_leave)

        self.open_tab_registry = DeduplicatedTabRegistry(self.editor_notebook)
        self.open_tabs = self.open_tab_registry.tabs_by_key

        self.event_queue.subscribe("MethodSelected", self.open_method)
        self.event_queue.subscribe(
            "MethodSelected",
            self.record_method_navigation,
        )
        self.event_queue.subscribe("MethodsChanged", self.repopulate)
        self.event_queue.subscribe("Committed", self.repopulate)
        self.event_queue.subscribe("Aborted", self.repopulate)
        self.event_queue.subscribe(
            "McpBusyStateChanged",
            self.handle_mcp_busy_state_changed,
            ui_context=self.ui_context,
        )
        self.refresh_navigation_controls()
        self.set_read_only(
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )

    def repopulate(self, origin=None):
        for key, tab in dict(self.open_tabs).items():
            tab.repopulate()

    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)

    def open_tab_menu_handler(self, event):
        return None

    def close_tab(self, tab):
        if tab.tab_key not in self.open_tabs:
            return
        self.editor_notebook.forget(self.open_tabs[tab.tab_key])
        self.open_tab_registry.remove_key(tab.tab_key)

    def current_method_context(self):
        selected_class = self.gemstone_session_record.selected_class
        selected_method_symbol = self.gemstone_session_record.selected_method_symbol
        if selected_class is None:
            return None
        if selected_method_symbol is None:
            return None
        return (
            selected_class,
            self.gemstone_session_record.show_instance_side,
            selected_method_symbol,
        )

    def method_context_label(self, method_context):
        class_name, show_instance_side, method_symbol = method_context
        if show_instance_side:
            return f"{class_name}>>{method_symbol}"
        return f"{class_name} class>>{method_symbol}"

    def record_method_navigation(self, origin=None):
        self.method_navigation_history.record(self.current_method_context())
        self.refresh_navigation_controls()

    def refresh_navigation_controls(self):
        back_button_state = (
            tk.NORMAL if self.method_navigation_history.can_go_back() else tk.DISABLED
        )
        self.back_button.configure(state=back_button_state)

        forward_button_state = (
            tk.NORMAL
            if self.method_navigation_history.can_go_forward()
            else tk.DISABLED
        )
        self.forward_button.configure(state=forward_button_state)

        history_entries = self.method_navigation_history.entries_with_current_marker()
        self.history_choice_indices = []
        history_labels = []
        for history_entry in reversed(history_entries):
            history_index = history_entry["history_index"]
            method_context = history_entry["entry"]
            history_labels.append(self.method_context_label(method_context))
            self.history_choice_indices.append(history_index)
        self.history_combobox["values"] = history_labels

        if len(history_labels) > 0:
            current_history_index = self.method_navigation_history.current_index
            selected_index = len(history_labels) - current_history_index - 1
            self.history_combobox.current(selected_index)
        if len(history_labels) == 0:
            self.history_combobox.set("")

    def jump_to_method_context(self, method_context):
        if method_context is None:
            self.refresh_navigation_controls()
            return
        if method_context == self.current_method_context():
            self.refresh_navigation_controls()
            return
        class_name, show_instance_side, method_symbol = method_context
        self.browser_window.application.handle_sender_selection(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.refresh_navigation_controls()

    def go_to_previous_method(self):
        method_context = self.method_navigation_history.go_back()
        self.jump_to_method_context(method_context)

    def go_to_next_method(self):
        method_context = self.method_navigation_history.go_forward()
        self.jump_to_method_context(method_context)

    def jump_to_selected_history_entry(self, event):
        combobox_index = self.history_combobox.current()
        if combobox_index < 0:
            return
        if combobox_index >= len(self.history_choice_indices):
            return
        history_index = self.history_choice_indices[combobox_index]
        method_context = self.method_navigation_history.jump_to(history_index)
        self.jump_to_method_context(method_context)

    def open_method(self, origin=None):
        method_context = self.current_method_context()
        if method_context is None:
            return
        selected_method_symbol = method_context[2]

        if self.open_tab_registry.select_key(method_context):
            return

        new_tab = EditorTab(
            self.editor_notebook,
            self.browser_window,
            self,
            method_context,
        )
        self.editor_notebook.add(new_tab, text=selected_method_symbol)
        self.editor_notebook.select(new_tab)
        self.open_tab_registry.register_tab(
            method_context,
            new_tab,
            selected_method_symbol,
        )
        new_tab.code_panel.set_read_only(
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )

    def set_read_only(self, read_only):
        for open_tab in self.open_tabs.values():
            open_tab.code_panel.set_read_only(read_only)

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name="",
        busy_lease_token=None,
    ):
        busy_coordinator = getattr(
            self.browser_window.application,
            'busy_coordinator',
            None,
        )
        if busy_coordinator is not None:
            if not busy_coordinator.is_current_lease(busy_lease_token):
                return
        self.set_read_only(is_busy)

    def destroy(self):
        self.ui_context.invalidate()
        super().destroy()

    def on_tab_motion(self, event):
        try:
            tab_index = self.editor_notebook.index("@%d,%d" % (event.x, event.y))
            if tab_index is not None:
                tab_key = self.get_tab(tab_index).tab_key
                if tab_key[1]:
                    text = f"{tab_key[0]}>>{tab_key[2]}"
                else:
                    text = f"{tab_key[0]} class>>{tab_key[2]}"
                self.label_bar.config(text=text)
        except tk.TclError:
            pass

    def on_tab_leave(self, event):
        self.label_bar.config(text="Method Editor")


class CodePanel(tk.Frame):
    def __init__(self, parent, application, tab_key=None):
        super().__init__(parent)

        self.application = application
        self.tab_key = tab_key

        self.text_editor = tk.Text(self, tabs=("4",), wrap="none", undo=True)
        self.editable_text = EditableText(self.text_editor, self)

        self.scrollbar_y = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.text_editor.yview,
        )
        self.scrollbar_x = tk.Scrollbar(
            self,
            orient="horizontal",
            command=self.text_editor.xview,
        )
        self.line_number_column = CodeLineNumberColumn(
            self,
            self.text_editor,
            external_yscrollcommand=self.scrollbar_y.set,
        )
        self.text_editor.configure(
            xscrollcommand=self.scrollbar_x.set,
        )

        self.line_number_column.line_numbers_text.grid(
            row=0,
            column=0,
            sticky="ns",
        )
        self.text_editor.grid(row=0, column=1, sticky="nsew")
        self.scrollbar_y.grid(row=0, column=2, sticky="ns")
        self.scrollbar_x.grid(row=1, column=1, sticky="ew")
        self.cursor_position_label = ttk.Label(self, text="Ln 1, Col 1")
        self.cursor_position_label.grid(
            row=2,
            column=1,
            sticky="e",
            pady=(2, 0),
        )
        self.cursor_position_indicator = TextCursorPositionIndicator(
            self.text_editor,
            self.cursor_position_label,
        )

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.text_editor.tag_configure("smalltalk_keyword", foreground="blue")
        self.text_editor.tag_configure("smalltalk_comment", foreground="green")
        self.text_editor.tag_configure("smalltalk_string", foreground="orange")
        self.text_editor.tag_configure("highlight", background="darkgrey")
        self.text_editor.tag_configure(
            "breakpoint_marker",
            background="#ff6b6b",
            foreground="black",
        )

        self.text_editor.bind("<Control-a>", self.select_all_text_editor)
        self.text_editor.bind("<Control-A>", self.select_all_text_editor)
        self.text_editor.bind("<Control-c>", self.copy_text_editor_selection)
        self.text_editor.bind("<Control-C>", self.copy_text_editor_selection)
        self.text_editor.bind("<Control-v>", self.paste_into_text_editor)
        self.text_editor.bind("<Control-V>", self.paste_into_text_editor)
        self.text_editor.bind("<Control-z>", self.undo_text_editor)
        self.text_editor.bind("<Control-Z>", self.undo_text_editor)
        self.text_editor.bind(
            "<KeyPress>", self.replace_selected_text_editor_before_typing, add="+"
        )
        self.text_editor.bind("<KeyRelease>", self.on_key_release)
        self.text_editor.bind("<Button-3>", self.open_text_menu)

        self.current_context_menu = None
        self.text_editor.bind("<Button-1>", self.close_context_menu, add="+")

    def is_read_only(self):
        is_busy = self.application.integrated_session_state.is_mcp_busy()
        action_gate = getattr(self.application, 'action_gate', None)
        if action_gate is None:
            return is_busy
        return action_gate.read_only_for('method_editor_source', is_busy=is_busy)

    def set_read_only(self, read_only):
        text_state = tk.NORMAL
        if read_only:
            text_state = tk.DISABLED
        configure_widget_if_alive(self.text_editor, state=text_state)

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record

    def method_context(self):
        if self.tab_key is not None:
            return self.tab_key
        gemstone_session_record = self.gemstone_session_record
        if gemstone_session_record is None:
            return None
        class_name = gemstone_session_record.selected_class
        method_selector = gemstone_session_record.selected_method_symbol
        show_instance_side = gemstone_session_record.show_instance_side
        has_complete_context = class_name is not None and method_selector is not None
        if not has_complete_context:
            return None
        return (class_name, show_instance_side, method_selector)

    def selected_text(self):
        try:
            return self.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ""

    def select_all_text_editor(self, event=None):
        self.editable_text.select_all()
        return "break"

    def copy_text_editor_selection(self, event=None):
        self.editable_text.copy_selection()
        return "break"

    def paste_into_text_editor(self, event=None):
        self.editable_text.paste()
        return "break"

    def undo_text_editor(self, event=None):
        self.editable_text.undo()
        return "break"

    def replace_selected_text_editor_before_typing(self, event):
        self.editable_text.delete_selection_before_typing(event)

    def selector_token(self, token_text):
        candidate = (token_text or "").strip()
        if not candidate:
            return None
        is_identifier_selector = re.fullmatch(
            r"[A-Za-z_]\w*(?::[A-Za-z_]\w*)*:?",
            candidate,
        )
        if is_identifier_selector:
            return candidate
        keyword_tokens = re.findall(
            r"[A-Za-z_]\w*:",
            candidate,
        )
        if keyword_tokens:
            return "".join(keyword_tokens)
        is_binary_selector = re.fullmatch(r"[-+*/\\~<>=@%,|&?!]+", candidate)
        if is_binary_selector:
            return candidate
        return None

    def cursor_offset(self):
        cursor_index = self.text_editor.index(tk.INSERT)
        characters = self.text_editor.count("1.0", cursor_index, "chars")
        if not characters:
            return 0
        return int(characters[0])

    def selector_entry_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            return None
        class_name, show_instance_side, method_selector = method_context
        sends_payload = self.gemstone_session_record.method_sends(
            class_name,
            method_selector,
            show_instance_side,
        )
        cursor_offset = self.cursor_offset()
        for send_entry in sends_payload.get("sends", []):
            starts_before_or_at_cursor = send_entry["start_offset"] <= cursor_offset
            ends_after_cursor = cursor_offset < send_entry["end_offset"]
            if starts_before_or_at_cursor and ends_after_cursor:
                return send_entry
        return None

    def word_under_cursor(self):
        line, column = self.text_editor.index(tk.INSERT).split(".")
        line_text = self.text_editor.get(f"{line}.0", f"{line}.end")
        cursor_column = int(column)
        token_matches = [
            match
            for match in re.finditer(
                r"[-+*/\\~<>=@%,|&?!]+|[A-Za-z_]\w*:?",
                line_text,
            )
            if match.start() <= cursor_column <= match.end()
        ]
        token_match = token_matches[0] if token_matches else None
        if token_match is None:
            return ""
        return token_match.group(0)

    def selector_for_navigation(self):
        selected_text = self.selected_text()
        selector_from_selection = self.selector_token(selected_text)
        if selector_from_selection is not None:
            return selector_from_selection
        send_entry = self.selector_entry_at_cursor()
        if send_entry is not None:
            return send_entry["selector"]
        selector_from_cursor = self.selector_token(self.word_under_cursor())
        if selector_from_cursor is not None:
            return selector_from_cursor
        method_context = self.method_context()
        if method_context is None:
            return None
        return method_context[2]

    def open_text_menu(self, event):
        self.text_editor.mark_set(tk.INSERT, f"@{event.x},{event.y}")
        if self.current_context_menu:
            self.current_context_menu.unpost()

        self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = self.is_read_only()
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        self.current_context_menu.add_command(
            label="Select All",
            command=self.select_all_text_editor,
        )
        self.current_context_menu.add_command(
            label="Copy",
            command=self.copy_text_editor_selection,
        )
        self.current_context_menu.add_command(
            label="Paste",
            command=self.paste_into_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Undo",
            command=self.undo_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_separator()
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is not None:
            self.current_context_menu.add_command(
                label="Jump to Class",
                command=self.jump_to_method_context,
            )
            self.current_context_menu.add_separator()
            self.current_context_menu.add_command(
                label="Save",
                command=self.save_current_tab,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label="Close",
                command=self.close_current_tab,
            )
            self.current_context_menu.add_command(
                label="Set Breakpoint Here",
                command=self.set_breakpoint_at_cursor,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label="Clear Breakpoint Here",
                command=self.clear_breakpoint_at_cursor,
                state=write_command_state,
            )
            self.current_context_menu.add_separator()
        selected_text = self.selected_text()
        if selected_text:
            self.current_context_menu.add_command(
                label="Run",
                command=lambda: self.run_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_command(
                label="Inspect",
                command=lambda: self.inspect_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_command(
                label="Graph Inspect",
                command=lambda: self.graph_inspect_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label="Implementors",
            command=self.open_implementors_from_source,
        )
        self.current_context_menu.add_command(
            label="Senders",
            command=self.open_senders_from_source,
        )
        self.current_context_menu.add_command(
            label="References",
            command=self.find_references_from_source,
        )
        self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label="Apply Rename Method",
            command=self.apply_method_rename,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Apply Move Method",
            command=self.apply_method_move,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Apply Add Parameter",
            command=self.apply_method_add_parameter,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Apply Remove Parameter",
            command=self.apply_method_remove_parameter,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Apply Extract Method",
            command=self.apply_method_extract,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label="Apply Inline Method",
            command=self.apply_method_inline,
            state=write_command_state,
        )
        add_close_command_to_popup_menu(self.current_context_menu)
        self.current_context_menu.bind(
            "<Escape>",
            lambda popup_event: close_popup_menu(self.current_context_menu),
        )
        self.current_context_menu.post(event.x_root, event.y_root)

    def active_editor_tab(self):
        parent_widget = self.master
        has_editor_tab_shape = (
            parent_widget is not None
            and hasattr(parent_widget, "save")
            and hasattr(parent_widget, "method_editor")
        )
        if not has_editor_tab_shape:
            return None
        return parent_widget

    def is_debugger_source_panel(self):
        debugger_tab = getattr(self.application, "debugger_tab", None)
        if debugger_tab is None:
            return False
        return debugger_tab.code_panel is self

    def save_current_tab(self):
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is None:
            return
        active_editor_tab.save()

    def close_current_tab(self):
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is None:
            return
        active_editor_tab.method_editor.close_tab(active_editor_tab)

    def source_offset_at_cursor(self):
        return self.cursor_offset() + 1

    def set_breakpoint_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before setting a breakpoint.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        requested_source_offset = self.source_offset_at_cursor()
        try:
            breakpoint_entry = self.gemstone_session_record.set_breakpoint(
                class_name,
                show_instance_side,
                method_selector,
                requested_source_offset,
            )
            current_source = self.text_editor.get("1.0", "end-1c")
            self.apply_breakpoint_markers(current_source)
            resolved_source_offset = breakpoint_entry["source_offset"]
            if resolved_source_offset != requested_source_offset:
                requested_line, requested_column = (
                    self.line_and_column_for_source_offset(requested_source_offset)
                )
                resolved_line, resolved_column = self.line_and_column_for_source_offset(
                    resolved_source_offset
                )
                messagebox.showinfo(
                    "Breakpoint Set",
                    (
                        "Requested line %s, column %s. "
                        "Breakpoint set at nearest executable location "
                        "line %s, column %s."
                    )
                    % (
                        requested_line,
                        requested_column,
                        resolved_line,
                        resolved_column,
                    ),
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Set Breakpoint", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Set Breakpoint", str(error))

    def clear_breakpoint_at_cursor(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before clearing a breakpoint.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        source_offset = self.source_offset_at_cursor()
        try:
            self.gemstone_session_record.clear_breakpoint_at(
                class_name,
                show_instance_side,
                method_selector,
                source_offset,
            )
            current_source = self.text_editor.get("1.0", "end-1c")
            self.apply_breakpoint_markers(current_source)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Clear Breakpoint", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Clear Breakpoint", str(error))

    def jump_to_method_context(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        self.application.handle_sender_selection(
            class_name,
            show_instance_side,
            method_selector,
        )

    def close_context_menu(self, event):
        if self.current_context_menu:
            self.current_context_menu.unpost()
            self.current_context_menu = None

    def run_selected_text(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                "Read Only",
                "MCP is busy. Run is disabled until MCP finishes.",
            )
            return
        self.application.run_code(selected_text)

    def inspect_selected_text(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                "Read Only",
                "MCP is busy. Inspect is disabled until MCP finishes.",
            )
            return
        if self.is_debugger_source_panel():
            debugger_tab = self.application.debugger_tab
            debugger_tab.inspect_selected_source_expression(selected_text)
            return
        try:
            inspected_object = self.gemstone_session_record.run_code(selected_text)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Inspect Selection", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Inspect Selection", str(gemstone_exception))
            return
        if hasattr(self.application, "open_inspector_for_object"):
            self.application.open_inspector_for_object(inspected_object)

    def graph_inspect_selected_text(self, selected_text):
        if self.is_read_only():
            messagebox.showwarning(
                "Read Only",
                "MCP is busy. Graph inspect is disabled until MCP finishes.",
            )
            return
        if self.is_debugger_source_panel():
            debugger_tab = self.application.debugger_tab
            debugger_tab.graph_inspect_selected_source_expression(selected_text)
            return
        try:
            inspected_object = self.gemstone_session_record.run_code(selected_text)
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Graph Inspect Selection", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Graph Inspect Selection", str(gemstone_exception))
            return
        if hasattr(self.application, "open_graph_inspector_for_object"):
            self.application.open_graph_inspector_for_object(inspected_object)

    def open_implementors_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                "No Selector",
                "Could not determine a selector at the current cursor position.",
            )
            return
        self.application.open_implementors_dialog(method_symbol=selector)

    def open_senders_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
            )
            return
        context = self.method_context()
        source_class_name = context[0] if context is not None else None
        self.application.open_senders_dialog(method_symbol=selector, source_class_name=source_class_name)

    def class_name_for_reference_lookup(self):
        selected_text = self.selected_text()
        candidate = selected_text if selected_text else self.word_under_cursor()
        candidate = (candidate or "").strip()
        if not candidate:
            return None
        class_name_match = re.search(r"[A-Za-z_]\w*", candidate)
        if class_name_match is None:
            return None
        return class_name_match.group(0)

    def find_references_from_source(self):
        class_name = self.class_name_for_reference_lookup()
        if class_name is None:
            messagebox.showwarning(
                "No Class Name",
                "Could not determine a class name at the current cursor position.",
            )
            return
        self.application.open_find_dialog_for_class(class_name)

    def run_method_analysis(self, analysis_function, title):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        try:
            analysis_result = analysis_function(
                class_name,
                method_selector,
                show_instance_side,
            )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(self.application, title, analysis_result)

    def show_method_sends(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_sends,
            "Method Sends",
        )

    def show_method_structure(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_structure_summary,
            "Method Structure",
        )

    def show_method_control_flow(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_control_flow_summary,
            "Method Control Flow",
        )

    def show_method_ast(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_ast,
            "Method AST",
        )

    def new_selector_name(self, default_selector):
        return simpledialog.askstring(
            "Rename Method",
            "New selector name:",
            initialvalue=default_selector,
            parent=self.application,
        )

    def run_method_rename(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, old_selector = method_context
        new_selector = self.new_selector_name(old_selector)
        if not new_selector:
            return
        if apply_change:
            should_apply = messagebox.askyesno(
                "Confirm Rename",
                (
                    "Apply rename of %s to %s on %s (%s side)?"
                    % (
                        old_selector,
                        new_selector,
                        class_name,
                        "instance" if show_instance_side else "class",
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                rename_result = self.gemstone_session_record.apply_method_rename(
                    class_name,
                    show_instance_side,
                    old_selector,
                    new_selector,
                )
            else:
                rename_result = self.gemstone_session_record.preview_method_rename(
                    class_name,
                    show_instance_side,
                    old_selector,
                    new_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Method Rename %s" % ("Apply" if apply_change else "Preview"),
            rename_result,
        )
        if apply_change:
            self.application.event_queue.publish("MethodSelected", origin=self)

    def preview_method_rename(self):
        self.run_method_rename(apply_change=False)

    def apply_method_rename(self):
        self.run_method_rename(apply_change=True)

    def side_input_to_boolean(self, side_input):
        normalized_side = (side_input or "").strip().lower()
        if normalized_side in ("instance", "instance side", "i"):
            return True
        if normalized_side in ("class", "class side", "meta", "c"):
            return False
        return None

    def move_target_details(self, show_instance_side):
        target_class_name = simpledialog.askstring(
            "Move Method",
            "Target class name:",
            parent=self.application,
        )
        if not target_class_name:
            return None
        default_side = "instance" if show_instance_side else "class"
        target_side = simpledialog.askstring(
            "Move Method",
            "Target side (instance/class):",
            initialvalue=default_side,
            parent=self.application,
        )
        target_show_instance_side = self.side_input_to_boolean(target_side)
        if target_show_instance_side is None:
            messagebox.showerror(
                "Invalid Side",
                "Target side must be instance or class.",
            )
            return None
        return (target_class_name, target_show_instance_side)

    def run_method_move(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        source_class_name, source_show_instance_side, method_selector = method_context
        target_details = self.move_target_details(source_show_instance_side)
        if target_details is None:
            return
        target_class_name, target_show_instance_side = target_details
        overwrite_target_method = False
        delete_source_method = True
        if apply_change:
            overwrite_target_method = messagebox.askyesno(
                "Move Method",
                "Overwrite target method when it already exists?",
            )
            delete_source_method = messagebox.askyesno(
                "Move Method",
                "Delete source method after move?",
            )
            should_apply = messagebox.askyesno(
                "Confirm Move",
                (
                    "Apply move of %s from %s (%s side) to %s (%s side)?"
                    % (
                        method_selector,
                        source_class_name,
                        "instance" if source_show_instance_side else "class",
                        target_class_name,
                        "instance" if target_show_instance_side else "class",
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                move_result = self.gemstone_session_record.apply_method_move(
                    source_class_name,
                    source_show_instance_side,
                    target_class_name,
                    target_show_instance_side,
                    method_selector,
                    overwrite_target_method=overwrite_target_method,
                    delete_source_method=delete_source_method,
                )
            else:
                move_result = self.gemstone_session_record.preview_method_move(
                    source_class_name,
                    source_show_instance_side,
                    target_class_name,
                    target_show_instance_side,
                    method_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Method Move %s" % ("Apply" if apply_change else "Preview"),
            move_result,
        )
        if apply_change:
            self.application.event_queue.publish("SelectedClassChanged")
            self.application.event_queue.publish("SelectedCategoryChanged")
            self.application.event_queue.publish("MethodSelected")

    def preview_method_move(self):
        self.run_method_move(apply_change=False)

    def apply_method_move(self):
        self.run_method_move(apply_change=True)

    def parameter_keyword_input(self):
        return simpledialog.askstring(
            "Add Parameter",
            "Parameter keyword (for example with:):",
            initialvalue="with:",
            parent=self.application,
        )

    def parameter_name_input(self):
        return simpledialog.askstring(
            "Add Parameter",
            "Parameter name:",
            initialvalue="newValue",
            parent=self.application,
        )

    def default_argument_source_input(self):
        return simpledialog.askstring(
            "Add Parameter",
            "Default argument source expression:",
            initialvalue="nil",
            parent=self.application,
        )

    def run_method_add_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        parameter_keyword = self.parameter_keyword_input()
        if not parameter_keyword:
            return
        parameter_name = self.parameter_name_input()
        if not parameter_name:
            return
        default_argument_source = self.default_argument_source_input()
        if not default_argument_source:
            return
        if apply_change:
            should_apply = messagebox.askyesno(
                "Confirm Add Parameter",
                (
                    "Apply add-parameter on %s>>%s with keyword %s?"
                    % (
                        class_name,
                        method_selector,
                        parameter_keyword,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                add_parameter_result = (
                    self.gemstone_session_record.apply_method_add_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        parameter_name,
                        default_argument_source,
                    )
                )
            else:
                add_parameter_result = (
                    self.gemstone_session_record.preview_method_add_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        parameter_name,
                        default_argument_source,
                    )
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Add Parameter %s" % ("Apply" if apply_change else "Preview"),
            add_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish("MethodSelected", origin=self)

    def preview_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=False)

    def apply_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=True)

    def remove_parameter_keyword_input(self):
        return simpledialog.askstring(
            "Remove Parameter",
            "Parameter keyword to remove:",
            parent=self.application,
        )

    def run_method_remove_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        parameter_keyword = self.remove_parameter_keyword_input()
        if not parameter_keyword:
            return
        rewrite_source_senders = messagebox.askyesno(
            "Remove Parameter",
            "Rewrite same-class senders that use this keyword selector?",
        )
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                "Remove Parameter",
                "Overwrite generated selector when it already exists?",
            )
            should_apply = messagebox.askyesno(
                "Confirm Remove Parameter",
                (
                    "Apply remove-parameter on %s>>%s removing %s?"
                    % (
                        class_name,
                        method_selector,
                        parameter_keyword,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                remove_parameter_result = (
                    self.gemstone_session_record.apply_method_remove_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        overwrite_new_method=overwrite_new_method,
                        rewrite_source_senders=rewrite_source_senders,
                    )
                )
            else:
                remove_parameter_result = (
                    self.gemstone_session_record.preview_method_remove_parameter(
                        class_name,
                        show_instance_side,
                        method_selector,
                        parameter_keyword,
                        rewrite_source_senders=rewrite_source_senders,
                    )
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Remove Parameter %s" % ("Apply" if apply_change else "Preview"),
            remove_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish("MethodSelected", origin=self)

    def preview_method_remove_parameter(self):
        self.run_method_remove_parameter(apply_change=False)

    def apply_method_remove_parameter(self):
        self.run_method_remove_parameter(apply_change=True)

    def new_selector_input(self, title_text, prompt_text, initial_value=None):
        return simpledialog.askstring(
            title_text,
            prompt_text,
            initialvalue=initial_value,
            parent=self.application,
        )

    def text_offset_for_index(self, text_index):
        characters = self.text_editor.count("1.0", text_index, "chars")
        if not characters:
            return 0
        return int(characters[0])

    def selected_text_offsets(self):
        try:
            selection_start_index = self.text_editor.index(tk.SEL_FIRST)
            selection_end_index = self.text_editor.index(tk.SEL_LAST)
        except tk.TclError:
            return None
        selection_start_offset = self.text_offset_for_index(selection_start_index)
        selection_end_offset = self.text_offset_for_index(selection_end_index)
        if selection_start_offset <= selection_end_offset:
            return (selection_start_offset, selection_end_offset)
        return (selection_end_offset, selection_start_offset)

    def selector_from_words(self, text):
        words = re.findall(r"[A-Za-z0-9]+", text)
        if not words:
            return "extractedPart"
        capitalized_words = "".join(
            word[0:1].upper() + word[1:] for word in words if word
        )
        if not capitalized_words:
            return "extractedPart"
        selector = "extracted%s" % capitalized_words
        normalized_selector = re.sub(r"[^A-Za-z0-9_]", "", selector)
        if not normalized_selector:
            return "extractedPart"
        if normalized_selector[0].isdigit():
            normalized_selector = "extracted%s" % normalized_selector
        return normalized_selector[0].lower() + normalized_selector[1:]

    def method_argument_names_from_ast_header(
        self,
        method_ast_payload,
        method_selector,
    ):
        selector_tokens = [
            "%s:" % selector_part
            for selector_part in method_selector.split(":")
            if selector_part
        ]
        if not selector_tokens:
            return []
        header_source = method_ast_payload.get("header_source", "")
        cursor = 0
        argument_names = []
        for selector_token in selector_tokens:
            while cursor < len(header_source) and header_source[cursor].isspace():
                cursor = cursor + 1
            token_matches = header_source.startswith(selector_token, cursor)
            if not token_matches:
                return []
            cursor = cursor + len(selector_token)
            while cursor < len(header_source) and header_source[cursor].isspace():
                cursor = cursor + 1
            argument_match = re.match(
                r"[A-Za-z_][A-Za-z0-9_]*",
                header_source[cursor:],
            )
            if argument_match is None:
                return []
            argument_name = argument_match.group(0)
            argument_names.append(argument_name)
            cursor = cursor + len(argument_name)
        return argument_names

    def inferred_extract_argument_names(
        self,
        method_ast_payload,
        selected_statement_entries,
        method_selector,
    ):
        method_temporaries = method_ast_payload.get("temporaries", [])
        method_arguments = self.method_argument_names_from_ast_header(
            method_ast_payload,
            method_selector,
        )
        scoped_names = []
        for name in method_arguments + method_temporaries:
            if name not in scoped_names:
                scoped_names.append(name)
        assignment_targets = []
        for statement_entry in selected_statement_entries:
            assignment_match = re.match(
                r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=",
                statement_entry.get("source", ""),
            )
            has_assignment = assignment_match is not None
            if has_assignment:
                target_name = assignment_match.group(1)
                if target_name not in assignment_targets:
                    assignment_targets.append(target_name)
        inferred_argument_names = []
        for statement_entry in selected_statement_entries:
            statement_source = statement_entry.get("source", "")
            identifier_matches = re.finditer(
                r"[A-Za-z_][A-Za-z0-9_]*",
                statement_source,
            )
            for identifier_match in identifier_matches:
                identifier_name = identifier_match.group(0)
                is_scoped = identifier_name in scoped_names
                is_assigned = identifier_name in assignment_targets
                is_already_inferred = identifier_name in inferred_argument_names
                if is_scoped and not is_assigned and not is_already_inferred:
                    inferred_argument_names.append(identifier_name)
        return inferred_argument_names

    def suggested_extract_selector(
        self,
        selected_statement_entries,
        inferred_argument_names,
    ):
        if not selected_statement_entries:
            return "extractedPart"
        first_statement = selected_statement_entries[0]
        statement_source = first_statement.get("source", "").strip()
        assignment_match = re.match(
            r"([A-Za-z_]\w*)\s*:=",
            statement_source,
        )
        if assignment_match:
            variable_name = assignment_match.group(1)
            base_selector = self.selector_from_words("compute %s" % variable_name)
        else:
            sends = first_statement.get("sends", [])
            if sends:
                base_selector = self.selector_from_words(sends[0].get("selector", ""))
            else:
                base_selector = self.selector_from_words(statement_source)
        if not inferred_argument_names:
            return base_selector
        keyword_tokens = ["%s:" % base_selector]
        for argument_name in inferred_argument_names[1:]:
            keyword_token = re.sub(r"[^A-Za-z0-9_]", "", argument_name) or "with"
            keyword_tokens.append("%s:" % keyword_token)
        return "".join(keyword_tokens)

    def selected_statement_entries_from_offsets(
        self,
        method_ast_payload,
        selection_offsets,
    ):
        if selection_offsets is None:
            raise DomainException(
                "Select one or more top-level statements before extracting."
            )
        statements = method_ast_payload.get("statements", [])
        if not statements:
            raise DomainException("No extractable top-level statements found.")
        selection_start_offset, selection_end_offset = selection_offsets
        selected_statement_entries = [
            statement_entry
            for statement_entry in statements
            if (
                statement_entry["start_offset"] >= selection_start_offset
                and statement_entry["end_offset"] <= selection_end_offset
            )
        ]
        if not selected_statement_entries:
            raise DomainException(
                ("Selection must fully cover one or more " "top-level statements.")
            )
        sorted_statement_entries = sorted(
            selected_statement_entries,
            key=lambda statement_entry: statement_entry["statement_index"],
        )
        statement_indexes = [
            statement_entry["statement_index"]
            for statement_entry in sorted_statement_entries
        ]
        expected_statement_indexes = list(
            range(
                statement_indexes[0],
                statement_indexes[-1] + 1,
            )
        )
        if statement_indexes != expected_statement_indexes:
            raise DomainException(
                "Selection must cover contiguous top-level statements."
            )
        return sorted_statement_entries

    def run_method_extract(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, method_selector = method_context
        try:
            selection_offsets = self.selected_text_offsets()
            if selection_offsets is None:
                raise DomainException(
                    "Select one or more top-level statements before extracting."
                )
            method_ast_payload = self.gemstone_session_record.method_ast(
                class_name,
                method_selector,
                show_instance_side,
            )
            selected_statement_entries = self.selected_statement_entries_from_offsets(
                method_ast_payload,
                selection_offsets,
            )
            statement_indexes = [
                statement_entry["statement_index"]
                for statement_entry in selected_statement_entries
            ]
            inferred_argument_names = self.inferred_extract_argument_names(
                method_ast_payload,
                selected_statement_entries,
                method_selector,
            )
            suggested_selector = self.suggested_extract_selector(
                selected_statement_entries,
                inferred_argument_names,
            )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror(
                "Extract Method",
                str(domain_exception),
            )
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Extract Method", str(gemstone_exception))
            return
        new_selector = self.new_selector_input(
            "Extract Method",
            "Name for extracted method:",
            initial_value=suggested_selector,
        )
        if not new_selector:
            return
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                "Extract Method",
                "Overwrite extracted method when it already exists?",
            )
            should_apply = messagebox.askyesno(
                "Confirm Extract Method",
                (
                    "Apply extract-method on %s>>%s to %s using statements %s?"
                    % (
                        class_name,
                        method_selector,
                        new_selector,
                        statement_indexes,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                extract_result = self.gemstone_session_record.apply_method_extract(
                    class_name,
                    show_instance_side,
                    method_selector,
                    new_selector,
                    statement_indexes,
                    overwrite_new_method=overwrite_new_method,
                )
            else:
                extract_result = self.gemstone_session_record.preview_method_extract(
                    class_name,
                    show_instance_side,
                    method_selector,
                    new_selector,
                    statement_indexes,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Extract Method %s" % ("Apply" if apply_change else "Preview"),
            extract_result,
        )
        if apply_change:
            self.application.event_queue.publish("MethodSelected", origin=self)

    def preview_method_extract(self):
        self.run_method_extract(apply_change=False)

    def apply_method_extract(self):
        self.run_method_extract(apply_change=True)

    def inline_selector_input(self):
        return self.new_selector_input(
            "Inline Method",
            "Inline selector:",
        )

    def run_method_inline(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                "No Method Context",
                "Select or open a method before running this operation.",
            )
            return
        class_name, show_instance_side, caller_selector = method_context
        inline_selector = self.inline_selector_input()
        if not inline_selector:
            return
        delete_inlined_method = False
        if apply_change:
            delete_inlined_method = messagebox.askyesno(
                "Inline Method",
                "Delete the inlined callee method after rewriting caller?",
            )
            should_apply = messagebox.askyesno(
                "Confirm Inline Method",
                (
                    "Apply inline-method in %s>>%s for selector %s?"
                    % (
                        class_name,
                        caller_selector,
                        inline_selector,
                    )
                ),
            )
            if not should_apply:
                return
        try:
            if apply_change:
                inline_result = self.gemstone_session_record.apply_method_inline(
                    class_name,
                    show_instance_side,
                    caller_selector,
                    inline_selector,
                    delete_inlined_method=delete_inlined_method,
                )
            else:
                inline_result = self.gemstone_session_record.preview_method_inline(
                    class_name,
                    show_instance_side,
                    caller_selector,
                    inline_selector,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Operation Failed", str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror("Operation Failed", str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            "Inline Method %s" % ("Apply" if apply_change else "Preview"),
            inline_result,
        )
        if apply_change:
            self.application.event_queue.publish("MethodSelected", origin=self)

    def preview_method_inline(self):
        self.run_method_inline(apply_change=False)

    def apply_method_inline(self):
        self.run_method_inline(apply_change=True)

    def apply_syntax_highlighting(self, text):
        for match in re.finditer(r"\b(class|self|super|true|false|nil)\b", text):
            start, end = match.span()
            self.text_editor.tag_add(
                "smalltalk_keyword", f"1.0 + {start} chars", f"1.0 + {end} chars"
            )

        for match in re.finditer(r'".*?"', text):
            start, end = match.span()
            self.text_editor.tag_add(
                "smalltalk_comment", f"1.0 + {start} chars", f"1.0 + {end} chars"
            )

        for match in re.finditer(r"\'.*?\'", text):
            start, end = match.span()
            self.text_editor.tag_add(
                "smalltalk_string", f"1.0 + {start} chars", f"1.0 + {end} chars"
            )

    def on_key_release(self, event):
        text = self.text_editor.get("1.0", tk.END)
        self.apply_syntax_highlighting(text)
        self.apply_breakpoint_markers(text)

    def line_and_column_for_source_offset(self, source_offset):
        source_text = self.text_editor.get("1.0", "end-1c")
        source_length = len(source_text)
        normalized_source_offset = source_offset
        if normalized_source_offset < 1:
            normalized_source_offset = 1
        maximum_offset = source_length + 1
        if normalized_source_offset > maximum_offset:
            normalized_source_offset = maximum_offset
        index_text = self.text_editor.index(
            f"1.0 + {normalized_source_offset - 1} chars"
        )
        line_text, column_text = index_text.split(".")
        return int(line_text), int(column_text) + 1

    def breakpoint_entries_for_current_method(self):
        if self.tab_key is None:
            return []
        gemstone_session_record = self.gemstone_session_record
        if gemstone_session_record is None:
            return []
        class_name, show_instance_side, method_selector = self.tab_key
        breakpoint_entries = gemstone_session_record.list_breakpoints()
        matching_breakpoints = []
        index = 0
        breakpoint_count = len(breakpoint_entries)
        while index < breakpoint_count:
            breakpoint_entry = breakpoint_entries[index]
            same_class = breakpoint_entry["class_name"] == class_name
            same_side = breakpoint_entry["show_instance_side"] == show_instance_side
            same_selector = breakpoint_entry["method_selector"] == method_selector
            if same_class and same_side and same_selector:
                matching_breakpoints.append(breakpoint_entry)
            index += 1
        return matching_breakpoints

    def apply_breakpoint_markers(self, source):
        self.text_editor.tag_remove("breakpoint_marker", "1.0", tk.END)
        breakpoint_entries = self.breakpoint_entries_for_current_method()
        source_length = len(source)
        index = 0
        breakpoint_count = len(breakpoint_entries)
        while index < breakpoint_count:
            source_offset = breakpoint_entries[index]["source_offset"]
            normalized_source_offset = source_offset
            if normalized_source_offset < 1:
                normalized_source_offset = 1
            if normalized_source_offset > source_length and source_length > 0:
                normalized_source_offset = source_length
            if source_length > 0:
                start_position = self.text_editor.index(
                    f"1.0 + {normalized_source_offset - 1} chars"
                )
                self.text_editor.tag_add(
                    "breakpoint_marker",
                    start_position,
                    f"{start_position} + 1c",
                )
            index += 1

    def refresh(self, source, mark=None):
        text_editor_was_disabled = self.text_editor.cget("state") == tk.DISABLED
        if text_editor_was_disabled:
            self.text_editor.configure(state=tk.NORMAL)
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", source)
        if mark is not None and mark >= 0:
            position = self.text_editor.index(f"1.0 + {mark-1} chars")
            self.text_editor.tag_add("highlight", position, f"{position} + 1c")
        self.apply_syntax_highlighting(source)
        self.apply_breakpoint_markers(source)
        self.cursor_position_indicator.update_position()
        if text_editor_was_disabled:
            self.text_editor.configure(state=tk.DISABLED)


class EditorTab(tk.Frame):
    def __init__(self, parent, browser_window, method_editor, tab_key):
        super().__init__(parent)
        self.browser_window = browser_window
        self.method_editor = method_editor
        self.tab_key = tab_key

        # Create CodePanel instance
        self.code_panel = CodePanel(
            self,
            self.browser_window.application,
            tab_key=tab_key,
        )
        self.code_panel.grid(row=0, column=0, sticky="nsew")

        # Configure the grid weights for resizing
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.repopulate()

    def open_tab_menu(self, event):
        return None

    def save(self):
        selected_class, show_instance_side, method_symbol = self.tab_key
        self.browser_window.gemstone_session_record.update_method_source(
            selected_class,
            show_instance_side,
            method_symbol,
            self.code_panel.text_editor.get("1.0", "end-1c"),
        )
        self.browser_window.event_queue.publish("MethodSelected", origin=self)
        self.repopulate()

    def repopulate(self):
        selected_class, show_instance_side, method_symbol = self.tab_key
        gemstone_method = self.browser_window.gemstone_session_record.get_method(
            *self.tab_key
        )
        if gemstone_method:
            method_source = gemstone_method.sourceString().to_py
            self.code_panel.refresh(method_source)
        else:
            self.method_editor.close_tab(self)


class BrowserWindow(ttk.PanedWindow):
    def __init__(self, parent, application):
        super().__init__(
            parent, orient=tk.VERTICAL
        )  # Make BrowserWindow a vertical paned window

        self.application = application

        # Create two frames to act as rows in the PanedWindow
        self.top_frame = ttk.Frame(self)
        self.bottom_frame = ttk.Frame(self)

        # Add frames to the PanedWindow
        self.add(self.top_frame)  # Add the top frame (row 0)
        self.add(self.bottom_frame)  # Add the bottom frame (row 1)

        # Add widgets to top_frame (similar to row 0 previously)
        self.packages_widget = PackageSelection(
            self.top_frame, self, self.event_queue, 0, 0
        )
        self.classes_widget = ClassSelection(
            self.top_frame, self, self.event_queue, 0, 1
        )
        self.categories_widget = CategorySelection(
            self.top_frame, self, self.event_queue, 0, 2
        )
        self.methods_widget = MethodSelection(
            self.top_frame, self, self.event_queue, 0, 3
        )

        # Add MethodEditor to bottom_frame (similar to row 1 previously)
        self.editor_area_widget = MethodEditor(
            self.bottom_frame, self, self.event_queue, 0, 0, colspan=4
        )

        # Configure grid in top_frame and bottom_frame for proper resizing
        self.top_frame.columnconfigure(0, weight=1)
        self.top_frame.columnconfigure(1, weight=1)
        self.top_frame.columnconfigure(2, weight=1)
        self.top_frame.columnconfigure(3, weight=1)
        self.top_frame.rowconfigure(0, weight=1)

        self.bottom_frame.columnconfigure(0, weight=1)
        self.bottom_frame.rowconfigure(0, weight=1)

    @property
    def event_queue(self):
        return self.application.event_queue

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record


class ObjectInspector(ttk.Frame):
    def __init__(
        self,
        parent,
        an_object=None,
        values=None,
        external_inspect_action=None,
        graph_inspect_action=None,
        browse_class_action=None,
    ):
        super().__init__(parent)
        self.inspected_object = an_object
        self.external_inspect_action = external_inspect_action
        self.graph_inspect_action = graph_inspect_action
        self.browse_class_action = browse_class_action
        self.current_object_menu = None
        self.page_size = 100
        self.current_page = 0
        self.total_items = 0
        self.pagination_mode = None
        self.dictionary_keys = []
        self.set_as_array = None
        self.actual_values = []
        self.treeview_heading = "Name"

        # Create a Treeview widget in the inspector
        self.treeview = ttk.Treeview(
            self, columns=("Name", "Class", "Value"), show="headings"
        )
        self.treeview.heading("Name", text="Name")
        self.treeview.heading("Class", text="Class")
        self.treeview.heading("Value", text="Value")
        self.treeview.grid(row=0, column=0, sticky="nsew")

        self.footer = ttk.Frame(self)
        self.footer.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.status_label = ttk.Label(self.footer, text="")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.previous_button = ttk.Button(
            self.footer, text="Previous", command=self.on_previous_page
        )
        self.previous_button.grid(row=0, column=1, padx=(8, 0))
        self.next_button = ttk.Button(
            self.footer, text="Next", command=self.on_next_page
        )
        self.next_button.grid(row=0, column=2, padx=(4, 0))
        self.browse_class_button = ttk.Button(
            self.footer,
            text="Browse Class",
            command=self.browse_inspected_object_class,
        )
        self.browse_class_button.grid(row=0, column=3, padx=(8, 0))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.footer.columnconfigure(0, weight=1)

        if values is not None:
            self.pagination_mode = None
            self.load_rows(list(values.items()), "Name", len(values))
        else:
            self.inspect_object(an_object)

        # Bind double-click event to open nested inspectors
        self.treeview.bind("<Double-1>", self.on_item_double_click)
        self.treeview.bind("<Button-3>", self.open_object_menu)
        self.treeview.bind("<Button-1>", self.close_object_menu, add="+")
        browse_class_state = tk.NORMAL
        if self.browse_class_action is None or self.inspected_object is None:
            browse_class_state = tk.DISABLED
        self.browse_class_button.configure(state=browse_class_state)

    def class_name_of(self, an_object):
        class_name = "Unknown"
        if an_object is not None:
            try:
                class_name_candidate = an_object.gemstone_class().asString().to_py
                normalized_class_name = self.normalized_text(class_name_candidate)
                if normalized_class_name:
                    class_name = normalized_class_name
            except GemstoneError:
                pass
        return class_name

    def normalized_text(self, text_value):
        if isinstance(text_value, str):
            return " ".join(text_value.split())
        return ""

    def string_value_via_as_string(self, an_object):
        if an_object is None:
            return ""
        try:
            return self.normalized_text(an_object.asString().to_py)
        except GemstoneError:
            return ""

    def string_value_via_print_string(self, an_object):
        if an_object is None:
            return ""
        try:
            return self.normalized_text(an_object.printString().to_py)
        except GemstoneError:
            return ""

    def oop_label_of(self, an_object):
        if an_object is None:
            return ""
        oop_label = ""
        try:
            oop_value = an_object.oop
            if isinstance(oop_value, int):
                oop_label = str(oop_value)
            if isinstance(oop_value, str):
                oop_label = oop_value.strip()
        except (GemstoneError, AttributeError):
            pass
        return oop_label

    def value_label(self, an_object):
        label = "<unavailable>"
        if an_object is not None:
            as_string_value = self.string_value_via_as_string(an_object)
            if as_string_value:
                label = as_string_value
            if not as_string_value:
                print_string_value = self.string_value_via_print_string(an_object)
                if print_string_value:
                    label = print_string_value
            if label == "<unavailable>":
                label = f"<{self.class_name_of(an_object)}>"
        return label

    def tab_label_for(self, an_object):
        if an_object is None:
            return "Context"

        class_name = self.class_name_of(an_object)
        value = self.value_label(an_object)
        value_placeholder = f"<{class_name}>"
        include_value = value not in ("<unavailable>", value_placeholder, class_name)

        tab_label = class_name
        if include_value:
            tab_label = f"{class_name} {value}"

        oop_label = self.oop_label_of(an_object)
        if oop_label:
            tab_label = f"{oop_label}:{tab_label}"
        return tab_label

    def class_name_has_dictionary_semantics(self, class_name):
        dictionary_markers = ("Dictionary", "KeyValue")
        return any(marker in class_name for marker in dictionary_markers)

    def class_name_has_indexed_collection_semantics(self, class_name):
        indexed_markers = (
            "Array",
            "OrderedCollection",
            "SortedCollection",
            "SequenceableCollection",
            "List",
        )
        return any(marker in class_name for marker in indexed_markers)

    def class_name_has_set_semantics(self, class_name):
        set_markers = ("Set", "Bag")
        return any(marker in class_name for marker in set_markers)

    def configure_set_rows(self, an_object):
        try:
            self.set_as_array = an_object.asArray()
        except GemstoneError:
            return False
        try:
            total_items = self.set_as_array.size().to_py
        except GemstoneError:
            return False
        if type(total_items) is not int:
            return False
        self.pagination_mode = "set"
        self.current_page = 0
        self.total_items = total_items
        self.treeview_heading = "Element"
        self.refresh_rows_for_current_page()
        return True

    def set_rows_for_range(self, start_index, end_index):
        rows = []
        for one_based_index in range(start_index + 1, end_index + 1):
            value_found = False
            value = None
            try:
                value = self.set_as_array.at(one_based_index)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((f"[{one_based_index}]", value))
        return rows

    def inspect_object(self, an_object):
        if an_object is None:
            self.pagination_mode = None
            self.load_rows([], "Name", 0)
            return

        try:
            is_class = an_object.isBehavior().to_py
        except GemstoneError:
            is_class = False

        if is_class:
            self.pagination_mode = None
            inspected_values = self.inspect_class(an_object)
            self.load_rows(
                list(inspected_values.items()), "Name", len(inspected_values)
            )
            return

        class_name = self.class_name_of(an_object)
        dictionary_is_configured = False
        if self.class_name_has_dictionary_semantics(class_name):
            dictionary_is_configured = self.configure_dictionary_rows(an_object)
        if dictionary_is_configured:
            return

        indexed_collection_is_configured = False
        if self.class_name_has_indexed_collection_semantics(class_name):
            indexed_collection_is_configured = self.configure_indexed_collection_rows(
                an_object
            )
        if indexed_collection_is_configured:
            return

        set_is_configured = False
        if self.class_name_has_set_semantics(class_name):
            set_is_configured = self.configure_set_rows(an_object)
        if set_is_configured:
            return

        self.pagination_mode = None
        inspected_values = self.inspect_instance(an_object)
        self.load_rows(list(inspected_values.items()), "Name", len(inspected_values))

    def configure_dictionary_rows(self, an_object):
        try:
            self.dictionary_keys = list(an_object.keys())
        except GemstoneError:
            return False

        self.pagination_mode = "dictionary"
        self.current_page = 0
        self.total_items = len(self.dictionary_keys)
        self.treeview_heading = "Key"
        self.refresh_rows_for_current_page()
        return True

    def configure_indexed_collection_rows(self, an_object):
        try:
            total_items = an_object.size().to_py
        except GemstoneError:
            return False
        if type(total_items) is not int:
            return False

        can_access_index_one = True
        if total_items > 0:
            try:
                an_object.at(1)
            except GemstoneError:
                can_access_index_one = False
        if not can_access_index_one:
            return False

        self.pagination_mode = "indexed"
        self.current_page = 0
        self.total_items = total_items
        self.treeview_heading = "Index"
        self.refresh_rows_for_current_page()
        return True

    def row_range_for_current_page(self):
        if self.total_items < 1:
            return 0, 0

        start_index = self.current_page * self.page_size
        end_index = start_index + self.page_size
        if end_index > self.total_items:
            end_index = self.total_items
        return start_index, end_index

    def dictionary_rows_for_range(self, start_index, end_index):
        rows = []
        for key in self.dictionary_keys[start_index:end_index]:
            value_found = False
            value = None
            try:
                value = self.inspected_object.at(key)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((self.value_label(key), value))
        return rows

    def indexed_rows_for_range(self, start_index, end_index):
        rows = []
        for one_based_index in range(start_index + 1, end_index + 1):
            value_found = False
            value = None
            try:
                value = self.inspected_object.at(one_based_index)
                value_found = True
            except GemstoneError:
                pass
            if value_found:
                rows.append((f"[{one_based_index}]", value))
        return rows

    def refresh_rows_for_current_page(self):
        start_index, end_index = self.row_range_for_current_page()
        rows = []
        if self.pagination_mode == "dictionary":
            rows = self.dictionary_rows_for_range(start_index, end_index)
        if self.pagination_mode == "indexed":
            rows = self.indexed_rows_for_range(start_index, end_index)
        if self.pagination_mode == "set":
            rows = self.set_rows_for_range(start_index, end_index)
        self.load_rows(rows, self.treeview_heading, self.total_items)

    def inspect_instance(self, an_object):
        # AI: Regular instances expose their instance variables via instVarNamed:.
        values = {}
        for i, instvar_name in enumerate(
            an_object.gemstone_class().allInstVarNames(), start=1
        ):
            try:
                values[instvar_name.to_py] = an_object.instVarNamed(instvar_name)
            except GemstoneError:
                try:
                    # AI: Fall back to indexed access for objects that understand instVarAt:
                    # but not instVarNamed: (e.g. VariableContext, some built-in types).
                    values[instvar_name.to_py] = an_object.instVarAt(i)
                except GemstoneError:
                    pass
        return values

    def inspect_class(self, an_object):
        # AI: For class objects, show class variables (shared among all instances)
        # and any class-side instance variables.
        values = {}
        try:
            class_pool = an_object.classPool()
            for key in class_pool.keys():
                try:
                    values[key.to_py] = class_pool.at(key)
                except GemstoneError:
                    pass
        except (GemstoneError, AttributeError):
            pass
        for i, instvar_name in enumerate(
            an_object.gemstone_class().allInstVarNames(), start=1
        ):
            try:
                values[instvar_name.to_py] = an_object.instVarAt(i)
            except GemstoneError:
                pass
        return values

    def load_rows(self, rows, first_column_title, total_items):
        self.treeview_heading = first_column_title
        self.total_items = total_items
        self.treeview.heading("Name", text=self.treeview_heading)

        for existing_item in self.treeview.get_children():
            self.treeview.delete(existing_item)
        self.actual_values = []

        for row_name, row_value in rows:
            self.treeview.insert(
                "",
                "end",
                values=(
                    row_name,
                    self.class_name_of(row_value),
                    self.value_label(row_value),
                ),
            )
            self.actual_values.append(row_value)

        self.update_footer()

    def update_footer(self):
        start_index, end_index = self.row_range_for_current_page()
        show_page_window = (
            self.pagination_mode in ("dictionary", "indexed")
            and self.total_items > self.page_size
        )
        if show_page_window:
            self.status_label.configure(
                text=f"Items {start_index + 1}-{end_index} of {self.total_items}"
            )
        if not show_page_window:
            if self.total_items == 1:
                self.status_label.configure(text="1 item")
            if self.total_items != 1:
                self.status_label.configure(text=f"{self.total_items} items")

        self.previous_button.configure(state=tk.DISABLED)
        self.next_button.configure(state=tk.DISABLED)
        if show_page_window:
            if self.current_page > 0:
                self.previous_button.configure(state=tk.NORMAL)
            if end_index < self.total_items:
                self.next_button.configure(state=tk.NORMAL)

    def on_previous_page(self):
        can_page_backwards = (
            self.pagination_mode in ("dictionary", "indexed") and self.current_page > 0
        )
        if can_page_backwards:
            self.current_page -= 1
            self.refresh_rows_for_current_page()

    def on_next_page(self):
        start_index, end_index = self.row_range_for_current_page()
        can_page_forwards = (
            self.pagination_mode in ("dictionary", "indexed")
            and end_index < self.total_items
        )
        if can_page_forwards:
            self.current_page += 1
            self.refresh_rows_for_current_page()

    def on_item_double_click(self, event):
        value = self.selected_row_value()
        if value is None:
            return

        if hasattr(self.master, "open_or_select_object"):
            self.master.open_or_select_object(value)
            return

        tab_label = self.tab_label_for(value)
        try:
            new_tab = ObjectInspector(
                self.master,
                an_object=value,
                external_inspect_action=self.external_inspect_action,
                graph_inspect_action=self.graph_inspect_action,
            )
        except GemstoneError as e:
            messagebox.showerror("Inspector", f"Cannot inspect this object:\n{e}")
            return
        self.master.add(new_tab, text=tab_label)
        self.master.select(new_tab)

    def selected_row_value(self):
        selected_item = self.treeview.focus()
        if not selected_item:
            return None
        index = self.treeview.index(selected_item)
        if index < len(self.actual_values):
            return self.actual_values[index]
        return None

    def select_row_at_coordinates(self, event):
        selected_item = self.treeview.identify_row(event.y)
        if selected_item:
            self.treeview.focus(selected_item)
            self.treeview.selection_set(selected_item)

    def inspect_selected_row_in_external_inspector(self):
        if self.external_inspect_action is None:
            return
        value = self.selected_row_value()
        if value is None:
            return
        self.external_inspect_action(value)

    def graph_inspect_selected_row(self):
        if self.graph_inspect_action is None:
            return
        value = self.selected_row_value()
        if value is None:
            return
        self.graph_inspect_action(value)

    def browse_inspected_object_class(self):
        if self.browse_class_action is None:
            return
        if self.inspected_object is None:
            return
        self.browse_class_action(self.inspected_object)

    def open_object_menu(self, event):
        self.close_object_menu()
        self.select_row_at_coordinates(event)
        selected_value = self.selected_row_value()
        if selected_value is None:
            return
        object_menu = tk.Menu(self, tearoff=0)
        if self.external_inspect_action is not None:
            object_menu.add_command(
                label="Inspect",
                command=self.inspect_selected_row_in_external_inspector,
            )
        if self.graph_inspect_action is not None:
            object_menu.add_command(
                label="Graph Inspect",
                command=self.graph_inspect_selected_row,
            )
        has_menu_entries = object_menu.index("end") is not None
        if not has_menu_entries:
            return
        add_close_command_to_popup_menu(object_menu)
        self.current_object_menu = object_menu
        popup_menu(object_menu, event)

    def close_object_menu(self, event=None):
        if self.current_object_menu is None:
            return
        self.current_object_menu.destroy()
        self.current_object_menu = None


class Explorer(ttk.Notebook):
    def __init__(
        self,
        parent,
        an_object=None,
        values=None,
        root_tab_label=None,
        external_inspect_action=None,
        graph_inspect_action=None,
        browse_class_action=None,
    ):
        super().__init__(parent)
        self.tab_registry = DeduplicatedTabRegistry(self)
        self.external_inspect_action = external_inspect_action
        self.graph_inspect_action = graph_inspect_action
        self.browse_class_action = browse_class_action

        context_frame = ObjectInspector(
            self,
            an_object=an_object,
            values=values,
            external_inspect_action=self.external_inspect_action,
            graph_inspect_action=self.graph_inspect_action,
            browse_class_action=self.browse_class_action,
        )
        tab_label = root_tab_label
        if tab_label is None:
            tab_label = context_frame.tab_label_for(an_object)
        self.add(context_frame, text=tab_label)
        context_key = None
        if values is not None and an_object is None:
            context_key = ("context", str(id(context_frame)))
        self.register_object_tab(
            context_frame, an_object, tab_label, object_key=context_key
        )

    def object_key_for(self, an_object):
        if an_object is None:
            return ("none",)

        oop_label = ""
        try:
            oop_value = an_object.oop
            if isinstance(oop_value, int):
                oop_label = str(oop_value)
            if isinstance(oop_value, str):
                oop_label = oop_value.strip()
        except (GemstoneError, AttributeError):
            pass

        if oop_label:
            return ("oop", oop_label)
        return ("identity", str(id(an_object)))

    def register_object_tab(self, tab_widget, an_object, tab_label, object_key=None):
        if object_key is None:
            object_key = self.object_key_for(an_object)
        self.tab_registry.register_tab(object_key, tab_widget, tab_label)
        return object_key

    def open_or_select_object(self, an_object):
        object_key = self.object_key_for(an_object)
        if self.tab_registry.select_key(object_key):
            return

        try:
            new_tab = ObjectInspector(
                self,
                an_object=an_object,
                external_inspect_action=self.external_inspect_action,
                graph_inspect_action=self.graph_inspect_action,
                browse_class_action=self.browse_class_action,
            )
        except GemstoneError as e:
            messagebox.showerror("Inspector", f"Cannot inspect this object:\n{e}")
            return
        tab_label = new_tab.tab_label_for(an_object)
        self.add(new_tab, text=tab_label)
        self.register_object_tab(new_tab, an_object, tab_label, object_key=object_key)
        self.select(new_tab)

    def selected_object_key(self):
        return self.tab_registry.selected_key()

    def select_object_key(self, object_key):
        return self.tab_registry.select_key(object_key)

    def label_for_object_key(self, object_key):
        return self.tab_registry.label_for_key(object_key)


class InspectorTab(ttk.Frame):
    def __init__(
        self,
        parent,
        application,
        an_object=None,
        graph_inspect_action=None,
    ):
        super().__init__(parent)
        self.application = application
        self.object_navigation_history = NavigationHistory()
        self.history_choice_indices = []
        self.navigation_selection_in_progress = False

        self.actions_frame = ttk.Frame(self)
        self.actions_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.actions_frame.columnconfigure(4, weight=1)

        self.title_label = ttk.Label(self.actions_frame, text="Inspector")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.back_button = ttk.Button(
            self.actions_frame,
            text="Back",
            command=self.go_to_previous_object,
        )
        self.back_button.grid(row=0, column=1, padx=(6, 0))

        self.forward_button = ttk.Button(
            self.actions_frame,
            text="Forward",
            command=self.go_to_next_object,
        )
        self.forward_button.grid(row=0, column=2, padx=(4, 0))

        self.history_combobox = ttk.Combobox(
            self.actions_frame,
            state="readonly",
            width=44,
        )
        self.history_combobox.grid(row=0, column=3, padx=(6, 0), sticky="e")
        self.history_combobox.bind(
            "<<ComboboxSelected>>",
            self.jump_to_selected_history_entry,
        )

        self.close_button = ttk.Button(
            self.actions_frame,
            text="Close",
            command=self.application.close_inspector_tab,
        )
        self.close_button.grid(row=0, column=5, sticky="e")

        self.explorer = Explorer(
            self,
            an_object=an_object,
            graph_inspect_action=graph_inspect_action,
            browse_class_action=self.application.browse_object_class,
        )
        self.explorer.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.explorer.bind(
            "<<NotebookTabChanged>>",
            self.handle_explorer_tab_changed,
        )

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.record_object_navigation()

    def current_object_context(self):
        return self.explorer.selected_object_key()

    def object_context_label(self, object_context):
        return self.explorer.label_for_object_key(object_context)

    def record_object_navigation(self):
        self.object_navigation_history.record(self.current_object_context())
        self.refresh_navigation_controls()

    def refresh_navigation_controls(self):
        back_button_state = (
            tk.NORMAL if self.object_navigation_history.can_go_back() else tk.DISABLED
        )
        self.back_button.configure(state=back_button_state)

        forward_button_state = (
            tk.NORMAL
            if self.object_navigation_history.can_go_forward()
            else tk.DISABLED
        )
        self.forward_button.configure(state=forward_button_state)

        history_entries = self.object_navigation_history.entries_with_current_marker()
        self.history_choice_indices = []
        history_labels = []
        for history_entry in reversed(history_entries):
            history_index = history_entry["history_index"]
            object_context = history_entry["entry"]
            history_labels.append(self.object_context_label(object_context))
            self.history_choice_indices.append(history_index)
        self.history_combobox["values"] = history_labels

        if len(history_labels) > 0:
            current_history_index = self.object_navigation_history.current_index
            selected_index = len(history_labels) - current_history_index - 1
            self.history_combobox.current(selected_index)
        if len(history_labels) == 0:
            self.history_combobox.set("")

    def jump_to_object_context(self, object_context):
        if object_context is None:
            self.refresh_navigation_controls()
            return
        if object_context == self.current_object_context():
            self.refresh_navigation_controls()
            return
        self.navigation_selection_in_progress = True
        selected = self.explorer.select_object_key(object_context)
        if not selected:
            self.navigation_selection_in_progress = False
        self.refresh_navigation_controls()

    def go_to_previous_object(self):
        object_context = self.object_navigation_history.go_back()
        self.jump_to_object_context(object_context)

    def go_to_next_object(self):
        object_context = self.object_navigation_history.go_forward()
        self.jump_to_object_context(object_context)

    def jump_to_selected_history_entry(self, event):
        combobox_index = self.history_combobox.current()
        if combobox_index < 0:
            return
        if combobox_index >= len(self.history_choice_indices):
            return
        history_index = self.history_choice_indices[combobox_index]
        object_context = self.object_navigation_history.jump_to(history_index)
        self.jump_to_object_context(object_context)

    def handle_explorer_tab_changed(self, event=None):
        if self.navigation_selection_in_progress:
            self.navigation_selection_in_progress = False
            self.refresh_navigation_controls()
            return
        self.record_object_navigation()


class GraphNode:
    def __init__(self, an_object, oop_key, class_name, label):
        self.gemstone_object = an_object
        self.oop_key = oop_key
        self.class_name = class_name
        self.label = label
        self.x = 0
        self.y = 0
        self.canvas_item_ids = []

    def bounding_box(self):
        half_width = GRAPH_NODE_WIDTH // 2
        half_height = GRAPH_NODE_HEIGHT // 2
        return (
            self.x - half_width,
            self.y - half_height,
            self.x + half_width,
            self.y + half_height,
        )


class GraphEdge:
    def __init__(self, source_node, target_node, instvar_label):
        self.source_node = source_node
        self.target_node = target_node
        self.instvar_label = instvar_label
        self.canvas_item_ids = []


class GraphObjectRegistry:
    def __init__(self):
        self.nodes_by_oop_key = {}
        self.edges = []

    def oop_key_for(self, an_object):
        if an_object is None:
            return ("none",)
        try:
            oop_label = an_object.oop
            if oop_label is not None:
                return ("oop", str(oop_label))
        except (
            AttributeError,
            GemstoneError,
            tk.TclError,
            TypeError,
            ValueError,
            RuntimeError,
        ):
            pass
        return ("identity", str(id(an_object)))

    def contains_object(self, an_object):
        return self.oop_key_for(an_object) in self.nodes_by_oop_key

    def node_for(self, an_object):
        return self.nodes_by_oop_key.get(self.oop_key_for(an_object))

    def register_node(self, node):
        self.nodes_by_oop_key[node.oop_key] = node

    def add_edge(self, source_node, target_node, instvar_label):
        for existing in self.edges:
            is_same = (
                existing.source_node is source_node
                and existing.target_node is target_node
                and existing.instvar_label == instvar_label
            )
            if is_same:
                return None
        self.edges.append(GraphEdge(source_node, target_node, instvar_label))
        return self.edges[-1]

    def all_nodes(self):
        return list(self.nodes_by_oop_key.values())

    def all_edges(self):
        return list(self.edges)


class GraphNodeInspectorHost(ttk.Frame):
    def __init__(
        self,
        parent,
        an_object,
        graph_node,
        on_navigate_to_child,
        browse_class_action,
    ):
        super().__init__(parent)
        self.graph_node = graph_node
        self.on_navigate_to_child = on_navigate_to_child
        self.inspector = ObjectInspector(
            self,
            an_object=an_object,
            external_inspect_action=None,
            graph_inspect_action=None,
            browse_class_action=browse_class_action,
        )
        self.inspector.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def open_or_select_object(self, value):
        selected_item = self.inspector.treeview.focus()
        instvar_label = ""
        if selected_item:
            row_values = self.inspector.treeview.item(selected_item, "values")
            if row_values:
                instvar_label = row_values[0]
        self.on_navigate_to_child(value, instvar_label)


class ObjectDetailDialog:
    def __init__(self, parent, an_object, graph_node, on_add_to_graph):
        self.graph_node = graph_node
        self.on_add_to_graph = on_add_to_graph
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"Graph Node: {graph_node.label}")
        self.dialog.geometry("650x420")
        self.dialog.grab_set()
        self.inspector_host = GraphNodeInspectorHost(
            self.dialog,
            an_object=an_object,
            graph_node=graph_node,
            on_navigate_to_child=self.navigate_to_child,
            browse_class_action=parent.application.browse_object_class,
        )
        self.inspector_host.pack(fill="both", expand=True)

    def navigate_to_child(self, target_object, instvar_label):
        self.on_add_to_graph(self.graph_node, target_object, instvar_label)
        self.dialog.destroy()


class UmlMethodChooserDialog(tk.Toplevel):
    def __init__(self, parent, application, class_name, on_method_selected):
        super().__init__(parent)
        self.application = application
        self.class_name = class_name
        self.on_method_selected = on_method_selected
        self.selected_method_category = None
        self.selected_method_selector = None
        self.side_var = tk.StringVar(value="instance")

        self.title(f"Add Method to UML: {class_name}")
        self.geometry("620x420")
        self.transient(parent)
        self.grab_set()

        controls_frame = ttk.Frame(self)
        controls_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ttk.Label(controls_frame, text=class_name).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
        )
        self.instance_radiobutton = ttk.Radiobutton(
            controls_frame,
            text="Instance",
            variable=self.side_var,
            value="instance",
            command=self.handle_side_changed,
        )
        self.instance_radiobutton.grid(row=0, column=1, sticky="w")
        self.class_radiobutton = ttk.Radiobutton(
            controls_frame,
            text="Class",
            variable=self.side_var,
            value="class",
            command=self.handle_side_changed,
        )
        self.class_radiobutton.grid(row=0, column=2, sticky="w", padx=(8, 0))
        controls_frame.columnconfigure(3, weight=1)

        lists_frame = ttk.Frame(self)
        lists_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        lists_frame.columnconfigure(0, weight=1)
        lists_frame.columnconfigure(1, weight=1)
        lists_frame.rowconfigure(1, weight=1)

        ttk.Label(lists_frame, text="Categories").grid(row=0, column=0, sticky="w")
        ttk.Label(lists_frame, text="Methods").grid(row=0, column=1, sticky="w")

        self.category_selection = InteractiveSelectionList(
            lists_frame,
            self.get_all_categories,
            self.get_selected_category,
            self.select_category,
        )
        self.category_selection.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.method_selection = InteractiveSelectionList(
            lists_frame,
            self.get_all_methods,
            self.get_selected_method,
            self.select_method,
        )
        self.method_selection.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self.method_selection.selection_listbox.bind(
            "<Double-1>",
            self.add_selected_method,
        )

        buttons_frame = ttk.Frame(self)
        buttons_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        buttons_frame.columnconfigure(0, weight=1)
        self.add_button = ttk.Button(
            buttons_frame,
            text="Add",
            command=self.add_selected_method,
            state=tk.DISABLED,
        )
        self.add_button.grid(row=0, column=1)
        ttk.Button(
            buttons_frame,
            text="Cancel",
            command=self.destroy,
        ).grid(row=0, column=2, padx=(6, 0))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.repopulate()

    @property
    def show_instance_side(self):
        return self.side_var.get() == "instance"

    def repopulate(self):
        self.selected_method_category = None
        self.selected_method_selector = None
        self.category_selection.repopulate()
        category_entries = list(self.category_selection.selection_listbox.get(0, "end"))
        if category_entries:
            self.select_category(category_entries[0])
        if not category_entries:
            self.method_selection.repopulate()
            self.refresh_add_button()

    def get_all_categories(self):
        categories = list(
            self.application.gemstone_session_record.get_categories_in_class(
                self.class_name,
                self.show_instance_side,
            )
        )
        return ["all"] + categories

    def get_selected_category(self):
        return self.selected_method_category

    def select_category(self, selected_category):
        self.selected_method_category = selected_category
        self.selected_method_selector = None
        self.method_selection.repopulate()
        self.refresh_add_button()

    def get_all_methods(self):
        if self.selected_method_category is None:
            return []
        return list(
            self.application.gemstone_session_record.get_selectors_in_class(
                self.class_name,
                self.selected_method_category,
                self.show_instance_side,
            )
        )

    def get_selected_method(self):
        return self.selected_method_selector

    def select_method(self, selected_method):
        self.selected_method_selector = selected_method
        self.refresh_add_button()

    def refresh_add_button(self):
        button_state = tk.NORMAL if self.selected_method_selector else tk.DISABLED
        self.add_button.configure(state=button_state)

    def handle_side_changed(self):
        self.repopulate()

    def add_selected_method(self, event=None):
        if not self.selected_method_selector:
            return
        self.on_method_selected(
            self.class_name,
            self.show_instance_side,
            self.selected_method_selector,
        )
        self.destroy()


class GraphCanvas(ttk.Frame):
    def __init__(self, parent, node_detail_action):
        super().__init__(parent)
        self.node_detail_action = node_detail_action
        self.registry = GraphObjectRegistry()
        self.dragging_node = None
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.canvas = tk.Canvas(
            self,
            bg="white",
            scrollregion=(0, 0, 2000, 2000),
        )
        horizontal_scrollbar = ttk.Scrollbar(
            self,
            orient="horizontal",
            command=self.canvas.xview,
        )
        vertical_scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.canvas.configure(
            xscrollcommand=horizontal_scrollbar.set,
            yscrollcommand=vertical_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)

    def add_object_to_graph(self, an_object, source_node=None, instvar_label=None):
        if an_object is None:
            return
        existing_node = self.registry.node_for(an_object)
        if existing_node is not None:
            target_node = existing_node
        else:
            oop_key = self.registry.oop_key_for(an_object)
            class_name = "?"
            try:
                class_name = an_object.gemstone_class().asString().to_py
            except (
                AttributeError,
                GemstoneError,
                tk.TclError,
                TypeError,
                ValueError,
            ):
                pass
            oop_string = oop_key[1] if oop_key[0] == "oop" else "?"
            label = f"{oop_string}:{class_name}"
            target_node = GraphNode(an_object, oop_key, class_name, label)
            self.place_new_node(target_node)
            self.draw_node(target_node)
            self.registry.register_node(target_node)

        should_add_edge = source_node is not None and bool(instvar_label)
        if should_add_edge:
            new_edge = self.registry.add_edge(source_node, target_node, instvar_label)
            if new_edge is not None:
                self.draw_edge(new_edge)

        self.expand_scroll_region()

    def place_new_node(self, node):
        existing_count = len(self.registry.all_nodes())
        column_index = existing_count % GRAPH_NODES_PER_ROW
        row_index = existing_count // GRAPH_NODES_PER_ROW
        node.x = (
            GRAPH_ORIGIN_X
            + column_index * (GRAPH_NODE_WIDTH + GRAPH_NODE_PADDING_X)
            + GRAPH_NODE_WIDTH // 2
        )
        node.y = (
            GRAPH_ORIGIN_Y
            + row_index * (GRAPH_NODE_HEIGHT + GRAPH_NODE_PADDING_Y)
            + GRAPH_NODE_HEIGHT // 2
        )

    def draw_node(self, node):
        x1, y1, x2, y2 = node.bounding_box()
        rectangle_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill="#e8f0fe",
            outline="#3366cc",
            width=2,
        )
        oop_string = node.oop_key[1] if node.oop_key[0] == "oop" else "?"
        oop_text_id = self.canvas.create_text(
            node.x,
            y1 + 14,
            text=oop_string,
            font=("TkDefaultFont", 9, "bold"),
            fill="#3366cc",
        )
        class_text_id = self.canvas.create_text(
            node.x,
            y1 + 32,
            text=node.class_name,
            font=("TkDefaultFont", 9),
            fill="#222222",
        )
        node.canvas_item_ids = [rectangle_id, oop_text_id, class_text_id]

    def edge_boundary_point(self, from_node, toward_node):
        delta_x = toward_node.x - from_node.x
        delta_y = toward_node.y - from_node.y
        half_width = GRAPH_NODE_WIDTH / 2
        half_height = GRAPH_NODE_HEIGHT / 2
        if delta_x == 0 and delta_y == 0:
            return from_node.x + half_width, from_node.y
        scale_x = abs(half_width / delta_x) if delta_x != 0 else float("inf")
        scale_y = abs(half_height / delta_y) if delta_y != 0 else float("inf")
        scale = min(scale_x, scale_y)
        return from_node.x + delta_x * scale, from_node.y + delta_y * scale

    def draw_edge(self, edge):
        x1, y1 = self.edge_boundary_point(edge.source_node, edge.target_node)
        x2, y2 = self.edge_boundary_point(edge.target_node, edge.source_node)
        midpoint_x = (x1 + x2) / 2
        midpoint_y = (y1 + y2) / 2
        line_id = self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            arrow=tk.LAST,
            arrowshape=(10, 12, 5),
            fill="#444444",
            width=1.5,
        )
        label_id = self.canvas.create_text(
            midpoint_x,
            midpoint_y - 10,
            text=edge.instvar_label,
            font=("TkDefaultFont", 9),
            fill="#222288",
            anchor="s",
        )
        edge.canvas_item_ids = [line_id, label_id]

    def redraw_edges_for_node(self, node):
        for edge in self.registry.all_edges():
            touches_node = edge.source_node is node or edge.target_node is node
            if touches_node:
                for item_id in edge.canvas_item_ids:
                    self.canvas.delete(item_id)
                edge.canvas_item_ids = []
                self.draw_edge(edge)

    def node_at_canvas_coordinates(self, canvas_x, canvas_y):
        for node in self.registry.all_nodes():
            x1, y1, x2, y2 = node.bounding_box()
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                return node
        return None

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.dragging_node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y

    def on_canvas_drag(self, event):
        if self.dragging_node is None:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        delta_x = canvas_x - self.drag_start_x
        delta_y = canvas_y - self.drag_start_y
        for item_id in self.dragging_node.canvas_item_ids:
            self.canvas.move(item_id, delta_x, delta_y)
        self.dragging_node.x += delta_x
        self.dragging_node.y += delta_y
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y
        self.redraw_edges_for_node(self.dragging_node)

    def on_canvas_release(self, event):
        self.dragging_node = None
        self.expand_scroll_region()

    def on_canvas_right_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        if node is None:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Inspect Object",
            command=lambda: self.node_detail_action(node),
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def expand_scroll_region(self):
        all_nodes = self.registry.all_nodes()
        if not all_nodes:
            self.canvas.configure(scrollregion=(0, 0, 2000, 2000))
            return
        minimum_x = min(node.x - GRAPH_NODE_WIDTH // 2 for node in all_nodes)
        minimum_x -= GRAPH_ORIGIN_X
        minimum_y = min(node.y - GRAPH_NODE_HEIGHT // 2 for node in all_nodes)
        minimum_y -= GRAPH_ORIGIN_Y
        maximum_x = max(node.x + GRAPH_NODE_WIDTH // 2 for node in all_nodes)
        maximum_x += GRAPH_ORIGIN_X
        maximum_y = max(node.y + GRAPH_NODE_HEIGHT // 2 for node in all_nodes)
        maximum_y += GRAPH_ORIGIN_Y
        self.canvas.configure(
            scrollregion=(
                min(minimum_x, 0),
                min(minimum_y, 0),
                max(maximum_x, 2000),
                max(maximum_y, 2000),
            )
        )

    def clear_all(self):
        self.canvas.delete("all")
        self.registry = GraphObjectRegistry()
        self.expand_scroll_region()


class GraphTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application

        actions_frame = ttk.Frame(self)
        actions_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        ttk.Label(actions_frame, text="Graph Inspector").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(actions_frame, text="Clear", command=self.clear_graph).grid(
            row=0,
            column=1,
            padx=(6, 0),
        )
        ttk.Button(
            actions_frame,
            text="Close",
            command=self.application.close_graph_tab,
        ).grid(row=0, column=2, padx=(6, 0))

        self.graph_canvas = GraphCanvas(
            self,
            node_detail_action=self.open_node_detail,
        )
        self.graph_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

    def add_object(self, an_object):
        self.graph_canvas.add_object_to_graph(
            an_object,
            source_node=None,
            instvar_label=None,
        )

    def open_node_detail(self, graph_node):
        ObjectDetailDialog(
            self,
            an_object=graph_node.gemstone_object,
            graph_node=graph_node,
            on_add_to_graph=self.on_add_to_graph_from_dialog,
        )

    def on_add_to_graph_from_dialog(self, source_node, target_object, instvar_label):
        self.graph_canvas.add_object_to_graph(
            target_object,
            source_node=source_node,
            instvar_label=instvar_label,
        )

    def clear_graph(self):
        self.graph_canvas.clear_all()


class UmlClassNode:
    def __init__(self, class_definition):
        self.class_name = class_definition.get("class_name") or ""
        self.superclass_name = class_definition.get("superclass_name")
        self.inst_var_names = list(class_definition.get("inst_var_names") or [])
        self.pinned_methods = []
        self.x = 0
        self.y = 0
        self.canvas_item_ids = []

    def update_from_definition(self, class_definition):
        self.superclass_name = class_definition.get("superclass_name")
        self.inst_var_names = list(class_definition.get("inst_var_names") or [])

    def height(self):
        method_count = len(self.pinned_methods)
        if method_count == 0:
            return UML_NODE_MIN_HEIGHT
        return UML_HEADER_HEIGHT + 14 + method_count * UML_METHOD_LINE_HEIGHT + 12

    def bounding_box(self):
        half_width = UML_NODE_WIDTH // 2
        half_height = self.height() // 2
        return (
            self.x - half_width,
            self.y - half_height,
            self.x + half_width,
            self.y + half_height,
        )


class UmlRelationship:
    def __init__(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        self.source_node = source_node
        self.target_node = target_node
        self.label = label
        self.relationship_kind = relationship_kind
        self.relationship_style = relationship_style
        self.canvas_item_ids = []


class UmlDiagramRegistry:
    def __init__(self):
        self.nodes_by_class_name = {}
        self.relationships = []

    def class_node_for(self, class_name):
        return self.nodes_by_class_name.get(class_name)

    def register_node(self, node):
        self.nodes_by_class_name[node.class_name] = node

    def remove_node(self, class_name):
        node = self.nodes_by_class_name.pop(class_name, None)
        if node is None:
            return []
        relationships_to_remove = []
        for relationship in self.relationships:
            touches_node = (
                relationship.source_node is node or relationship.target_node is node
            )
            if touches_node:
                relationships_to_remove.append(relationship)
        self.relationships = [
            relationship
            for relationship in self.relationships
            if relationship not in relationships_to_remove
        ]
        return relationships_to_remove

    def add_relationship(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        existing_relationship = None
        for relationship in self.relationships:
            is_same_relationship = (
                relationship.source_node is source_node
                and relationship.target_node is target_node
                and relationship.label == label
                and relationship.relationship_kind == relationship_kind
                and relationship.relationship_style == relationship_style
            )
            if is_same_relationship:
                existing_relationship = relationship
        if existing_relationship is not None:
            return None
        relationship = UmlRelationship(
            source_node,
            target_node,
            label,
            relationship_kind,
            relationship_style,
        )
        self.relationships.append(relationship)
        return relationship

    def remove_relationship(self, relationship):
        if relationship in self.relationships:
            self.relationships.remove(relationship)

    def remove_relationships_by_kind(self, relationship_kind):
        relationships_to_remove = []
        for relationship in self.relationships:
            if relationship.relationship_kind == relationship_kind:
                relationships_to_remove.append(relationship)
        self.relationships = [
            relationship
            for relationship in self.relationships
            if relationship.relationship_kind != relationship_kind
        ]
        return relationships_to_remove

    def all_nodes(self):
        return list(self.nodes_by_class_name.values())

    def all_relationships(self):
        return list(self.relationships)


class UmlCanvas(ttk.Frame):
    def __init__(self, parent, node_menu_action):
        super().__init__(parent)
        self.node_menu_action = node_menu_action
        self.registry = UmlDiagramRegistry()
        self.dragging_node = None
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.canvas = tk.Canvas(
            self,
            bg="white",
            scrollregion=(0, 0, 2000, 2000),
        )
        horizontal_scrollbar = ttk.Scrollbar(
            self,
            orient="horizontal",
            command=self.canvas.xview,
        )
        vertical_scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.canvas.configure(
            xscrollcommand=horizontal_scrollbar.set,
            yscrollcommand=vertical_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)

    def add_or_update_class_node(self, class_definition):
        class_name = class_definition.get("class_name") or ""
        if not class_name:
            return None
        node = self.registry.class_node_for(class_name)
        if node is None:
            node = UmlClassNode(class_definition)
            self.place_new_node(node)
            self.registry.register_node(node)
        else:
            node.update_from_definition(class_definition)
        self.redraw_node(node)
        self.expand_scroll_region()
        return node

    def place_new_node(self, node):
        existing_count = len(self.registry.all_nodes())
        column_index = existing_count % UML_NODES_PER_ROW
        row_index = existing_count // UML_NODES_PER_ROW
        node.x = (
            UML_ORIGIN_X
            + column_index * (UML_NODE_WIDTH + UML_NODE_PADDING_X)
            + UML_NODE_WIDTH // 2
        )
        node.y = (
            UML_ORIGIN_Y
            + row_index * (UML_NODE_MIN_HEIGHT + 100 + UML_NODE_PADDING_Y)
            + UML_NODE_MIN_HEIGHT // 2
        )

    def redraw_node(self, node):
        for item_id in node.canvas_item_ids:
            self.canvas.delete(item_id)
        node.canvas_item_ids = []
        self.draw_node(node)
        self.redraw_relationships_for_node(node)

    def draw_node(self, node):
        x1, y1, x2, y2 = node.bounding_box()
        rectangle_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill="#fff9e6",
            outline="#8a6d1f",
            width=2,
        )
        divider_y = y1 + UML_HEADER_HEIGHT
        divider_id = self.canvas.create_line(
            x1,
            divider_y,
            x2,
            divider_y,
            fill="#8a6d1f",
            width=2,
        )
        class_text_id = self.canvas.create_text(
            node.x,
            y1 + 7,
            text=node.class_name,
            font=("TkDefaultFont", 10, "bold"),
            fill="#533f05",
            anchor="n",
        )
        node.canvas_item_ids.extend([rectangle_id, divider_id, class_text_id])
        method_index = 0
        for method_entry in node.pinned_methods:
            method_y = divider_y + 8 + method_index * UML_METHOD_LINE_HEIGHT
            method_id = self.canvas.create_text(
                x1 + 8,
                method_y,
                text=method_entry["label"],
                font=("TkDefaultFont", 9),
                fill="#222222",
                anchor="nw",
            )
            node.canvas_item_ids.append(method_id)
            method_index += 1

    def edge_boundary_point(self, from_node, toward_node):
        delta_x = toward_node.x - from_node.x
        delta_y = toward_node.y - from_node.y
        half_width = UML_NODE_WIDTH / 2
        half_height = from_node.height() / 2
        if delta_x == 0 and delta_y == 0:
            return from_node.x + half_width, from_node.y
        scale_x = abs(half_width / delta_x) if delta_x != 0 else float("inf")
        scale_y = abs(half_height / delta_y) if delta_y != 0 else float("inf")
        scale = min(scale_x, scale_y)
        return from_node.x + delta_x * scale, from_node.y + delta_y * scale

    def draw_relationship(self, relationship):
        x1, y1 = self.edge_boundary_point(
            relationship.source_node,
            relationship.target_node,
        )
        x2, y2 = self.edge_boundary_point(
            relationship.target_node,
            relationship.source_node,
        )
        relationship.canvas_item_ids = []
        fill = "#444444"
        width = 1.5
        if relationship.relationship_kind == "inheritance":
            fill = "#2266aa"
            width = 2
            if relationship.relationship_style == "inferred":
                fill = "#9aa4b2"
        line_id = self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            arrow=tk.LAST,
            arrowshape=(12, 14, 6),
            fill=fill,
            width=width,
        )
        relationship.canvas_item_ids.append(line_id)
        should_draw_label = bool(relationship.label)
        if should_draw_label:
            midpoint_x = (x1 + x2) / 2
            midpoint_y = (y1 + y2) / 2
            label_id = self.canvas.create_text(
                midpoint_x,
                midpoint_y - 10,
                text=relationship.label,
                font=("TkDefaultFont", 9),
                fill="#222288",
                anchor="s",
            )
            relationship.canvas_item_ids.append(label_id)

    def redraw_relationships_for_node(self, node):
        for relationship in self.registry.all_relationships():
            touches_node = (
                relationship.source_node is node or relationship.target_node is node
            )
            if touches_node:
                self.delete_relationship_items(relationship)
                self.draw_relationship(relationship)

    def delete_relationship_items(self, relationship):
        for item_id in relationship.canvas_item_ids:
            self.canvas.delete(item_id)
        relationship.canvas_item_ids = []

    def delete_node_items(self, node):
        for item_id in node.canvas_item_ids:
            self.canvas.delete(item_id)
        node.canvas_item_ids = []

    def add_relationship(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        relationship = self.registry.add_relationship(
            source_node,
            target_node,
            label,
            relationship_kind,
            relationship_style,
        )
        if relationship is not None:
            self.draw_relationship(relationship)
            self.expand_scroll_region()
        return relationship

    def remove_relationship(self, relationship):
        self.delete_relationship_items(relationship)
        self.registry.remove_relationship(relationship)
        self.expand_scroll_region()

    def remove_class_node(self, class_name):
        node = self.registry.class_node_for(class_name)
        if node is None:
            return
        relationships_to_remove = self.registry.remove_node(class_name)
        for relationship in relationships_to_remove:
            self.delete_relationship_items(relationship)
        self.delete_node_items(node)
        self.expand_scroll_region()

    def node_at_canvas_coordinates(self, canvas_x, canvas_y):
        for node in self.registry.all_nodes():
            x1, y1, x2, y2 = node.bounding_box()
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                return node
        return None

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.dragging_node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y

    def on_canvas_drag(self, event):
        if self.dragging_node is None:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        delta_x = canvas_x - self.drag_start_x
        delta_y = canvas_y - self.drag_start_y
        for item_id in self.dragging_node.canvas_item_ids:
            self.canvas.move(item_id, delta_x, delta_y)
        self.dragging_node.x += delta_x
        self.dragging_node.y += delta_y
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y
        self.redraw_relationships_for_node(self.dragging_node)

    def on_canvas_release(self, event):
        self.dragging_node = None
        self.expand_scroll_region()

    def on_canvas_right_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        if node is None:
            return
        self.node_menu_action(node, event)

    def expand_scroll_region(self):
        all_nodes = self.registry.all_nodes()
        if not all_nodes:
            self.canvas.configure(scrollregion=(0, 0, 2000, 2000))
            return
        minimum_x = min(node.bounding_box()[0] for node in all_nodes) - UML_ORIGIN_X
        minimum_y = min(node.bounding_box()[1] for node in all_nodes) - UML_ORIGIN_Y
        maximum_x = max(node.bounding_box()[2] for node in all_nodes) + UML_ORIGIN_X
        maximum_y = max(node.bounding_box()[3] for node in all_nodes) + UML_ORIGIN_Y
        self.canvas.configure(
            scrollregion=(
                min(minimum_x, 0),
                min(minimum_y, 0),
                max(maximum_x, 2000),
                max(maximum_y, 2000),
            )
        )

    def clear_all(self):
        self.canvas.delete("all")
        self.registry = UmlDiagramRegistry()
        self.expand_scroll_region()


class UmlTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.current_context_menu = None
        self.diagram_history = NavigationHistory()

        actions_frame = ttk.Frame(self)
        actions_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        ttk.Label(actions_frame, text="UML Class Diagram").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(actions_frame, text="Clear", command=self.clear_diagram).grid(
            row=0,
            column=1,
            padx=(6, 0),
        )
        self.undo_button = ttk.Button(
            actions_frame,
            text="Undo",
            command=self.undo_diagram,
        )
        self.undo_button.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(
            actions_frame,
            text="Close",
            command=self.application.close_uml_tab,
        ).grid(row=0, column=3, padx=(6, 0))

        self.uml_canvas = UmlCanvas(
            self,
            node_menu_action=self.open_node_menu,
        )
        self.uml_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.uml_canvas.canvas.bind("<Control-z>", self.undo_diagram)
        self.uml_canvas.canvas.bind("<Control-Z>", self.undo_diagram)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.record_diagram_snapshot()
        self.refresh_undo_controls()

    def snapshot_diagram(self):
        nodes = []
        for node in self.uml_canvas.registry.all_nodes():
            nodes.append(
                {
                    "class_name": node.class_name,
                    "superclass_name": node.superclass_name,
                    "inst_var_names": list(node.inst_var_names),
                    "pinned_methods": [dict(method_entry) for method_entry in node.pinned_methods],
                    "x": node.x,
                    "y": node.y,
                }
            )
        relationships = []
        for relationship in self.uml_canvas.registry.all_relationships():
            relationships.append(
                {
                    "source_class_name": relationship.source_node.class_name,
                    "target_class_name": relationship.target_node.class_name,
                    "label": relationship.label,
                    "relationship_kind": relationship.relationship_kind,
                    "relationship_style": relationship.relationship_style,
                }
            )
        return {
            "nodes": sorted(nodes, key=lambda entry: entry["class_name"]),
            "relationships": sorted(
                relationships,
                key=lambda entry: (
                    entry["relationship_kind"],
                    entry["relationship_style"],
                    entry["source_class_name"],
                    entry["target_class_name"],
                    entry["label"],
                ),
            ),
        }

    def restore_diagram_snapshot(self, snapshot):
        self.uml_canvas.clear_all()
        node_by_class_name = {}
        for node_entry in snapshot["nodes"]:
            class_definition = {
                "class_name": node_entry["class_name"],
                "superclass_name": node_entry["superclass_name"],
                "inst_var_names": list(node_entry["inst_var_names"]),
            }
            node = self.uml_canvas.add_or_update_class_node(class_definition)
            node.pinned_methods = [
                dict(method_entry) for method_entry in node_entry["pinned_methods"]
            ]
            node.x = node_entry["x"]
            node.y = node_entry["y"]
            self.uml_canvas.redraw_node(node)
            node_by_class_name[node.class_name] = node
        for relationship_entry in snapshot["relationships"]:
            source_node = node_by_class_name.get(relationship_entry["source_class_name"])
            target_node = node_by_class_name.get(relationship_entry["target_class_name"])
            if source_node is None or target_node is None:
                continue
            self.uml_canvas.add_relationship(
                source_node,
                target_node,
                relationship_entry["label"],
                relationship_entry["relationship_kind"],
                relationship_entry["relationship_style"],
            )
        self.uml_canvas.expand_scroll_region()

    def record_diagram_snapshot(self):
        self.diagram_history.record(self.snapshot_diagram())
        self.refresh_undo_controls()

    def refresh_undo_controls(self):
        undo_state = tk.NORMAL if self.diagram_history.can_go_back() else tk.DISABLED
        self.undo_button.configure(state=undo_state)

    def class_definition_for(self, class_name, show_errors=True):
        browser_session = self.application.gemstone_session_record.gemstone_browser_session
        try:
            return browser_session.get_class_definition(class_name)
        except (GemstoneDomainException, GemstoneError) as error:
            if show_errors:
                messagebox.showerror("UML", str(error))
            return None

    def add_class(self, class_name, record_history=True):
        class_definition = self.class_definition_for(class_name)
        if class_definition is None:
            return None
        snapshot_before = self.snapshot_diagram()
        node = self.uml_canvas.add_or_update_class_node(class_definition)
        self.refresh_inheritance_relationships()
        snapshot_after = self.snapshot_diagram()
        if record_history and snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        return node

    def pin_method(self, class_name, show_instance_side, method_selector):
        snapshot_before = self.snapshot_diagram()
        node = self.add_class(class_name, record_history=False)
        if node is None:
            return
        method_label = uml_method_label(show_instance_side, method_selector)
        existing_method = None
        for method_entry in node.pinned_methods:
            is_same_method = (
                method_entry["selector"] == method_selector
                and method_entry["show_instance_side"] == show_instance_side
            )
            if is_same_method:
                existing_method = method_entry
        if existing_method is None:
            node.pinned_methods.append(
                {
                    "selector": method_selector,
                    "show_instance_side": show_instance_side,
                    "label": method_label,
                }
            )
            self.uml_canvas.redraw_node(node)
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()

    def open_node_menu(self, node, event):
        if self.current_context_menu is not None:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Browse Class",
            command=lambda: self.browse_class(node.class_name),
        )
        menu.add_command(
            label="Add Method...",
            command=lambda: self.open_add_method_dialog(node),
        )

        browse_method_menu = tk.Menu(menu, tearoff=0)
        has_pinned_methods = len(node.pinned_methods) > 0
        if has_pinned_methods:
            for method_entry in node.pinned_methods:
                browse_method_menu.add_command(
                    label=method_entry["label"],
                    command=lambda entry=method_entry: self.browse_method(
                        node.class_name,
                        entry,
                    ),
                )
            menu.add_cascade(label="Browse Method...", menu=browse_method_menu)
        if not has_pinned_methods:
            menu.add_command(
                label="Browse Method...",
                state=tk.DISABLED,
            )

        menu.add_separator()

        association_menu = tk.Menu(menu, tearoff=0)
        has_instvars = len(node.inst_var_names) > 0
        if has_instvars:
            for inst_var_name in node.inst_var_names:
                association_menu.add_command(
                    label=inst_var_name,
                    command=lambda name=inst_var_name: self.prompt_add_association(
                        node,
                        name,
                    ),
                )
            menu.add_cascade(label="Add Association...", menu=association_menu)
        if not has_instvars:
            menu.add_command(
                label="Add Association...",
                state=tk.DISABLED,
            )

        remove_method_menu = tk.Menu(menu, tearoff=0)
        if has_pinned_methods:
            for method_entry in node.pinned_methods:
                remove_method_menu.add_command(
                    label=method_entry["label"],
                    command=lambda entry=method_entry: self.remove_method_from_node(
                        node,
                        entry,
                    ),
                )
            menu.add_cascade(label="Remove Method...", menu=remove_method_menu)
        if not has_pinned_methods:
            menu.add_command(
                label="Remove Method...",
                state=tk.DISABLED,
            )

        menu.add_command(
            label="Remove From UML",
            command=lambda: self.remove_class_from_diagram(node.class_name),
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def browse_class(self, class_name):
        self.application.handle_find_selection(True, class_name)
        if self.application.browser_tab is not None and self.application.browser_tab.winfo_exists():
            self.application.notebook.select(self.application.browser_tab)

    def browse_method(self, class_name, method_entry):
        self.application.handle_sender_selection(
            class_name,
            method_entry["show_instance_side"],
            method_entry["selector"],
        )
        if self.application.browser_tab is not None and self.application.browser_tab.winfo_exists():
            self.application.notebook.select(self.application.browser_tab)

    def add_existing_method_to_node(self, class_name, show_instance_side, method_selector):
        self.pin_method(
            class_name,
            show_instance_side,
            method_selector,
        )

    def open_add_method_dialog(self, node):
        UmlMethodChooserDialog(
            self,
            self.application,
            node.class_name,
            self.add_existing_method_to_node,
        )

    def prompt_add_association(self, source_node, inst_var_name):
        target_class_name = simpledialog.askstring(
            "Add UML Association",
            f"Target class for {source_node.class_name}>>{inst_var_name}:",
            parent=self,
        )
        if target_class_name is None:
            return
        target_class_name = target_class_name.strip()
        if not target_class_name:
            return
        snapshot_before = self.snapshot_diagram()
        target_node = self.add_class(target_class_name, record_history=False)
        if target_node is None:
            return
        self.uml_canvas.add_relationship(
            source_node,
            target_node,
            inst_var_name,
            "association",
        )
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()

    def remove_method_from_node(self, node, method_entry):
        node.pinned_methods = [
            existing_entry
            for existing_entry in node.pinned_methods
            if existing_entry is not method_entry
        ]
        self.uml_canvas.redraw_node(node)
        self.record_diagram_snapshot()

    def remove_class_from_diagram(self, class_name):
        snapshot_before = self.snapshot_diagram()
        self.uml_canvas.remove_class_node(class_name)
        self.refresh_inheritance_relationships()
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()

    def refresh_inheritance_relationships(self):
        relationships_to_remove = self.uml_canvas.registry.remove_relationships_by_kind(
            "inheritance"
        )
        for relationship in relationships_to_remove:
            self.uml_canvas.delete_relationship_items(relationship)
        for node in self.uml_canvas.registry.all_nodes():
            superclass_name = node.superclass_name
            ancestor_distance = 1
            while superclass_name:
                superclass_node = self.uml_canvas.registry.class_node_for(superclass_name)
                relationship_style = "direct"
                if ancestor_distance > 1:
                    relationship_style = "inferred"
                if superclass_node is not None:
                    self.uml_canvas.add_relationship(
                        node,
                        superclass_node,
                        "",
                        "inheritance",
                        relationship_style,
                    )
                superclass_definition = self.class_definition_for(
                    superclass_name, show_errors=False
                )
                if superclass_definition is None:
                    superclass_name = None
                else:
                    superclass_name = superclass_definition["superclass_name"]
                    ancestor_distance += 1
        self.uml_canvas.expand_scroll_region()

    def clear_diagram(self):
        snapshot_before = self.snapshot_diagram()
        self.uml_canvas.clear_all()
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()

    def undo_diagram(self, event=None):
        snapshot = self.diagram_history.go_back()
        if snapshot is None:
            self.refresh_undo_controls()
            return
        self.restore_diagram_snapshot(snapshot)
        self.refresh_undo_controls()


class DebuggerWindow(ttk.PanedWindow):
    def __init__(
        self, parent, application, gemstone_session_record, event_queue, exception
    ):
        super().__init__(
            parent, orient=tk.VERTICAL
        )  # Make DebuggerWindow a vertical paned window

        self.application = application
        self.exception = exception
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record

        # Create top and bottom frames to act as rows in the PanedWindow
        self.call_stack_frame = ttk.Frame(self)
        self.code_panel_frame = ttk.Frame(self)
        self.explorer_frame = ttk.Frame(self)

        # Add frames to the PanedWindow with equal weights
        self.add(self.call_stack_frame, weight=1)
        self.add(self.code_panel_frame, weight=1)
        self.add(self.explorer_frame, weight=1)

        # Add DebuggerControls to the top of the call_stack_frame
        self.debugger_controls = DebuggerControls(
            self.call_stack_frame, self, self.event_queue
        )
        self.debugger_controls.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.close_button = self.debugger_controls.close_button

        # Add a Treeview widget to the top frame, below DebuggerControls, to represent the three-column list
        self.listbox = ttk.Treeview(
            self.call_stack_frame,
            columns=("Level", "Column1", "Column2"),
            show="headings",
        )
        self.listbox.heading("Level", text="Level")
        self.listbox.heading("Column1", text="Class Name")
        self.listbox.heading("Column2", text="Method Name")
        self.listbox.grid(row=1, column=0, sticky="nsew")

        self.debug_session = GemstoneDebugSession(self.exception)
        self.stack_frames = self.debug_session.call_stack()

        # Bind item selection to method execution
        self.listbox.bind("<ButtonRelease-1>", self.on_listbox_select)
        self.listbox.bind("<Double-1>", self.open_method_from_selected_frame)

        # Add a Text widget to the bottom frame (text editor)
        self.code_panel = CodePanel(self.code_panel_frame, application=application)
        self.code_panel.grid(row=0, column=0, sticky="nsew")

        # Configure grid in call_stack_frame, code_panel_frame, and explorer_frame for proper resizing
        self.call_stack_frame.columnconfigure(0, weight=1)
        self.call_stack_frame.rowconfigure(1, weight=1)

        self.code_panel_frame.columnconfigure(0, weight=1)
        self.code_panel_frame.rowconfigure(0, weight=1)

        self.explorer_frame.columnconfigure(0, weight=1)
        self.explorer_frame.rowconfigure(0, weight=1)

        # Make the parent window expand correctly
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Ensure DebuggerWindow itself expands within its parent
        self.grid(row=0, column=0, sticky="nsew")

        self.refresh()

    @property
    def is_running(self):
        return bool(self.stack_frames)

    def refresh(self):
        # Clear the existing contents of the listbox
        for item in self.listbox.get_children():
            self.listbox.delete(item)

        # Re-populate the listbox with updated stack frames
        for frame in self.stack_frames:
            iid = str(frame.level)
            self.listbox.insert(
                "",
                "end",
                iid=iid,
                values=(frame.level, frame.class_name, frame.method_name),
            )

        # Select the first entry in the listbox by iid
        if self.stack_frames:
            first_frame = next(iter(self.stack_frames))
            first_iid = str(first_frame.level)
            self.listbox.selection_set(first_iid)
            self.listbox.focus(first_iid)
            self.code_panel.refresh(
                first_frame.method_source,
                mark=first_frame.step_point_offset,
            )
            self.refresh_explorer(first_frame)

    def refresh_explorer(self, frame):
        # Clear existing widgets in the explorer_frame
        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        # Create an Explorer widget in the explorer_frame
        explorer = Explorer(
            self.explorer_frame,
            frame,
            values=dict([("self", frame.self)] + list(frame.vars.items())),
            root_tab_label="Context",
            external_inspect_action=self.application.open_inspector_for_object,
            graph_inspect_action=self.application.open_graph_inspector_for_object,
        )
        self.explorer = explorer
        explorer.grid(row=0, column=0, sticky="nsew")

    def on_listbox_select(self, event):
        frame = self.get_selected_stack_frame()
        if frame:
            self.code_panel.refresh(frame.method_source, mark=frame.step_point_offset)
            self.refresh_explorer(frame)

    def open_method_from_selected_frame(self, event):
        self.open_selected_frame_method()

    def stack_frame_for_level(self, level):
        for frame in self.stack_frames:
            if frame.level == level:
                return frame
        return None

    def get_selected_stack_frame(self):
        selected_items = self.listbox.selection()
        selected_item = None
        if selected_items:
            selected_item = selected_items[0]
        if selected_item is None:
            selected_item = self.listbox.focus()
        if selected_item:
            try:
                selected_level = int(selected_item)
            except ValueError:
                return None
            return self.stack_frame_for_level(selected_level)
        return None

    def value_for_named_local_on_frame(self, frame, variable_name):
        frame_vars = frame.vars
        if variable_name in frame_vars:
            return True, frame_vars[variable_name]
        return False, None

    def value_for_named_instance_variable_on_frame_self(self, frame, variable_name):
        frame_self = getattr(frame, "self", None)
        if frame_self is None:
            return False, None
        inst_var_names = []
        try:
            inst_var_names = list(frame_self.gemstone_class().allInstVarNames())
        except (GemstoneError, AttributeError):
            return False, None
        for one_based_index, inst_var_name in enumerate(inst_var_names, start=1):
            candidate_name = ""
            try:
                candidate_name = inst_var_name.to_py
            except AttributeError:
                candidate_name = str(inst_var_name)
            names_match = candidate_name == variable_name
            if names_match:
                value = None
                value_found = False
                try:
                    value = frame_self.instVarNamed(inst_var_name)
                    value_found = True
                except GemstoneError:
                    pass
                if not value_found:
                    try:
                        value = frame_self.instVarAt(one_based_index)
                        value_found = True
                    except GemstoneError:
                        pass
                if value_found:
                    return True, value
        return False, None

    def value_for_source_expression(self, frame, source_expression):
        expression = source_expression.strip()
        if expression == "self":
            return frame.self
        local_value_found, local_value = self.value_for_named_local_on_frame(
            frame,
            expression,
        )
        if local_value_found:
            return local_value
        instvar_value_found, instvar_value = (
            self.value_for_named_instance_variable_on_frame_self(
                frame,
                expression,
            )
        )
        if instvar_value_found:
            return instvar_value
        return frame.gemstone_session.execute(
            expression,
            context=frame.var_context,
        )

    def inspect_selected_source_expression(self, source_expression):
        expression = source_expression.strip()
        if not expression:
            messagebox.showwarning(
                "No Selection",
                "Select source text in the debugger method pane to inspect it.",
            )
            return
        frame = self.get_selected_stack_frame()
        if frame is None:
            messagebox.showwarning(
                "No Stack Frame",
                "Select a stack frame before inspecting source text.",
            )
            return
        try:
            inspected_object = self.value_for_source_expression(
                frame,
                expression,
            )
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Inspect Expression", str(error))
            return
        self.application.open_inspector_for_object(inspected_object)

    def graph_inspect_selected_source_expression(self, source_expression):
        expression = source_expression.strip()
        if not expression:
            messagebox.showwarning(
                "No Selection",
                "Select source text in the debugger method pane to inspect it.",
            )
            return
        frame = self.get_selected_stack_frame()
        if frame is None:
            messagebox.showwarning(
                "No Stack Frame",
                "Select a stack frame before inspecting source text.",
            )
            return
        try:
            inspected_object = self.value_for_source_expression(
                frame,
                expression,
            )
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Inspect Expression", str(error))
            return
        self.application.open_graph_inspector_for_object(inspected_object)

    def frame_method_context(self, frame):
        if frame is None:
            return None
        class_name = frame.class_name
        show_instance_side = True
        class_side_suffix = " class"
        if class_name.endswith(class_side_suffix):
            class_name = class_name[: -len(class_side_suffix)]
            show_instance_side = False
        if not class_name or not frame.method_name:
            return None
        return class_name, show_instance_side, frame.method_name

    def open_selected_frame_method(self):
        frame = self.get_selected_stack_frame()
        method_context = self.frame_method_context(frame)
        if method_context is None:
            return
        class_name, show_instance_side, method_name = method_context
        try:
            self.application.handle_sender_selection(
                class_name,
                show_instance_side,
                method_name,
            )
            if self.application.browser_tab:
                self.application.notebook.select(self.application.browser_tab)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror("Browse Frame Method", str(error))

    def selected_frame_level(self):
        frame = self.get_selected_stack_frame()
        if frame:
            return frame.level
        return None

    def apply_debug_action_outcome(self, action_outcome):
        self.stack_frames = self.debug_session.call_stack()
        if action_outcome.has_completed:
            self.finish(action_outcome.result)
        else:
            self.refresh()

    def continue_running(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.continue_running()
            self.apply_debug_action_outcome(action_outcome)

    def step_over(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_over(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def step_into(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_into(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def step_through(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.step_through(frame_level)
            self.apply_debug_action_outcome(action_outcome)

    def restart_frame(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            outcome = self.debug_session.restart_frame(frame_level)
            self.apply_debug_action_outcome(outcome)

    def stop(self):
        frame_level = self.selected_frame_level()
        if frame_level:
            action_outcome = self.debug_session.stop()
            if action_outcome.has_completed:
                self.dismiss()
            else:
                self.stack_frames = self.debug_session.call_stack()
                self.refresh()

    def dismiss(self):
        self.stack_frames = None
        if self.application.debugger_tab is self:
            self.application.debugger_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()

    def finish(self, result):
        self.stack_frames = None

        # Remove existing frames from the PanedWindow
        self.forget(self.call_stack_frame)
        self.forget(self.code_panel_frame)
        self.forget(self.explorer_frame)

        self.finished_frame = ttk.Frame(self)
        self.finished_frame.columnconfigure(0, weight=1)
        self.finished_frame.rowconfigure(1, weight=1)
        self.add(self.finished_frame, weight=1)

        self.finished_actions = ttk.Frame(self.finished_frame)
        self.finished_actions.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        self.finished_actions.columnconfigure(0, weight=1)

        self.close_button = ttk.Button(
            self.finished_actions,
            text="Close",
            command=self.dismiss,
        )
        self.close_button.grid(row=0, column=1, sticky="e")

        self.result_text = tk.Text(self.finished_frame)
        self.result_text.insert("1.0", result.asString().to_py)
        self.result_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=(5, 5))


class DebuggerControls(ttk.Frame):
    def __init__(self, parent, debugger, event_queue):
        super().__init__(parent)
        self.debugger = debugger
        self.event_queue = event_queue

        # Create buttons for Debugger Controls
        self.continue_button = ttk.Button(
            self, text="Continue", command=self.handle_continue
        )
        self.continue_button.grid(row=0, column=0, padx=5, pady=5)

        self.over_button = ttk.Button(self, text="Over", command=self.handle_over)
        self.over_button.grid(row=0, column=1, padx=5, pady=5)

        self.into_button = ttk.Button(self, text="Into", command=self.handle_into)
        self.into_button.grid(row=0, column=2, padx=5, pady=5)

        self.through_button = ttk.Button(
            self, text="Through", command=self.handle_through
        )
        self.through_button.grid(row=0, column=3, padx=5, pady=5)

        self.restart_button = ttk.Button(
            self, text="Restart", command=self.handle_restart
        )
        self.restart_button.grid(row=0, column=4, padx=5, pady=5)

        self.stop_button = ttk.Button(self, text="Stop", command=self.handle_stop)
        self.stop_button.grid(row=0, column=5, padx=5, pady=5)

        self.browse_button = ttk.Button(
            self,
            text="Browse Method",
            command=self.handle_browse,
        )
        self.browse_button.grid(row=0, column=6, padx=5, pady=5)

        self.columnconfigure(7, weight=1)
        self.close_button = ttk.Button(
            self,
            text="Close",
            command=self.handle_close,
        )
        self.close_button.grid(row=0, column=8, padx=5, pady=5, sticky="e")

    def handle_continue(self):
        self.debugger.continue_running()

    def handle_over(self):
        self.debugger.step_over()

    def handle_into(self):
        self.debugger.step_into()

    def handle_through(self):
        self.debugger.step_through()

    def handle_restart(self):
        self.debugger.restart_frame()

    def handle_stop(self):
        self.debugger.stop()

    def handle_browse(self):
        self.debugger.open_selected_frame_method()

    def handle_close(self):
        self.debugger.dismiss()


class LoginFrame(ttk.Frame):
    def __init__(self, parent, default_stone_name="gs64stone"):
        super().__init__(parent)
        self.parent = parent
        self.error_label = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        self.form_frame = ttk.Frame(self, padding=24)
        self.form_frame.grid(
            row=0,
            column=0,
            sticky="n",
            padx=20,
            pady=20,
        )
        self.form_frame.columnconfigure(0, weight=0)
        self.form_frame.columnconfigure(1, weight=1)

        ttk.Label(
            self.form_frame,
            text="Connect to GemStone",
        ).grid(
            column=0,
            row=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )

        # Username label and entry
        ttk.Label(self.form_frame, text="Username:").grid(
            column=0,
            row=1,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.username_entry = ttk.Entry(self.form_frame)
        self.username_entry.insert(0, "DataCurator")
        self.username_entry.grid(column=1, row=1, sticky="ew", pady=2)

        # Password label and entry
        ttk.Label(self.form_frame, text="Password:").grid(
            column=0,
            row=2,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.password_entry = ttk.Entry(self.form_frame, show="*")
        self.password_entry.insert(0, "swordfish")
        self.password_entry.grid(column=1, row=2, sticky="ew", pady=2)

        ttk.Label(self.form_frame, text="Stone name:").grid(
            column=0,
            row=3,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.stone_name_entry = ttk.Entry(self.form_frame)
        self.stone_name_entry.insert(0, default_stone_name)
        self.stone_name_entry.grid(column=1, row=3, sticky="ew", pady=2)

        # Remote checkbox
        self.remote_var = tk.BooleanVar()
        self.remote_checkbox = ttk.Checkbutton(
            self.form_frame,
            text="Login RPC?",
            variable=self.remote_var,
            command=self.toggle_remote_widgets,
        )
        self.remote_checkbox.grid(
            column=0,
            row=4,
            columnspan=2,
            sticky="w",
            pady=(8, 2),
        )

        # Remote widgets (initially hidden)
        self.netldi_name_label = ttk.Label(self.form_frame, text="Netldi name:")
        self.netldi_name_entry = ttk.Entry(self.form_frame)
        self.netldi_name_entry.insert(0, "gs64-ldi")

        self.rpc_hostname_label = ttk.Label(self.form_frame, text="RPC host name:")
        self.rpc_hostname_entry = ttk.Entry(self.form_frame)
        self.rpc_hostname_entry.insert(0, "localhost")

        # Login button
        ttk.Button(self.form_frame, text="Login", command=self.attempt_login).grid(
            column=1,
            row=8,
            sticky="e",
            pady=(10, 0),
        )

    @property
    def login_rpc(self):
        return self.remote_var.get()

    def toggle_remote_widgets(self):
        if self.remote_var.get():
            # Show the remote widgets
            self.netldi_name_label.grid(
                column=0,
                row=5,
                sticky="e",
                padx=(0, 8),
                pady=2,
            )
            self.netldi_name_entry.grid(column=1, row=5, sticky="ew", pady=2)
            self.rpc_hostname_label.grid(
                column=0,
                row=6,
                sticky="e",
                padx=(0, 8),
                pady=2,
            )
            self.rpc_hostname_entry.grid(column=1, row=6, sticky="ew", pady=2)
        else:
            # Hide the remote widgets
            self.netldi_name_label.grid_remove()
            self.netldi_name_entry.grid_remove()
            self.rpc_hostname_label.grid_remove()
            self.rpc_hostname_entry.grid_remove()

    def attempt_login(self):
        if self.error_label:
            self.error_label.destroy()

        username = self.username_entry.get()
        password = self.password_entry.get()
        stone_name = self.stone_name_entry.get()
        netldi_name = self.netldi_name_entry.get()
        rpc_hostname = self.rpc_hostname_entry.get()
        try:
            if self.login_rpc:
                gemstone_session_record = GemstoneSessionRecord.log_in_rpc(
                    username, password, rpc_hostname, stone_name, netldi_name
                )
            else:
                gemstone_session_record = GemstoneSessionRecord.log_in_linked(
                    username, password, stone_name
                )
            self.parent.event_queue.publish(
                "LoggedInSuccessfully", gemstone_session_record
            )
        except DomainException as ex:
            self.error_label = ttk.Label(
                self.form_frame,
                text=str(ex),
                foreground="red",
            )
            self.error_label.grid(
                column=0,
                row=7,
                columnspan=2,
                sticky="w",
                pady=(8, 0),
            )


if __name__ == "__main__":
    Swordfish.run()
