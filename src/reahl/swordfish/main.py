#!/var/local/gemstone/venv/wonka/bin/python

import argparse
import asyncio
from collections import deque
import json
import logging
import os
import re
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
import weakref
from tkinter import ttk

from reahl.ptongue import GemstoneError, LinkedSession, RPCSession
from reahl.swordfish.gemstone import GemstoneBrowserSession
from reahl.swordfish.gemstone import GemstoneDebugSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.mcp.integration_state import current_integrated_session_state
from reahl.swordfish.mcp.server import create_server
from reahl.swordfish.mcp.server import McpDependencyNotInstalled


class DomainException(Exception):
    pass


def selected_range_in_text_widget(text_widget):
    start_index = None
    end_index = None
    try:
        start_index = text_widget.index(tk.SEL_FIRST)
        end_index = text_widget.index(tk.SEL_LAST)
    except tk.TclError:
        pass
    return start_index, end_index


def delete_selected_range_in_text_widget(text_widget):
    start_index, end_index = selected_range_in_text_widget(text_widget)
    if start_index is None:
        return False
    text_widget.mark_set(tk.INSERT, start_index)
    text_widget.delete(start_index, end_index)
    return True


def select_all_in_text_widget(text_widget):
    text_widget.tag_add(tk.SEL, '1.0', 'end-1c')
    text_widget.mark_set(tk.INSERT, '1.0')
    text_widget.see(tk.INSERT)


def copy_selection_from_text_widget(clipboard_owner, text_widget):
    start_index, end_index = selected_range_in_text_widget(text_widget)
    if start_index is None:
        return
    selected_text = text_widget.get(start_index, end_index)
    clipboard_owner.clipboard_clear()
    clipboard_owner.clipboard_append(selected_text)


def clipboard_text_from_widget(clipboard_owner):
    clipboard_text = None
    try:
        clipboard_text = clipboard_owner.clipboard_get()
    except tk.TclError:
        pass
    return clipboard_text


def paste_text_into_widget(clipboard_owner, text_widget):
    clipboard_text = clipboard_text_from_widget(clipboard_owner)
    if clipboard_text is None:
        return
    autoseparators_enabled = True
    can_configure_autoseparators = True
    try:
        autoseparators_value = text_widget.cget('autoseparators')
        autoseparators_enabled = bool(int(autoseparators_value))
    except (tk.TclError, TypeError, ValueError):
        can_configure_autoseparators = False

    if can_configure_autoseparators:
        text_widget.configure(autoseparators=False)
    text_widget.edit_separator()
    delete_selected_range_in_text_widget(text_widget)
    text_widget.insert(tk.INSERT, clipboard_text)
    text_widget.edit_separator()
    if can_configure_autoseparators and autoseparators_enabled:
        text_widget.configure(autoseparators=True)


def undo_text_widget_edit(text_widget):
    try:
        text_widget.edit_undo()
    except tk.TclError:
        pass


def control_key_pressed_for_event(event):
    return bool(event.state & 0x4)


def replace_selected_range_before_typing(text_widget, event):
    if control_key_pressed_for_event(event):
        return
    inserts_character = bool(event.char)
    inserts_control_character = event.keysym in ('Return', 'KP_Enter', 'Tab')
    if inserts_character or inserts_control_character:
        delete_selected_range_in_text_widget(text_widget)


class CodeLineNumberColumn:
    def __init__(self, parent, text_widget, external_yscrollcommand=None):
        self.parent = parent
        self.text_widget = text_widget
        self.external_yscrollcommand = external_yscrollcommand
        self.line_numbers_text = tk.Text(
            parent,
            width=4,
            wrap='none',
            padx=6,
            takefocus=0,
            state='disabled',
            borderwidth=0,
            highlightthickness=0,
            background='#f2f2f2',
            foreground='#666666',
            cursor='arrow',
        )
        self.line_numbers_text.tag_configure(
            'line_number_alignment',
            justify='right',
        )
        self.line_numbers_text.bind('<MouseWheel>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-4>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-5>', self.scroll_main_text)
        self.line_numbers_text.bind('<Button-1>', self.ignore_mouse_click)

        self.text_widget.bind('<<Modified>>', self.on_text_modified, add='+')
        self.text_widget.bind('<Configure>', self.refresh_line_numbers, add='+')
        self.text_widget.bind('<KeyRelease>', self.refresh_line_numbers, add='+')
        self.text_widget.bind('<ButtonRelease-1>', self.refresh_line_numbers, add='+')
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
        return 'break'

    def scroll_units_for_event(self, event):
        mouse_delta = 0
        if hasattr(event, 'delta'):
            mouse_delta = event.delta
        if mouse_delta > 0:
            return -1
        if mouse_delta < 0:
            return 1
        button_number = getattr(event, 'num', None)
        if button_number == 4:
            return -1
        if button_number == 5:
            return 1
        return 0

    def scroll_main_text(self, event):
        scroll_units = self.scroll_units_for_event(event)
        if scroll_units == 0:
            return None
        self.text_widget.yview_scroll(scroll_units, 'units')
        self.sync_scroll_position()
        return 'break'

    def on_text_scrolled(self, first_fraction, last_fraction):
        self.line_numbers_text.yview_moveto(first_fraction)
        if self.external_yscrollcommand:
            self.external_yscrollcommand(first_fraction, last_fraction)

    def line_count(self):
        line_number = int(self.text_widget.index('end-1c').split('.')[0])
        if line_number < 1:
            return 1
        return line_number

    def line_number_text_for_count(self, line_count):
        line_numbers = []
        for line_number in range(1, line_count + 1):
            line_numbers.append(str(line_number))
        return '\n'.join(line_numbers)

    def sync_scroll_position(self):
        first_fraction, _ = self.text_widget.yview()
        self.line_numbers_text.yview_moveto(first_fraction)

    def refresh_line_numbers(self, event=None):
        line_count = self.line_count()
        line_number_text = self.line_number_text_for_count(line_count)
        self.line_numbers_text.configure(state='normal')
        self.line_numbers_text.delete('1.0', tk.END)
        self.line_numbers_text.insert(
            '1.0',
            line_number_text,
            'line_number_alignment',
        )
        self.line_numbers_text.configure(
            width=max(3, len(str(line_count)) + 1),
        )
        self.line_numbers_text.configure(state='disabled')
        self.sync_scroll_position()


class TextCursorPositionIndicator:
    def __init__(self, text_widget, label_widget):
        self.text_widget = text_widget
        self.label_widget = label_widget
        self.text_widget.bind('<KeyRelease>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-1>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-2>', self.update_position, add='+')
        self.text_widget.bind('<ButtonRelease-3>', self.update_position, add='+')
        self.text_widget.bind('<FocusIn>', self.update_position, add='+')
        self.update_position()

    def line_and_column(self):
        try:
            line_text, zero_based_column_text = self.text_widget.index(
                tk.INSERT
            ).split('.')
            line_number = int(line_text)
            one_based_column_number = int(zero_based_column_text) + 1
            return line_number, one_based_column_number
        except (tk.TclError, ValueError):
            return None, None

    def update_position(self, event=None):
        line_number, column_number = self.line_and_column()
        if line_number is None or column_number is None:
            self.label_widget.config(text='Ln -, Col -')
            return
        self.label_widget.config(
            text=f'Ln {line_number}, Col {column_number}'
        )


class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.gemstone_browser_session = GemstoneBrowserSession(gemstone_session)
        self.change_event_publisher = None
        self.integrated_session_state = None
        self.selected_package = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.show_instance_side = True

    def set_integrated_session_state(self, integrated_session_state):
        self.integrated_session_state = integrated_session_state

    def require_write_access(self, operation_name):
        if self.integrated_session_state is None:
            return
        if not self.integrated_session_state.is_mcp_busy():
            return
        mcp_operation_name = (
            self.integrated_session_state.current_mcp_operation_name()
            or 'unknown'
        )
        raise DomainException(
            (
                'IDE is read-only while MCP operation %s is active. '
                'Retry %s after MCP finishes.'
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
        self.require_write_access('commit')
        self.gemstone_session.commit()
        
    def abort(self):
        self.require_write_access('abort')
        self.gemstone_session.abort()
        
    @classmethod
    def log_in_rpc(cls, gemstone_user_name, gemstone_password, rpc_hostname, stone_name, netldi_name):
        nrs_string = f'!@{rpc_hostname}#netldi:{netldi_name}!gemnetobject'
        logging.getLogger(__name__).debug(f'Logging in with: {gemstone_user_name} stone_name={stone_name} netldi_task={nrs_string}')
        try:
            gemstone_session = RPCSession(gemstone_user_name, gemstone_password, stone_name=stone_name, netldi_task=nrs_string)
        except GemstoneError as e:
            raise DomainException('Gemstone error: %s' % e)
        return cls(gemstone_session)

    @classmethod
    def log_in_linked(cls, gemstone_user_name, gemstone_password, stone_name):
        logging.getLogger(__name__).debug(f'Logging in with: {gemstone_user_name} stone_name={stone_name}')
        try:
            gemstone_session = LinkedSession(gemstone_user_name, gemstone_password, stone_name=stone_name)
        except GemstoneError as e:
            raise DomainException('Gemstone error: %s' % e)
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
        return self.gemstone_session.execute('System session').to_py        

    def __str__(self):
        return f'{self.session_id}: {self.user_name} on {self.stone_name} at server {self.host_name}'

    def log_out(self):
        self.gemstone_session.log_out()

    @property
    def class_organizer(self):
        return self.gemstone_browser_session.class_organizer

    @property
    def class_categories(self):
        yield from self.gemstone_browser_session.list_packages()

    def create_and_install_package(self, package_name):
        self.require_write_access('create_and_install_package')
        self.gemstone_browser_session.create_and_install_package(package_name)
        self.publish_model_change('packages')

    def delete_package(self, package_name):
        self.require_write_access('delete_package')
        self.gemstone_browser_session.delete_package(package_name)
        if self.selected_package == package_name:
            self.selected_package = None
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change('packages')

    def create_class(
        self,
        class_name,
        superclass_name='Object',
        in_dictionary=None,
    ):
        self.require_write_access('create_class')
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            selected_dictionary = self.selected_package or 'UserGlobals'
        self.gemstone_browser_session.create_class(
            class_name=class_name,
            superclass_name=superclass_name,
            in_dictionary=selected_dictionary,
        )
        self.publish_model_change('classes')

    def delete_class(self, class_name, in_dictionary=None):
        self.require_write_access('delete_class')
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            selected_dictionary = self.selected_package or 'UserGlobals'
        self.gemstone_browser_session.delete_class(
            class_name,
            in_dictionary=selected_dictionary,
        )
        if self.selected_class == class_name:
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change('classes')
        
    def get_classes_in_category(self, category):
        yield from self.gemstone_browser_session.list_classes(category)
        
    def get_categories_in_class(self, class_name, show_instance_side):
        categories = self.gemstone_browser_session.list_method_categories(
            class_name,
            show_instance_side,
        )
        if categories and categories[0] == 'all':
            categories = categories[1:]
        yield from categories

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

    def jump_to_class(self, class_name, show_instance_side):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_package = selected_gemstone_class.category().to_py
        self.select_package(selected_package)
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
        return list(self.get_selectors_in_class(self.selected_class, self.selected_method_category, self.show_instance_side))
        
    def find_class_names_matching(self, search_input):
        yield from self.gemstone_browser_session.find_classes(search_input)
        
    def find_selectors_matching(self, search_input):
        yield from self.gemstone_browser_session.find_selectors(search_input)

    def find_implementors_of_method(self, method_name):
        yield from [
            (
                implementor['class_name'],
                not implementor['show_instance_side'],
            )
            for implementor in self.gemstone_browser_session.find_implementors(
                method_name
            )
        ]

    def find_senders_of_method(self, method_name):
        sender_search_result = self.gemstone_browser_session.find_senders(
            method_name
        )
        yield from [
            (
                sender['class_name'],
                sender['show_instance_side'],
                sender['method_selector'],
            )
            for sender in sender_search_result['senders']
        ]

    def plan_sender_evidence_tests(
        self,
        method_name,
        max_depth=2,
        max_nodes=500,
        max_senders_per_selector=200,
        max_test_methods=200,
        max_elapsed_ms=1500,
    ):
        return self.gemstone_browser_session.sender_test_plan_for_selector(
            method_name,
            max_depth,
            max_nodes,
            max_senders_per_selector,
            max_test_methods,
            max_elapsed_ms=max_elapsed_ms,
        )

    def collect_sender_evidence_from_tests(
        self,
        method_name,
        selected_tests,
        max_traced_senders=250,
        max_observed_results=500,
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
        self.require_write_access('apply_method_rename')
        rename_result = self.gemstone_browser_session.apply_method_rename(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )
        self.publish_model_change('methods')
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
        self.require_write_access('apply_method_move')
        move_result = self.gemstone_browser_session.apply_method_move(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
            overwrite_target_method=overwrite_target_method,
            delete_source_method=delete_source_method,
        )
        self.publish_model_change('methods')
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
        self.require_write_access('apply_method_add_parameter')
        add_parameter_result = self.gemstone_browser_session.apply_method_add_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )
        self.publish_model_change('methods')
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
        self.require_write_access('apply_method_remove_parameter')
        remove_parameter_result = self.gemstone_browser_session.apply_method_remove_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            overwrite_new_method=overwrite_new_method,
            rewrite_source_senders=rewrite_source_senders,
        )
        self.publish_model_change('methods')
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
        self.require_write_access('apply_method_extract')
        extract_result = self.gemstone_browser_session.apply_method_extract(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
            overwrite_new_method=overwrite_new_method,
        )
        self.publish_model_change('methods')
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
        self.require_write_access('apply_method_inline')
        inline_result = self.gemstone_browser_session.apply_method_inline(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
            delete_inlined_method=delete_inlined_method,
        )
        self.publish_model_change('methods')
        return inline_result
        
    def update_method_source(self, selected_class, show_instance_side, method_symbol, source):
        self.require_write_access('update_method_source')
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
        )
        self.publish_model_change('methods')

    def create_method(
        self,
        selected_class,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        self.require_write_access('create_method')
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
            method_category=method_category,
        )
        self.publish_model_change('methods')

    def delete_method(self, selected_class, show_instance_side, method_selector):
        self.require_write_access('delete_method')
        self.gemstone_browser_session.delete_method(
            selected_class,
            method_selector,
            show_instance_side,
        )
        if self.selected_method_symbol == method_selector:
            self.selected_method_symbol = None
        self.publish_model_change('methods')

    def run_code(self, source):
        self.require_write_access('run_code')
        return self.gemstone_browser_session.run_code(source)

    def run_gemstone_tests(self, class_name):
        self.require_write_access('run_gemstone_tests')
        return self.gemstone_browser_session.run_gemstone_tests(class_name)

    def run_test_method(self, class_name, method_selector):
        self.require_write_access('run_test_method')
        return self.gemstone_browser_session.run_test_method(class_name, method_selector)

    def debug_test_method(self, class_name, method_selector):
        self.require_write_access('debug_test_method')
        return self.gemstone_browser_session.debug_test_method(class_name, method_selector)
    # except GemstoneError as e:
    #     try:
    #         e.context.gciStepOverFromLevel(1)
    #     except GemstoneError as ex:
    #         result = ex.continue_with()
    
        
    
class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = deque()
        self.queue_lock = threading.RLock()
        self.root_thread_ident = threading.get_ident()
        self.wakeup_read_descriptor = None
        self.wakeup_write_descriptor = None
        self.root.bind('<<CustomEventsPublished>>', self.process_events)
        self.configure_cross_thread_wakeup()

    def configure_cross_thread_wakeup(self):
        supports_filehandler = hasattr(self.root, 'createfilehandler')
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

    def subscribe(self, event_name, callback, *args):
        self.events.setdefault(event_name, [])
        self.events[event_name].append((self.callback_reference_for(callback), args))

    def publish(self, event_name, *args, **kwargs):
        if event_name in self.events:
            with self.queue_lock:
                self.queue.append((event_name, args, kwargs))
        if threading.get_ident() == self.root_thread_ident:
            try:
                self.root.event_generate('<<CustomEventsPublished>>')
            except tk.TclError:
                pass
            return
        self.publish_cross_thread_wakeup()

    def publish_cross_thread_wakeup(self):
        if self.wakeup_write_descriptor is not None:
            try:
                os.write(self.wakeup_write_descriptor, b'1')
            except OSError:
                pass
            return
        try:
            self.root.event_generate('<<CustomEventsPublished>>')
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
                if wakeup_payload == b'':
                    break
                if len(wakeup_payload) < 1024:
                    break
        self.process_events(None)

    def process_events(self, event):
        while True:
            with self.queue_lock:
                if not self.queue:
                    break
                event_name, args, kwargs = self.queue.popleft()
            if event_name in self.events:
                logging.getLogger(__name__).debug(f'Processing: {event_name}')
                retained_callbacks = []
                for weak_callback, callback_args in self.events[event_name]:
                    callback = weak_callback()
                    if callback is None:
                        continue
                    retained_callbacks.append((weak_callback, callback_args))
                    logging.getLogger(__name__).debug(f'Calling: {callback}')
                    callback(*callback_args, *args, **kwargs)
                self.events[event_name] = retained_callbacks
                    
    def clear_subscribers(self, owner):
        for event_name, registered_callbacks in self.events.copy().items():
            cleaned_callbacks = []
            for weak_callback, callback_args in registered_callbacks:
                callback = weak_callback()
                callback_is_live = callback is not None
                owner_matches = False
                if callback_is_live:
                    owner_matches = getattr(callback, '__self__', None) is owner
                if callback_is_live and not owner_matches:
                    cleaned_callbacks.append((weak_callback, callback_args))
            self.events[event_name] = cleaned_callbacks

    def close(self):
        if (
            self.wakeup_read_descriptor is not None
            and hasattr(self.root, 'deletefilehandler')
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


class McpRuntimeConfig:
    def __init__(
        self,
        allow_eval=False,
        allow_compile=False,
        allow_commit=False,
        allow_tracing=False,
        allow_mcp_commit_when_gui=False,
        require_gemstone_ast=False,
        mcp_host='127.0.0.1',
        mcp_port=8000,
        mcp_http_path='/mcp',
    ):
        self.allow_eval = allow_eval
        self.allow_compile = allow_compile
        self.allow_commit = allow_commit
        self.allow_tracing = allow_tracing
        self.allow_mcp_commit_when_gui = allow_mcp_commit_when_gui
        self.require_gemstone_ast = require_gemstone_ast
        self.mcp_host = mcp_host
        self.mcp_port = mcp_port
        self.mcp_http_path = mcp_http_path

    def copy(self):
        return McpRuntimeConfig(
            allow_eval=self.allow_eval,
            allow_compile=self.allow_compile,
            allow_commit=self.allow_commit,
            allow_tracing=self.allow_tracing,
            allow_mcp_commit_when_gui=self.allow_mcp_commit_when_gui,
            require_gemstone_ast=self.require_gemstone_ast,
            mcp_host=self.mcp_host,
            mcp_port=self.mcp_port,
            mcp_http_path=self.mcp_http_path,
        )

    def endpoint_url(self):
        return 'http://%s:%s%s' % (
            self.mcp_host,
            self.mcp_port,
            self.mcp_http_path,
        )

    def update_with(
        self,
        allow_eval=None,
        allow_compile=None,
        allow_commit=None,
        allow_tracing=None,
        allow_mcp_commit_when_gui=None,
        require_gemstone_ast=None,
        mcp_host=None,
        mcp_port=None,
        mcp_http_path=None,
    ):
        if allow_eval is not None:
            self.allow_eval = bool(allow_eval)
        if allow_compile is not None:
            self.allow_compile = bool(allow_compile)
        if allow_commit is not None:
            self.allow_commit = bool(allow_commit)
        if allow_tracing is not None:
            self.allow_tracing = bool(allow_tracing)
        if allow_mcp_commit_when_gui is not None:
            self.allow_mcp_commit_when_gui = bool(allow_mcp_commit_when_gui)
        if require_gemstone_ast is not None:
            self.require_gemstone_ast = bool(require_gemstone_ast)
        if mcp_host is not None:
            self.mcp_host = mcp_host
        if mcp_port is not None:
            self.mcp_port = mcp_port
        if mcp_http_path is not None:
            self.mcp_http_path = mcp_http_path


class EmbeddedMcpServerController:
    def __init__(self, integrated_session_state, runtime_config):
        self.integrated_session_state = integrated_session_state
        self.runtime_config = runtime_config.copy()
        self.lock = threading.RLock()
        self.server_thread = None
        self.uvicorn_server = None
        self.last_error_message = ''
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

    def status(self):
        with self.lock:
            return {
                'running': self.running,
                'starting': self.starting,
                'stopping': self.stopping,
                'last_error_message': self.last_error_message,
                'endpoint_url': self.runtime_config.endpoint_url(),
            }

    def callback_reference_for(self, callback):
        try:
            return weakref.WeakMethod(callback)
        except TypeError:
            return weakref.ref(callback)

    def subscribe_server_state(self, callback):
        with self.lock:
            self.server_state_subscribers.append(
                self.callback_reference_for(callback)
            )

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
                running=status_payload['running'],
                starting=status_payload['starting'],
                stopping=status_payload['stopping'],
                endpoint_url=status_payload['endpoint_url'],
                last_error_message=status_payload['last_error_message'],
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
            callback_owner = getattr(callback, '__self__', None)
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
            self.last_error_message = ''
            self.server_thread = threading.Thread(
                target=self.run_server,
                daemon=True,
                name='SwordfishEmbeddedMCP',
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
                name='SwordfishEmbeddedMCPStopWait',
            )
            wait_thread.start()
        return True

    def wait_for_server_thread_exit(self, server_thread):
        server_thread.join(timeout=5)

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
            mcp_server = create_server(
                allow_eval=local_runtime_config.allow_eval,
                allow_compile=local_runtime_config.allow_compile,
                allow_commit=local_runtime_config.allow_commit,
                allow_tracing=local_runtime_config.allow_tracing,
                allow_commit_when_gui=(
                    local_runtime_config.allow_mcp_commit_when_gui
                ),
                integrated_session_state=self.integrated_session_state,
                require_gemstone_ast=local_runtime_config.require_gemstone_ast,
                mcp_host=local_runtime_config.mcp_host,
                mcp_port=local_runtime_config.mcp_port,
                mcp_streamable_http_path=local_runtime_config.mcp_http_path,
            )
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
                self.running = True
                self.starting = False
                self.last_error_message = ''
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
            self.notify_server_state_subscribers()


class McpConfigurationDialog(tk.Toplevel):
    def __init__(self, parent, current_runtime_config):
        super().__init__(parent)
        self.parent = parent
        self.current_runtime_config = current_runtime_config.copy()
        self.result = None
        self.title('MCP Configuration')
        self.geometry('500x390')
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.host_variable = tk.StringVar(
            value=self.current_runtime_config.mcp_host
        )
        self.port_variable = tk.StringVar(
            value=str(self.current_runtime_config.mcp_port)
        )
        self.path_variable = tk.StringVar(
            value=self.current_runtime_config.mcp_http_path
        )
        self.allow_eval_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_eval
        )
        self.allow_compile_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_compile
        )
        self.allow_commit_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_commit
        )
        self.allow_commit_when_gui_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_mcp_commit_when_gui
        )
        self.allow_tracing_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_tracing
        )
        self.require_gemstone_ast_variable = tk.BooleanVar(
            value=self.current_runtime_config.require_gemstone_ast
        )

        self.create_widgets()

    def create_widgets(self):
        body_frame = ttk.Frame(self, padding=12)
        body_frame.grid(row=0, column=0, sticky='nsew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        ttk.Label(body_frame, text='Host').grid(
            row=0, column=0, sticky='w', pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.host_variable).grid(
            row=1, column=0, sticky='ew', pady=(0, 10)
        )

        ttk.Label(body_frame, text='Port').grid(
            row=2, column=0, sticky='w', pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.port_variable).grid(
            row=3, column=0, sticky='ew', pady=(0, 10)
        )

        ttk.Label(body_frame, text='HTTP Path').grid(
            row=4, column=0, sticky='w', pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.path_variable).grid(
            row=5, column=0, sticky='ew', pady=(0, 12)
        )

        ttk.Checkbutton(
            body_frame,
            text='Enable eval tools',
            variable=self.allow_eval_variable,
        ).grid(row=6, column=0, sticky='w')
        ttk.Checkbutton(
            body_frame,
            text='Enable compile/refactor tools',
            variable=self.allow_compile_variable,
        ).grid(row=7, column=0, sticky='w')
        ttk.Checkbutton(
            body_frame,
            text='Enable commit tool',
            variable=self.allow_commit_variable,
        ).grid(row=8, column=0, sticky='w')
        ttk.Checkbutton(
            body_frame,
            text='Allow MCP commit while IDE owns session',
            variable=self.allow_commit_when_gui_variable,
        ).grid(row=9, column=0, sticky='w')
        ttk.Checkbutton(
            body_frame,
            text='Enable tracing tools',
            variable=self.allow_tracing_variable,
        ).grid(row=10, column=0, sticky='w')
        ttk.Checkbutton(
            body_frame,
            text='Require GemStone AST backend',
            variable=self.require_gemstone_ast_variable,
        ).grid(row=11, column=0, sticky='w')

        button_frame = ttk.Frame(body_frame)
        button_frame.grid(row=12, column=0, sticky='e', pady=(16, 0))
        ttk.Button(
            button_frame,
            text='Cancel',
            command=self.cancel_dialog,
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            button_frame,
            text='Apply',
            command=self.apply_configuration,
        ).grid(row=0, column=1)
        body_frame.columnconfigure(0, weight=1)

    def apply_configuration(self):
        port_text = self.port_variable.get().strip()
        if not port_text:
            messagebox.showerror('Invalid MCP configuration', 'Port cannot be empty.')
            return
        if not port_text.isdigit():
            messagebox.showerror(
                'Invalid MCP configuration',
                'Port must be a positive integer.',
            )
            return
        mcp_port = int(port_text)
        if mcp_port <= 0:
            messagebox.showerror(
                'Invalid MCP configuration',
                'Port must be greater than zero.',
            )
            return
        mcp_host = self.host_variable.get().strip()
        if not mcp_host:
            messagebox.showerror(
                'Invalid MCP configuration',
                'Host cannot be empty.',
            )
            return
        mcp_http_path = self.path_variable.get().strip()
        if not mcp_http_path.startswith('/'):
            messagebox.showerror(
                'Invalid MCP configuration',
                'HTTP path must start with /.',
            )
            return
        self.result = McpRuntimeConfig(
            allow_eval=self.allow_eval_variable.get(),
            allow_compile=self.allow_compile_variable.get(),
            allow_commit=self.allow_commit_variable.get(),
            allow_tracing=self.allow_tracing_variable.get(),
            allow_mcp_commit_when_gui=(
                self.allow_commit_when_gui_variable.get()
            ),
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
        self.add_cascade(label='Session', menu=self.session_menu)
        self.update_session_menu()
        self.add_cascade(label='MCP', menu=self.mcp_menu)
        self.update_mcp_menu()

    def _subscribe_events(self):
        self.event_queue.subscribe('LoggedInSuccessfully', self.update_menus)
        self.event_queue.subscribe('LoggedOut', self.update_menus)
        self.event_queue.subscribe('McpBusyStateChanged', self.update_menus)
        self.event_queue.subscribe('McpServerStateChanged', self.update_menus)

    def update_menus(self, gemstone_session_record=None, **kwargs):
        self.update_session_menu()
        self.update_file_menu()
        self.update_mcp_menu()
        
    def update_session_menu(self):
        self.session_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            menu_state = tk.NORMAL
            if self.parent.integrated_session_state.is_mcp_busy():
                menu_state = tk.DISABLED
            self.session_menu.add_command(
                label='Commit',
                command=self.parent.commit,
                state=menu_state,
            )
            self.session_menu.add_command(
                label='Abort',
                command=self.parent.abort,
                state=menu_state,
            )
            self.session_menu.add_command(
                label='Logout',
                command=self.parent.logout,
                state=menu_state,
            )
        else:
            self.session_menu.add_command(label="Login", command=self.parent.show_login_screen)

    def update_mcp_menu(self):
        self.mcp_menu.delete(0, tk.END)
        mcp_state = self.parent.embedded_mcp_server_status()
        start_state = tk.NORMAL
        if mcp_state['running'] or mcp_state['starting'] or mcp_state['stopping']:
            start_state = tk.DISABLED
        stop_state = tk.NORMAL
        if (
            not mcp_state['running']
            and not mcp_state['starting']
            and not mcp_state['stopping']
        ):
            stop_state = tk.DISABLED
        if mcp_state['stopping']:
            stop_state = tk.DISABLED
        if self.parent.integrated_session_state.is_mcp_busy():
            stop_state = tk.DISABLED
        configure_state = tk.NORMAL
        if mcp_state['starting'] or mcp_state['stopping']:
            configure_state = tk.DISABLED
        self.mcp_menu.add_command(
            label='Start MCP',
            command=self.start_mcp_server,
            state=start_state,
        )
        self.mcp_menu.add_command(
            label='Stop MCP',
            command=self.stop_mcp_server,
            state=stop_state,
        )
        self.mcp_menu.add_separator()
        self.mcp_menu.add_command(
            label='Configure MCP',
            command=self.configure_mcp_server,
            state=configure_state,
        )
            
    def update_file_menu(self):
        self.file_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            run_command_state = tk.NORMAL
            if self.parent.integrated_session_state.is_mcp_busy():
                run_command_state = tk.DISABLED
            self.file_menu.add_command(label="Find", command=self.show_find_dialog)
            self.file_menu.add_command(label="Implementors", command=self.show_implementors_dialog)
            self.file_menu.add_command(label="Senders", command=self.show_senders_dialog)
            self.file_menu.add_command(
                label='Run',
                command=self.show_run_dialog,
                state=run_command_state,
            )
            self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

    def show_find_dialog(self):
        self.parent.open_find_dialog()
        
    def show_implementors_dialog(self):
        self.parent.open_implementors_dialog()

    def show_senders_dialog(self):
        self.parent.open_senders_dialog()

    def show_run_dialog(self):
        self.parent.run_code()

    def start_mcp_server(self):
        self.parent.start_mcp_server_from_menu()

    def stop_mcp_server(self):
        self.parent.stop_mcp_server_from_menu()

    def configure_mcp_server(self):
        self.parent.configure_mcp_server_from_menu()


class FindDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Find")
        self.geometry("300x400")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Radio buttons for search type
        self.search_type = tk.StringVar(value="class")
        ttk.Label(self, text="Search Type:").grid(row=0, column=0, padx=10, pady=5, sticky='w')
        self.class_radio = ttk.Radiobutton(self, text="Class", variable=self.search_type, value="class")
        self.class_radio.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        self.method_radio = ttk.Radiobutton(self, text="Method", variable=self.search_type, value="method")
        self.method_radio.grid(row=0, column=2, padx=5, pady=5, sticky='w')

        # Find entry
        ttk.Label(self, text="Find what:").grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.find_entry = ttk.Entry(self)
        self.find_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky='ew')

        # Buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.find_button = ttk.Button(self.button_frame, text="Find", command=self.find_text)
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=5)

        # Listbox for results
        self.results_listbox = tk.Listbox(self)
        self.results_listbox.grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky='nsew')
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record
    
    def find_text(self):
        self.results_listbox.grid()

        # Simulate search results based on the search type and query
        search_query = self.find_entry.get()
        search_type = self.search_type.get()
        results = []

        if search_query:
            if search_type == "class":
                # Simulate finding classes
                results = self.gemstone_session_record.find_class_names_matching(search_query)
            elif search_type == "method":
                results = self.gemstone_session_record.find_selectors_matching(search_query)

        # Display results in the listbox
        self.results_listbox.delete(0, tk.END)
        for result in results:
            self.results_listbox.insert(tk.END, result)

        self.results_listbox.grid()  # Show the listbox

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_text = self.results_listbox.get(selected_index)
            search_type = self.search_type.get()
            parent = self.parent
            self.destroy()
            if search_type == 'class':
                parent.handle_find_selection(search_type == 'class', selected_text)
            else:
                parent.open_implementors_dialog(method_symbol=selected_text)
        except IndexError:
            pass


class ImplementorsDialog(tk.Toplevel):
    def __init__(self, parent, method_name=None):
        super().__init__(parent)
        self.title("Implementors")
        self.geometry("400x500")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent

        # Configure grid for proper resizing
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Method name entry
        ttk.Label(self, text="Method Name:").grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.method_entry = ttk.Entry(self)
        self.method_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky='ew')
        if method_name:
            self.method_entry.insert(0, method_name)

        # Buttons frame
        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=1, column=0, columnspan=3, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.find_button = ttk.Button(self.button_frame, text="Find", command=self.find_implementors)
        self.find_button.grid(row=0, column=0, padx=5)

        self.cancel_button = ttk.Button(self.button_frame, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=0, column=1, padx=5)

        # Listbox for results
        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)
        self.results_listbox.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky='nsew')

        # Initialize with the implementors
        self.find_implementors()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def find_implementors(self):
        self.results_listbox.grid()  # Make listbox visible
        # Simulate search results for implementors of a method
        method_name = self.method_entry.get()
        results = []

        if method_name:
            results = self.gemstone_session_record.find_implementors_of_method(method_name)

        # Display results in the listbox
        self.results_listbox.delete(0, tk.END)
        for class_name, is_meta in results:
            method_type = " class" if is_meta else ""
            self.results_listbox.insert(tk.END, f"{class_name}{method_type}")

        self.results_listbox.grid()  # Show the listbox

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_text = self.results_listbox.get(selected_index)
            class_name, *rest = selected_text.split(' ', 1)
            is_instance_side = 'class' not in rest
            self.parent.handle_implementor_selection(self.method_entry.get(), class_name, is_instance_side)
            self.destroy()
        except IndexError:
            pass


class SenderEvidenceTestsDialog(tk.Toplevel):
    def __init__(self, parent, method_name, test_plan):
        super().__init__(parent)
        self.title('Trace Narrowing Tests')
        self.geometry('760x520')
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.selected_tests = None
        self.candidate_tests = test_plan.get('candidate_tests', [])
        self.checkbox_variables = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        summary_text = self.plan_summary_text(method_name, test_plan)
        self.summary_label = ttk.Label(
            self,
            text=summary_text,
            justify='left',
        )
        self.summary_label.grid(
            row=0,
            column=0,
            padx=10,
            pady=(10, 6),
            sticky='w',
        )

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky='nsew', padx=10)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient='vertical',
            command=self.canvas.yview,
        )
        self.scrollbar.grid(row=1, column=1, sticky='ns', padx=(0, 10))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.tests_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.tests_frame,
            anchor='nw',
        )
        self.tests_frame.bind('<Configure>', self.update_scroll_region)
        self.canvas.bind('<Configure>', self.update_canvas_window_width)

        self.populate_test_checkboxes()

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=2, column=0, columnspan=2, sticky='e', pady=10)
        self.select_all_button = ttk.Button(
            self.buttons,
            text='Select All',
            command=self.select_all_tests,
        )
        self.select_all_button.grid(row=0, column=0, padx=(0, 4))
        self.select_none_button = ttk.Button(
            self.buttons,
            text='Select None',
            command=self.select_no_tests,
        )
        self.select_none_button.grid(row=0, column=1, padx=(0, 10))
        self.run_selected_button = ttk.Button(
            self.buttons,
            text='Run Selected While Tracing',
            command=self.run_selected_tests,
        )
        self.run_selected_button.grid(row=0, column=2, padx=(0, 4))
        self.cancel_button = ttk.Button(
            self.buttons,
            text='Cancel',
            command=self.destroy,
        )
        self.cancel_button.grid(row=0, column=3)

    def plan_summary_text(self, method_name, test_plan):
        candidate_count = test_plan.get('candidate_test_count', 0)
        visited_selector_count = test_plan.get('visited_selector_count', 0)
        summary_parts = [
            (
                'Suggested tests for tracing callers of %s '
                '(candidates: %s, explored selectors: %s).'
            )
            % (
                method_name,
                candidate_count,
                visited_selector_count,
            )
        ]
        if test_plan.get('elapsed_limit_reached'):
            summary_parts.append(
                (
                    'Discovery hit time limit (%sms) and returned partial '
                    'suggestions.'
                )
                % test_plan.get('max_elapsed_ms')
            )
        if test_plan.get('sender_search_truncated'):
            summary_parts.append(
                (
                    'Some sender searches were truncated, so this is an '
                    'incomplete subset.'
                )
            )
        if test_plan.get('selector_limit_reached'):
            summary_parts.append(
                'Selector traversal limit was reached.'
            )
        return ' '.join(summary_parts)

    def format_test_label(self, candidate_test):
        return (
            '%s>>%s (depth %s via %s)'
            % (
                candidate_test['test_case_class_name'],
                candidate_test['test_method_selector'],
                candidate_test.get('depth', '?'),
                candidate_test.get('reached_from_selector', '?'),
            )
        )

    def populate_test_checkboxes(self):
        default_checked_count = 20
        for index, candidate_test in enumerate(self.candidate_tests):
            is_default_checked = index < default_checked_count
            selected = tk.BooleanVar(value=is_default_checked)
            self.checkbox_variables.append(selected)
            checkbutton = ttk.Checkbutton(
                self.tests_frame,
                text=self.format_test_label(candidate_test),
                variable=selected,
            )
            checkbutton.grid(
                row=index,
                column=0,
                sticky='w',
                padx=4,
                pady=2,
            )

    def update_scroll_region(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def update_canvas_window_width(self, event):
        self.canvas.itemconfigure(
            self.canvas_window,
            width=event.width,
        )

    def select_all_tests(self):
        for selected in self.checkbox_variables:
            selected.set(True)

    def select_no_tests(self):
        for selected in self.checkbox_variables:
            selected.set(False)

    def run_selected_tests(self):
        selected_tests = []
        for index, selected in enumerate(self.checkbox_variables):
            if selected.get():
                selected_tests.append(self.candidate_tests[index])
        if not selected_tests:
            messagebox.showwarning(
                'Trace Narrowing',
                'Select at least one test.',
                parent=self,
            )
            return
        self.selected_tests = selected_tests
        self.destroy()


class SendersDialog(tk.Toplevel):
    def __init__(self, parent, method_name=None):
        super().__init__(parent)
        self.title('Senders')
        self.geometry('560x560')
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent
        self.sender_results = []
        self.static_sender_results = []
        self.status_var = tk.StringVar(value='')

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ttk.Label(self, text='Method Name:').grid(
            row=0,
            column=0,
            padx=10,
            pady=10,
            sticky='w',
        )
        self.method_entry = ttk.Entry(self)
        self.method_entry.grid(
            row=0,
            column=1,
            columnspan=2,
            padx=10,
            pady=10,
            sticky='ew',
        )
        if method_name:
            self.method_entry.insert(0, method_name)

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=1, column=0, columnspan=3, pady=10)

        self.find_button = ttk.Button(
            self.button_frame,
            text='Find',
            command=self.find_senders,
        )
        self.find_button.grid(row=0, column=0, padx=5)

        self.narrow_button = ttk.Button(
            self.button_frame,
            text='Narrow With Tracing',
            command=self.narrow_senders_with_tracing,
        )
        self.narrow_button.grid(row=0, column=1, padx=5)

        self.cancel_button = ttk.Button(
            self.button_frame,
            text='Cancel',
            command=self.destroy,
        )
        self.cancel_button.grid(row=0, column=2, padx=5)

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)
        self.results_listbox.grid(
            row=2,
            column=0,
            columnspan=3,
            padx=10,
            pady=(10, 4),
            sticky='nsew',
        )

        self.status_label = ttk.Label(
            self,
            textvariable=self.status_var,
            anchor='w',
        )
        self.status_label.grid(
            row=3,
            column=0,
            columnspan=3,
            padx=10,
            pady=(0, 10),
            sticky='ew',
        )

        self.find_senders()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def populate_sender_results(self, sender_results):
        self.sender_results = list(sender_results)
        self.results_listbox.delete(0, tk.END)
        for class_name, show_instance_side, method_selector in self.sender_results:
            side_text = '' if show_instance_side else ' class'
            self.results_listbox.insert(
                tk.END,
                f'{class_name}{side_text}>>{method_selector}',
            )

    def find_senders(self):
        method_name = self.method_entry.get().strip()
        static_sender_results = []
        if method_name:
            static_sender_results = list(
                self.gemstone_session_record.find_senders_of_method(method_name)
            )
        self.static_sender_results = static_sender_results
        self.populate_sender_results(self.static_sender_results)
        self.status_var.set(
            'Static senders: %s' % len(self.static_sender_results)
        )

    def choose_tests_for_tracing(self, method_name, test_plan):
        test_selection_dialog = SenderEvidenceTestsDialog(
            self,
            method_name,
            test_plan,
        )
        self.wait_window(test_selection_dialog)
        return test_selection_dialog.selected_tests

    def observed_sender_key(self, observed_sender):
        return (
            observed_sender['caller_class_name'],
            observed_sender['caller_show_instance_side'],
            observed_sender['caller_method_selector'],
        )

    def narrow_senders_with_tracing(self):
        method_name = self.method_entry.get().strip()
        if not method_name:
            messagebox.showwarning(
                'Narrow Senders',
                'Enter a method selector first.',
                parent=self,
            )
            return
        if not self.static_sender_results:
            self.find_senders()
        try:
            test_plan = self.gemstone_session_record.plan_sender_evidence_tests(
                method_name,
                max_depth=2,
                max_nodes=500,
                max_senders_per_selector=200,
                max_test_methods=200,
                max_elapsed_ms=1500,
            )
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                'Narrow Senders',
                str(error),
                parent=self,
            )
            return
        if test_plan.get('candidate_test_count', 0) == 0:
            messagebox.showinfo(
                'Narrow Senders',
                (
                    'No candidate tests were found for this selector. '
                    'Run relevant tests manually, then retry narrowing.'
                ),
                parent=self,
            )
            return
        selected_tests = self.choose_tests_for_tracing(method_name, test_plan)
        if selected_tests is None:
            return
        self.status_var.set(
            (
                'Tracing %s and running %s selected tests...'
            )
            % (
                method_name,
                len(selected_tests),
            )
        )
        self.update_idletasks()
        try:
            evidence_result = (
                self.gemstone_session_record.collect_sender_evidence_from_tests(
                    method_name,
                    selected_tests,
                    max_traced_senders=250,
                    max_observed_results=500,
                )
            )
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                'Narrow Senders',
                str(error),
                parent=self,
            )
            self.status_var.set('')
            return
        observed_sender_entries = evidence_result['observed']['observed_senders']
        observed_sender_keys = {
            self.observed_sender_key(observed_sender)
            for observed_sender in observed_sender_entries
        }
        narrowed_sender_results = [
            sender_result
            for sender_result in self.static_sender_results
            if sender_result in observed_sender_keys
        ]
        self.populate_sender_results(narrowed_sender_results)
        trace_result = evidence_result.get('trace') or {}
        total_sender_count = trace_result.get('total_sender_count')
        targeted_sender_count = trace_result.get('targeted_sender_count')
        summary_text = (
            'Observed sender matches: %s of %s static senders.'
            % (
                len(narrowed_sender_results),
                len(self.static_sender_results),
            )
        )
        trace_was_capped = (
            total_sender_count is not None
            and targeted_sender_count is not None
            and targeted_sender_count < total_sender_count
        )
        if trace_was_capped:
            summary_text = (
                summary_text
                + ' Tracing targeted %s of %s senders (capped).'
                % (
                    targeted_sender_count,
                    total_sender_count,
                )
            )
        self.status_var.set(summary_text)

    def on_result_double_click(self, event):
        try:
            selected_index = self.results_listbox.curselection()[0]
            selected_sender = self.sender_results[selected_index]
            class_name, show_instance_side, method_selector = selected_sender
            self.parent.handle_sender_selection(
                class_name,
                show_instance_side,
                method_selector,
            )
            self.destroy()
        except IndexError:
            pass


class Swordfish(tk.Tk):
    def __init__(
        self,
        default_stone_name='gs64stone',
        start_embedded_mcp=False,
        mcp_runtime_config=None,
    ):
        super().__init__()
        self.event_queue = EventQueue(self)
        self.integrated_session_state = current_integrated_session_state()
        self.integrated_session_state.attach_ide_gui()
        self.title('Swordfish')
        self.geometry('800x600')
        self.default_stone_name = default_stone_name

        self.notebook = None
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.collaboration_status_text = tk.StringVar(value='')
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False
        self.foreground_activity_message = ''

        self.gemstone_session_record = None
        self.last_mcp_busy_state = None
        self.last_mcp_server_running_state = None
        self.last_mcp_server_starting_state = None
        self.last_mcp_server_stopping_state = None
        self.last_mcp_server_error_message = None
        if mcp_runtime_config is None:
            mcp_runtime_config = McpRuntimeConfig(
                allow_compile=True,
                allow_tracing=True,
            )
        self.mcp_runtime_config = mcp_runtime_config.copy()
        self.embedded_mcp_server_controller = EmbeddedMcpServerController(
            self.integrated_session_state,
            self.mcp_runtime_config,
        )

        self.event_queue.subscribe('LoggedInSuccessfully', self.show_main_app)
        self.event_queue.subscribe('LoggedOut', self.show_login_screen)
        self.event_queue.subscribe(
            'McpBusyStateChanged',
            self.handle_mcp_busy_state_changed,
        )
        self.event_queue.subscribe(
            'McpServerStateChanged',
            self.handle_mcp_server_state_changed,
        )
        self.event_queue.subscribe(
            'ModelRefreshRequested',
            self.handle_model_refresh_requested,
        )
        self.integrated_session_state.subscribe_mcp_busy_state(
            self.publish_mcp_busy_state_event,
        )
        self.integrated_session_state.subscribe_model_refresh_requests(
            self.publish_model_refresh_requested_event,
        )
        self.embedded_mcp_server_controller.subscribe_server_state(
            self.publish_mcp_server_state_event,
        )

        self.create_menu()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(
            **self.embedded_mcp_server_controller.status()
        )
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
        return self.embedded_mcp_server_controller.status()

    def start_mcp_server(self, report_errors=True):
        started = self.embedded_mcp_server_controller.start()
        if not started and report_errors:
            messagebox.showinfo(
                'MCP',
                'MCP is already running or starting.',
            )
        return started

    def stop_mcp_server(self):
        stopped = self.embedded_mcp_server_controller.stop()
        if not stopped:
            messagebox.showinfo(
                'MCP',
                'MCP is already stopped.',
            )
        return stopped

    def start_mcp_server_from_menu(self):
        self.begin_foreground_activity('Starting MCP server...')
        try:
            self.start_mcp_server(report_errors=True)
            self.menu_bar.update_menus()
        finally:
            self.end_foreground_activity()

    def stop_mcp_server_from_menu(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                'MCP Busy',
                'Stop MCP after the current MCP operation finishes.',
            )
            return
        self.begin_foreground_activity('Stopping MCP server...')
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
        mcp_was_running = self.embedded_mcp_server_controller.status()['running']
        self.embedded_mcp_server_controller.update_runtime_config(
            self.mcp_runtime_config
        )
        if mcp_was_running:
            self.embedded_mcp_server_controller.stop()
            self.start_mcp_server(report_errors=True)
        self.menu_bar.update_menus()

    def commit(self):
        self.gemstone_session_record.commit()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish('Committed')
        self.publish_model_change_events('transaction')
        
    def abort(self):
        self.gemstone_session_record.abort()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish('Aborted')
        self.publish_model_change_events('transaction')
        
    def logout(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                'MCP Busy',
                'Logout is disabled while MCP is running an operation.',
            )
            return
        self.gemstone_session_record.log_out()
        self.gemstone_session_record = None
        self.integrated_session_state.detach_ide_session()
        self.event_queue.publish('LoggedOut')
            
    def clear_widgets(self):
        for widget in self.winfo_children():
            if widget != self.menu_bar:
                widget.destroy()
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False

    def show_login_screen(self):
        self.clear_widgets()
        self.collaboration_status_text.set('')
        self.foreground_activity_message = ''
        self.last_mcp_server_stopping_state = None
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        self.login_frame = LoginFrame(
            self,
            default_stone_name=self.default_stone_name,
        )
        self.login_frame.grid(row=0, column=0, sticky='nsew')

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
        if change_kind == 'packages':
            self.event_queue.publish('PackagesChanged')
            self.event_queue.publish('ClassesChanged')
            return
        if change_kind == 'classes':
            self.event_queue.publish('ClassesChanged')
            self.event_queue.publish('SelectedClassChanged')
            return
        if change_kind == 'methods':
            self.event_queue.publish('MethodsChanged')
            self.event_queue.publish('SelectedCategoryChanged')
            self.event_queue.publish('MethodSelected')
            return
        if change_kind == 'transaction':
            self.event_queue.publish('PackagesChanged')
            self.event_queue.publish('ClassesChanged')
            self.event_queue.publish('MethodsChanged')

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky='nsew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def create_collaboration_status_bar(self):
        self.collaboration_status_frame = ttk.Frame(self)
        self.collaboration_status_frame.grid(
            row=1,
            column=0,
            sticky='ew',
            padx=6,
            pady=(2, 4),
        )
        self.collaboration_status_frame.columnconfigure(0, weight=1)
        self.collaboration_status_label = ttk.Label(
            self.collaboration_status_frame,
            textvariable=self.collaboration_status_text,
            anchor='w',
        )
        self.collaboration_status_label.grid(
            row=0,
            column=0,
            sticky='ew',
        )
        self.mcp_activity_indicator = ttk.Progressbar(
            self.collaboration_status_frame,
            mode='indeterminate',
            length=110,
        )
        self.mcp_activity_indicator.grid(
            row=0,
            column=1,
            sticky='e',
            padx=(8, 0),
        )
        self.set_mcp_activity_indicator_visibility(False)
        self.rowconfigure(1, weight=0)

    def set_mcp_activity_indicator_visibility(self, visible):
        if self.mcp_activity_indicator is None:
            self.mcp_activity_indicator_visible = False
            return
        if visible and not self.mcp_activity_indicator_visible:
            self.mcp_activity_indicator.grid()
            self.mcp_activity_indicator.start(10)
            self.mcp_activity_indicator_visible = True
            self.event_queue.publish(
                'UiActivityIndicatorChanged',
                is_visible=True,
            )
            return
        if not visible and self.mcp_activity_indicator_visible:
            self.mcp_activity_indicator.stop()
            self.mcp_activity_indicator.grid_remove()
            self.mcp_activity_indicator_visible = False
            self.event_queue.publish(
                'UiActivityIndicatorChanged',
                is_visible=False,
            )

    def begin_foreground_activity(self, message):
        self.foreground_activity_message = message
        self.event_queue.publish(
            'UiActivityChanged',
            is_active=True,
            message=message,
        )
        self.collaboration_status_text.set(message)
        self.set_mcp_activity_indicator_visibility(True)
        try:
            self.config(cursor='watch')
        except tk.TclError:
            pass
        self.update_idletasks()

    def end_foreground_activity(self):
        self.foreground_activity_message = ''
        self.event_queue.publish(
            'UiActivityChanged',
            is_active=False,
            message='',
        )
        try:
            self.config(cursor='')
        except tk.TclError:
            pass
        self.refresh_collaboration_status()

    def publish_mcp_busy_state_event(self, is_busy=False, operation_name=''):
        self.event_queue.publish(
            'McpBusyStateChanged',
            is_busy=is_busy,
            operation_name=operation_name,
        )

    def publish_mcp_server_state_event(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url='',
        last_error_message='',
    ):
        self.event_queue.publish(
            'McpServerStateChanged',
            running=running,
            starting=starting,
            stopping=stopping,
            endpoint_url=endpoint_url,
            last_error_message=last_error_message,
        )

    def publish_model_refresh_requested_event(self, change_kind=''):
        self.event_queue.publish(
            'ModelRefreshRequested',
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
        mcp_server_status = self.embedded_mcp_server_controller.status()
        mcp_server_running = mcp_server_status['running']
        mcp_server_starting = mcp_server_status['starting']
        mcp_server_stopping = mcp_server_status['stopping']
        self.apply_collaboration_read_only_state(mcp_busy)
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
                self.integrated_session_state.current_mcp_operation_name()
                or 'unknown'
            )
            self.collaboration_status_text.set(
                'MCP busy: %s. IDE write/run/debug actions are read-only.'
                % operation_name
            )
        elif mcp_server_stopping:
            self.collaboration_status_text.set('Stopping MCP server...')
        elif mcp_server_starting:
            self.collaboration_status_text.set('Starting MCP server...')
        elif mcp_server_running:
            self.collaboration_status_text.set(
                'IDE ready. MCP running at %s.'
                % mcp_server_status['endpoint_url']
            )
        elif self.is_logged_in:
            self.collaboration_status_text.set(
                'IDE ready. Embedded MCP is stopped.'
            )
        else:
            self.collaboration_status_text.set('')

    def handle_mcp_busy_state_changed(self, is_busy=False, operation_name=''):
        self.last_mcp_busy_state = is_busy
        self.refresh_collaboration_status()

    def handle_mcp_server_state_changed(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url='',
        last_error_message='',
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
                'MCP Startup Failed',
                last_error_message,
            )
        if not last_error_message:
            self.last_mcp_server_error_message = None
        self.refresh_collaboration_status()

    def handle_model_refresh_requested(self, change_kind=''):
        self.process_pending_model_refresh_requests()
        self.refresh_collaboration_status()

    def synchronise_collaboration_state(self):
        if not self.winfo_exists():
            return
        self.process_pending_model_refresh_requests()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(
            **self.embedded_mcp_server_controller.status()
        )
        self.refresh_collaboration_status()

    def destroy(self):
        self.embedded_mcp_server_controller.clear_subscribers(self)
        self.integrated_session_state.clear_subscribers(self)
        self.event_queue.clear_subscribers(self)
        self.embedded_mcp_server_controller.stop()
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
                'MCP Busy',
                'Debugging is disabled while MCP is running an operation.',
            )
            return
        if self.debugger_tab:
            if self.debugger_tab.is_running:
                response = messagebox.askquestion("Debugger Already Open", "A debugger is already open. Replace it with a new one?", icon='warning', type='okcancel')
                if response == 'cancel':
                    return
            self.debugger_tab.destroy()

        self.add_debugger_tab(exception)
        self.select_debugger_tab()

    def add_debugger_tab(self, exception):
        self.debugger_tab = DebuggerWindow(self.notebook, self, self.gemstone_session_record, self.event_queue, exception)
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
        self.event_queue.publish('SelectedClassChanged')
        
    def handle_implementor_selection(self, method_symbol, class_name, show_instance_side):
        self.gemstone_session_record.jump_to_method(class_name, show_instance_side, method_symbol)
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        self.gemstone_session_record.jump_to_method(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.event_queue.publish('SelectedClassChanged')
        self.event_queue.publish('SelectedCategoryChanged')
        self.event_queue.publish('MethodSelected')

    def run_code(self, source=""):
        if self.run_tab is None or not self.run_tab.winfo_exists():
            self.run_tab = RunTab(self.notebook, self)
            self.notebook.add(self.run_tab, text='Run')
        self.run_tab.set_read_only(
            self.integrated_session_state.is_mcp_busy()
        )
        self.notebook.select(self.run_tab)
        run_immediately = bool(source and source.strip())
        self.run_tab.present_source(source, run_immediately=run_immediately)

    def open_inspector_for_object(self, inspected_object):
        self.close_inspector_tab()
        self.inspector_tab = InspectorTab(
            self.notebook,
            self,
            an_object=inspected_object,
        )
        self.notebook.add(self.inspector_tab, text='Inspect')
        self.notebook.select(self.inspector_tab)

    def close_inspector_tab(self):
        has_open_tab = self.inspector_tab is not None and self.inspector_tab.winfo_exists()
        if not has_open_tab:
            self.inspector_tab = None
            return
        try:
            self.notebook.forget(self.inspector_tab)
        except tk.TclError:
            pass
        self.inspector_tab.destroy()
        self.inspector_tab = None
        
    def open_find_dialog(self):
        FindDialog(self)
        
    def open_implementors_dialog(self, method_symbol=None):
        ImplementorsDialog(self, method_name=method_symbol)

    def open_senders_dialog(self, method_symbol=None):
        SendersDialog(self, method_name=method_symbol)
        
        
class RunTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.last_exception = None
        self.current_text_menu = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(5, weight=1)

        self.source_label = ttk.Label(self, text='Source Code:')
        self.source_label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 0))

        self.source_editor_frame = ttk.Frame(self)
        self.source_editor_frame.grid(
            row=1,
            column=0,
            sticky='nsew',
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
        self.source_line_number_column = CodeLineNumberColumn(
            self.source_editor_frame,
            self.source_text,
        )
        self.source_line_number_column.line_numbers_text.grid(
            row=0,
            column=0,
            sticky='ns',
        )
        self.source_text.grid(
            row=0,
            column=1,
            sticky='nsew',
        )

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=(0, 10))
        self.button_frame.columnconfigure(3, weight=1)

        self.run_button = ttk.Button(
            self.button_frame,
            text='Run',
            command=self.run_code_from_editor,
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5))

        self.close_button = ttk.Button(
            self.button_frame,
            text='Close Tab',
            command=self.close_tab,
        )
        self.close_button.grid(row=0, column=1, padx=(0, 5))

        self.debug_button = ttk.Button(
            self.button_frame,
            text='Debug',
            command=self.open_debugger,
        )
        self.debug_button.grid(row=0, column=2, sticky='w')

        self.status_bar = ttk.Frame(self)
        self.status_bar.grid(row=3, column=0, sticky='ew', padx=10)
        self.status_bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(self.status_bar, text='Ready')
        self.status_label.grid(row=0, column=0, sticky='w')
        self.source_cursor_position_label = ttk.Label(
            self.status_bar,
            text='Ln 1, Col 1',
        )
        self.source_cursor_position_label.grid(
            row=0,
            column=1,
            sticky='e',
        )

        self.result_label = ttk.Label(self, text='Result:')
        self.result_label.grid(row=4, column=0, sticky='nw', padx=10, pady=(10, 0))

        self.result_text = tk.Text(self, height=7, state='disabled')
        self.result_text.grid(row=5, column=0, sticky='nsew', padx=10, pady=(0, 10))
        self.configure_text_actions()
        self.source_cursor_position_indicator = TextCursorPositionIndicator(
            self.source_text,
            self.source_cursor_position_label,
        )
        self.application.event_queue.subscribe(
            'McpBusyStateChanged',
            self.handle_mcp_busy_state_changed,
        )
        self.set_read_only(self.is_read_only())

    def configure_text_actions(self):
        self.source_text.bind('<Control-a>', self.select_all_source_text)
        self.source_text.bind('<Control-A>', self.select_all_source_text)
        self.source_text.bind('<Control-c>', self.copy_source_selection)
        self.source_text.bind('<Control-C>', self.copy_source_selection)
        self.source_text.bind('<Control-v>', self.paste_into_source_text)
        self.source_text.bind('<Control-V>', self.paste_into_source_text)
        self.source_text.bind('<Control-z>', self.undo_source_text)
        self.source_text.bind('<Control-Z>', self.undo_source_text)
        self.source_text.bind('<KeyPress>', self.replace_selected_source_text_before_typing, add='+')
        self.source_text.bind('<Button-3>', self.open_source_text_menu)

        self.result_text.bind('<Control-a>', self.select_all_result_text)
        self.result_text.bind('<Control-A>', self.select_all_result_text)
        self.result_text.bind('<Control-c>', self.copy_result_selection)
        self.result_text.bind('<Control-C>', self.copy_result_selection)
        self.result_text.bind('<Button-3>', self.open_result_text_menu)

        self.source_text.bind('<Button-1>', self.close_text_menu, add='+')
        self.result_text.bind('<Button-1>', self.close_text_menu, add='+')

    def is_read_only(self):
        return self.application.integrated_session_state.is_mcp_busy()

    def set_read_only(self, read_only):
        source_text_state = tk.NORMAL
        run_button_state = tk.NORMAL
        debug_button_state = tk.NORMAL
        if read_only:
            source_text_state = tk.DISABLED
            run_button_state = tk.DISABLED
            debug_button_state = tk.DISABLED
        self.source_text.configure(state=source_text_state)
        self.run_button.configure(state=run_button_state)
        self.debug_button.configure(state=debug_button_state)

    def handle_mcp_busy_state_changed(self, is_busy=False, operation_name=''):
        self.set_read_only(is_busy)

    def select_all_source_text(self, event=None):
        select_all_in_text_widget(self.source_text)
        return 'break'

    def copy_source_selection(self, event=None):
        copy_selection_from_text_widget(self, self.source_text)
        return 'break'

    def paste_into_source_text(self, event=None):
        paste_text_into_widget(self, self.source_text)
        return 'break'

    def undo_source_text(self, event=None):
        undo_text_widget_edit(self.source_text)
        return 'break'

    def replace_selected_source_text_before_typing(self, event):
        replace_selected_range_before_typing(self.source_text, event)

    def select_all_result_text(self, event=None):
        select_all_in_text_widget(self.result_text)
        return 'break'

    def copy_result_selection(self, event=None):
        copy_selection_from_text_widget(self, self.result_text)
        return 'break'

    def open_source_text_menu(self, event):
        self.source_text.mark_set(tk.INSERT, f'@{event.x},{event.y}')
        self.show_text_menu_for_widget(
            event,
            self.source_text,
            allow_paste=True,
            allow_undo=True,
            include_run_actions=True,
        )

    def open_result_text_menu(self, event):
        self.result_text.mark_set(tk.INSERT, f'@{event.x},{event.y}')
        self.show_text_menu_for_widget(
            event,
            self.result_text,
            allow_paste=False,
            allow_undo=False,
            include_run_actions=False,
        )

    def selected_source_text(self):
        start_index, end_index = selected_range_in_text_widget(self.source_text)
        if start_index is None:
            return ''
        return self.source_text.get(start_index, end_index)

    def run_selected_source_text(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Run is disabled.')
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text='Select source text to run')
            return
        self.status_label.config(text='Running selection...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Running selected source...')
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
            self.status_label.config(text='MCP is busy. Inspect is disabled.')
            return
        selected_text = self.selected_source_text()
        if not selected_text.strip():
            self.status_label.config(text='Select source text to inspect')
            return
        self.status_label.config(text='Inspecting selection...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Inspecting selected source...')
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
        read_only = self.is_read_only()
        paste_command_state = tk.NORMAL
        undo_command_state = tk.NORMAL
        if read_only and text_widget is self.source_text:
            paste_command_state = tk.DISABLED
            undo_command_state = tk.DISABLED
        self.current_text_menu.add_command(
            label='Select All',
            command=lambda: select_all_in_text_widget(text_widget),
        )
        self.current_text_menu.add_command(
            label='Copy',
            command=lambda: copy_selection_from_text_widget(self, text_widget),
        )
        if allow_paste:
            self.current_text_menu.add_command(
                label='Paste',
                command=lambda: paste_text_into_widget(self, text_widget),
                state=paste_command_state,
            )
        if allow_undo:
            self.current_text_menu.add_command(
                label='Undo',
                command=lambda: undo_text_widget_edit(text_widget),
                state=undo_command_state,
            )
        if include_run_actions:
            has_selection = bool(self.selected_source_text().strip())
            run_command_state = tk.NORMAL if has_selection else tk.DISABLED
            if self.is_read_only():
                run_command_state = tk.DISABLED
            self.current_text_menu.add_separator()
            self.current_text_menu.add_command(
                label='Run',
                command=self.run_selected_source_text,
                state=run_command_state,
            )
            self.current_text_menu.add_command(
                label='Inspect',
                command=self.inspect_selected_source_text,
                state=run_command_state,
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
        source_text_was_disabled = self.source_text.cget('state') == tk.DISABLED
        if source_text_was_disabled:
            self.source_text.configure(state=tk.NORMAL)
        if source and source.strip():
            self.source_text.delete('1.0', tk.END)
            self.source_text.insert(tk.END, source)
            self.source_cursor_position_indicator.update_position()
        if source_text_was_disabled:
            self.source_text.configure(state=tk.DISABLED)
        if run_immediately:
            self.run_code_from_editor()

    def run_code_from_editor(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Run is disabled.')
            return
        self.status_label.config(text='Running...')
        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Running source...')
        try:
            try:
                code_to_run = self.source_text.get('1.0', 'end-1c')
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
        self.status_label.config(text='Completed successfully')
        self.clear_source_error_highlight()
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert(tk.END, result.asString().to_py)
        self.result_text.config(state='disabled')

    def on_run_error(self, exception):
        self.last_exception = exception
        error_text = str(exception)
        line_number, column_number = self.compile_error_location_for_exception(exception, error_text)
        self.show_source_error_highlight(line_number, column_number)
        self.show_error_in_result_panel(error_text, line_number, column_number)
        self.status_label.config(text=self.error_status_text(error_text, line_number, column_number))

    def clear_source_error_highlight(self):
        self.source_text.tag_remove('compile_error_location', '1.0', tk.END)

    def source_text_line_count(self):
        return int(self.source_text.index('end-1c').split('.')[0])

    def source_text_line(self, line_number):
        if line_number < 1:
            return None
        line_count = self.source_text_line_count()
        if line_number > line_count:
            return None
        return self.source_text.get(f'{line_number}.0', f'{line_number}.end')

    def show_source_error_highlight(self, line_number, column_number):
        self.clear_source_error_highlight()
        if line_number is None:
            return

        source_line = self.source_text_line(line_number)
        if source_line is None:
            return

        start_index = f'{line_number}.0'
        end_index = f'{line_number}.end'
        if column_number is not None and column_number > 0:
            bounded_column_number = column_number
            if bounded_column_number > len(source_line) + 1:
                bounded_column_number = len(source_line) + 1
            start_index = f'{line_number}.{bounded_column_number - 1}'
            end_index = f'{line_number}.{bounded_column_number}'

        self.source_text.tag_configure(
            'compile_error_location',
            background='#ffe4e4',
            underline=True,
        )
        self.source_text.tag_add('compile_error_location', start_index, end_index)
        self.source_text.see(start_index)

    def show_error_in_result_panel(self, error_text, line_number, column_number):
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert(tk.END, error_text)
        if line_number is not None and column_number is not None:
            source_line = self.source_text_line(line_number)
            if source_line is None:
                source_line = ''
            caret_padding = ''
            if column_number > 1:
                caret_padding = ' ' * (column_number - 1)
            self.result_text.insert(tk.END, f'\nLine {line_number}, column {column_number}\n')
            self.result_text.insert(tk.END, f'{source_line}\n')
            self.result_text.insert(tk.END, f'{caret_padding}^\n')
        self.result_text.config(state='disabled')

    def error_status_text(self, error_text, line_number, column_number):
        if line_number is not None and column_number is not None:
            return f'Error: {error_text} (line {line_number}, column {column_number})'
        return f'Error: {error_text}'

    def compile_error_location_for_exception(self, exception, error_text):
        line_number = None
        column_number = None

        line_number, column_number = self.compile_error_location_from_structured_arguments(exception)
        if line_number is None:
            line_number, column_number = self.compile_error_location_from_text(error_text)
            if line_number is None:
                message_text = self.compile_error_message_text(exception)
                line_number, column_number = self.compile_error_location_from_text(message_text)

        return line_number, column_number

    def compile_error_message_text(self, exception):
        message_text = ''
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

        full_match = re.search(r'line\s+(\d+)\s*[,;]?\s*column\s+(\d+)', error_text, re.IGNORECASE)
        if full_match:
            line_number = int(full_match.group(1))
            column_number = int(full_match.group(2))

        if line_number is None:
            inverted_match = re.search(r'column\s+(\d+)\s*[,;]?\s*line\s+(\d+)', error_text, re.IGNORECASE)
            if inverted_match:
                line_number = int(inverted_match.group(2))
                column_number = int(inverted_match.group(1))

        if line_number is None:
            line_only_match = re.search(r'line\s+(\d+)', error_text, re.IGNORECASE)
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

        size_value = self.python_error_value(self.message_send_result(sequence_value, 'size'))
        if not isinstance(size_value, int):
            return None
        if one_based_index < 1 or one_based_index > size_value:
            return None
        return self.message_send_result(sequence_value, 'at', one_based_index)

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

        to_py_value = getattr(candidate_value, 'to_py', None)
        if to_py_value is not None:
            if callable(to_py_value):
                try:
                    return to_py_value()
                except (GemstoneError, TypeError, AttributeError):
                    pass
            if not callable(to_py_value):
                return to_py_value

        as_string_result = self.message_send_result(candidate_value, 'asString')
        as_string_value = getattr(as_string_result, 'to_py', None)
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

        source_before_error = source_text[:bounded_offset - 1]
        line_number = source_before_error.count('\n') + 1
        last_newline_index = source_before_error.rfind('\n')
        column_number = bounded_offset
        if last_newline_index >= 0:
            column_number = len(source_before_error) - last_newline_index
        return line_number, column_number

    def open_debugger(self):
        if self.is_read_only():
            self.status_label.config(text='MCP is busy. Debug is disabled.')
            return
        code_to_run = self.source_text.get('1.0', 'end-1c')
        if not code_to_run.strip():
            self.status_label.config(text='No source to debug')
            return

        self.last_exception = None
        self.clear_source_error_highlight()
        self.application.begin_foreground_activity('Debugging source...')
        try:
            try:
                result = self.gemstone_session_record.run_code(code_to_run)
                self.on_run_complete(result)
                self.status_label.config(
                    text='Completed successfully; no debugger context',
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
        return 'compileerror' in error_text or 'compile error' in error_text

    def close_tab(self):
        if self.application.run_tab is self:
            self.application.run_tab = None
        try:
            self.application.notebook.forget(self)
        except tk.TclError:
            pass
        self.destroy()


class JsonResultDialog(tk.Toplevel):
    def __init__(self, parent, title, result_payload):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
        self.transient(parent)
        self.grab_set()
        self.focus_force()

        self.result_text = tk.Text(self, wrap='word')
        self.result_text.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        rendered_result = json.dumps(
            result_payload,
            indent=2,
            sort_keys=True,
            default=str,
        )
        self.result_text.insert('1.0', rendered_result)
        self.result_text.config(state='disabled')

        self.close_button = tk.Button(self, text='Close', command=self.destroy)
        self.close_button.pack(pady=10)


class FramedWidget(ttk.Frame):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, borderwidth=2, relief="sunken")
        self.browser_window = browser_window
        self.event_queue = event_queue
        self.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=1, pady=1)

    @property
    def gemstone_session_record(self):
        return self.browser_window.gemstone_session_record
    
    def destroy(self):
        super().destroy()
        self.event_queue.clear_subscribers(self)

    def show_test_result(self, result):
        if result['has_passed']:
            messagebox.showinfo('Test Result', f"Passed ({result['run_count']} run)")
        else:
            lines = [f"Failures: {result['failure_count']}, Errors: {result['error_count']}"]
            lines.extend(result['failures'])
            lines.extend(result['errors'])
            messagebox.showerror('Test Result', '\n'.join(lines))

class InteractiveSelectionList(ttk.Frame):
    def __init__(self, parent, get_all_entries, get_selected_entry, set_selected_to):
        super().__init__(parent)

        self.get_all_entries = get_all_entries
        self.get_selected_entry = get_selected_entry
        self.set_selected_to = set_selected_to
        self.synchronizing_selection = False

        # Filter entry to allow filtering listbox content
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', self.update_filter)
        self.filter_entry = tk.Entry(self, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, columnspan=2, sticky='ew')

        # Packages listbox to show filtered packages with scrollbar
        self.selection_listbox = tk.Listbox(self, selectmode=tk.SINGLE, exportselection=False)
        self.selection_listbox.grid(row=1, column=0, sticky='nsew')

        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.selection_listbox.yview)
        self.scrollbar.grid(row=1, column=1, sticky='ns')
        self.selection_listbox.config(yscrollcommand=self.scrollbar.set)

        # Configure weights for proper resizing
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Initial population of listbox
        self.repopulate()

        # Bind the listbox selection event
        self.selection_listbox.bind('<<ListboxSelect>>', self.handle_selection)
        
    def repopulate(self, origin=None):
        self.synchronizing_selection = True
        try:
            self.all_entries = self.get_all_entries()
            self.filter_var.set('')
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
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.selection_list = InteractiveSelectionList(self, self.get_all_packages, self.get_selected_package, self.select_package)
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
                                                       
        # Initial population of listbox
        self.repopulate()

        # Subscribe to event_queue for any "Aborted" event
        self.event_queue.subscribe('PackagesChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def select_package(self, selected_package):
        self.gemstone_session_record.select_package(selected_package)
        self.event_queue.publish('SelectedPackageChanged', origin=self)
        
    def get_all_packages(self):
        return list(self.browser_window.gemstone_session_record.class_categories)

    def get_selected_package(self):
        return self.gemstone_session_record.selected_package
        
    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            idx = listbox.nearest(event.y)
            listbox.selection_clear(0, 'end')
            listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        command_state = tk.NORMAL
        if self.browser_window.application.integrated_session_state.is_mcp_busy():
            command_state = tk.DISABLED
        delete_command_state = command_state if has_selection else tk.DISABLED
        menu.add_command(
            label='Add Package',
            command=self.add_package,
            state=command_state,
        )
        menu.add_command(
            label='Delete Package',
            command=self.delete_package,
            state=delete_command_state,
        )
        menu.tk_popup(event.x_root, event.y_root)

    def add_package(self):
        package_name = simpledialog.askstring('Add Package', 'Package name:')
        if not package_name:
            return
        try:
            package_name = package_name.strip()
            if not package_name:
                return
            self.gemstone_session_record.create_and_install_package(package_name)
            self.gemstone_session_record.select_package(package_name)
            self.selection_list.repopulate()
            self.event_queue.publish('SelectedPackageChanged', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Package', str(error))

    def delete_package(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        package_name = listbox.get(selection[0])
        should_delete = messagebox.askyesno(
            'Delete Package',
            (
                'Delete package %s and all classes in it? '
                'This cannot be undone.'
            )
            % package_name,
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_package(package_name)
            self.selection_list.repopulate()
            self.event_queue.publish('SelectedPackageChanged', origin=self)
            self.event_queue.publish('SelectedClassChanged', origin=self)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Package', str(error))

            
class ClassSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.classes_notebook = ttk.Notebook(self)
        self.classes_notebook.grid(row=0, column=0, columnspan=2, sticky='nsew')

        self.rowconfigure(0, weight=3, minsize=180)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.selection_list = InteractiveSelectionList(self, self.get_all_classes, self.get_selected_class, self.select_class)
        self.selection_list.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.selection_list, text='List')

        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.hierarchy_frame.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(
            self.hierarchy_frame,
            columns=('class_category',),
            show='tree headings',
        )
        self.hierarchy_tree.grid(row=0, column=0, sticky='nsew')
        self.hierarchy_frame.rowconfigure(0, weight=1)
        self.hierarchy_frame.columnconfigure(0, weight=1)
        self.hierarchy_tree.heading('#0', text='Class')
        self.hierarchy_tree.heading('class_category', text='Class Category')
        self.hierarchy_tree.column('#0', width=260, anchor='w')
        self.hierarchy_tree.column('class_category', width=180, anchor='w')
        self.hierarchy_item_by_class_name = {}
        self.synchronizing_hierarchy_selection = False
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.repopulate_categories)
        self.classes_notebook.bind(
            '<<NotebookTabChanged>>',
            self.handle_classes_notebook_changed,
        )

        self.selection_var = tk.StringVar(value='instance' if self.gemstone_session_record.show_instance_side else 'class')
        self.syncing_side_selection = False
        self.selection_var.trace_add('write', lambda name, index, operation: self.switch_side())
        self.class_controls_frame = ttk.Frame(self)
        self.class_controls_frame.grid(
            column=0,
            row=2,
            columnspan=2,
            sticky='ew',
        )
        self.class_controls_frame.columnconfigure(0, weight=0)
        self.class_controls_frame.columnconfigure(1, weight=0)
        self.class_controls_frame.columnconfigure(2, weight=1)
        self.class_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text='Class',
            variable=self.selection_var,
            value='class',
        )
        self.instance_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text='Instance',
            variable=self.selection_var,
            value='instance',
        )
        self.class_radiobutton.grid(column=0, row=0, sticky='w')
        self.instance_radiobutton.grid(column=1, row=0, sticky='w')
        self.show_class_definition_var = tk.BooleanVar(value=False)
        self.show_class_definition_checkbox = tk.Checkbutton(
            self.class_controls_frame,
            text='Show Class Definition',
            variable=self.show_class_definition_var,
            command=self.toggle_class_definition,
        )
        self.show_class_definition_checkbox.grid(
            column=2,
            row=0,
            sticky='e',
        )
        self.class_definition_frame = ttk.Frame(self)
        self.class_definition_frame.grid(
            column=0,
            row=3,
            columnspan=2,
            sticky='nsew',
        )
        self.class_definition_frame.rowconfigure(0, weight=1)
        self.class_definition_frame.columnconfigure(1, weight=1)
        self.class_definition_text = tk.Text(
            self.class_definition_frame,
            wrap='word',
            height=8,
        )
        self.class_definition_line_number_column = CodeLineNumberColumn(
            self.class_definition_frame,
            self.class_definition_text,
        )
        self.class_definition_line_number_column.line_numbers_text.grid(
            column=0,
            row=0,
            sticky='ns',
        )
        self.class_definition_text.grid(
            column=1,
            row=0,
            sticky='nsew',
        )
        self.class_definition_cursor_position_label = ttk.Label(
            self.class_definition_frame,
            text='Ln 1, Col 1',
        )
        self.class_definition_cursor_position_label.grid(
            column=1,
            row=1,
            sticky='e',
            pady=(2, 0),
        )
        self.class_definition_cursor_position_indicator = (
            TextCursorPositionIndicator(
                self.class_definition_text,
                self.class_definition_cursor_position_label,
            )
        )
        self.class_definition_text.config(state='disabled')
        self.class_definition_frame.grid_remove()

        self.rowconfigure(1, weight=0)
        self.rowconfigure(3, weight=0, minsize=0)

        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('PackagesChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def switch_side(self):
        if self.syncing_side_selection:
            return
        self.gemstone_session_record.select_instance_side(self.show_instance_side)
        self.event_queue.publish('SelectedClassChanged')

    @property
    def show_instance_side(self):
        return self.selection_var.get() == 'instance'  

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                selected_index = widget.curselection()[0]
                selected_class = widget.get(selected_index)
                self.select_class(
                    selected_class,
                    selection_source='list',
                )
                return
            if isinstance(widget, ttk.Treeview):
                if self.synchronizing_hierarchy_selection:
                    return
                selected_item_id = widget.selection()[0]
                selected_class = widget.item(selected_item_id, 'text')
                class_values = widget.item(selected_item_id, 'values')
                class_category = class_values[0] if class_values else ''
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
                    selection_source='hierarchy',
                    class_category=class_category,
                )
        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            expected_side = (
                'instance'
                if self.gemstone_session_record.show_instance_side
                else 'class'
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
                class_name: class_definition.get('superclass_name')
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
                '',
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
                    'class_name': class_name,
                    'superclass_name': None,
                    'package_name': '',
                }
                try:
                    fetched_class_definition = (
                        self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                            class_name,
                        )
                    )
                    class_definition.update(fetched_class_definition)
                except GemstoneDomainException:
                    pass
                superclass_name = class_definition.get('superclass_name')
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
            class_category = class_definition.get('package_name') or ''
            child_item_id = self.hierarchy_tree.insert(
                parent_item_id,
                'end',
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
        selected_package = self.gemstone_session_record.selected_package
        return list(self.browser_window.gemstone_session_record.get_classes_in_category(selected_package))

    def get_selected_class(self):
        return self.gemstone_session_record.selected_class

    def select_class(
        self,
        selected_class,
        selection_source='list',
        class_category='',
    ):
        selected_package = self.gemstone_session_record.selected_package
        if selection_source == 'hierarchy':
            selected_package = class_category
            if not selected_package:
                try:
                    class_definition = (
                        self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                            selected_class,
                        )
                    )
                except (GemstoneDomainException, GemstoneError):
                    class_definition = {}
                selected_package = class_definition.get('package_name') or selected_package
            if selected_package:
                self.gemstone_session_record.select_package(selected_package)
                self.selection_list.repopulate()
        self.gemstone_session_record.select_class(selected_class)
        if selection_source == 'hierarchy':
            self.gemstone_session_record.select_method_category('all')
        self.refresh_class_definition()
        self.event_queue.publish('SelectedClassChanged', origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            idx = listbox.nearest(event.y)
            listbox.selection_clear(0, 'end')
            listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        read_only = self.browser_window.application.integrated_session_state.is_mcp_busy()
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = (
            write_command_state if has_selection else tk.DISABLED
        )
        menu.add_command(
            label='Add Class',
            command=self.add_class,
            state=write_command_state,
        )
        menu.add_command(
            label='Delete Class',
            command=self.delete_class,
            state=delete_command_state,
        )
        menu.add_command(
            label='Run All Tests',
            command=self.run_all_tests,
            state=run_command_state,
        )
        menu.tk_popup(event.x_root, event.y_root)

    def add_class(self):
        selected_package = self.gemstone_session_record.selected_package
        if not selected_package:
            messagebox.showerror('Add Class', 'Select a package first.')
            return
        class_name = simpledialog.askstring('Add Class', 'Class name:')
        if class_name is None:
            return
        class_name = class_name.strip()
        if not class_name:
            return
        superclass_name = simpledialog.askstring(
            'Add Class',
            'Superclass name:',
            initialvalue='Object',
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
                in_dictionary=selected_package,
            )
            self.gemstone_session_record.select_class(class_name)
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish('SelectedClassChanged', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Class', str(error))

    def delete_class(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        selected_package = self.gemstone_session_record.selected_package
        should_delete = messagebox.askyesno(
            'Delete Class',
            (
                'Delete class %s from package %s? '
                'This cannot be undone.'
            )
            % (class_name, selected_package or 'UserGlobals'),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_class(
                class_name,
                in_dictionary=selected_package,
            )
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish('SelectedClassChanged', origin=self)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Class', str(error))

    def toggle_class_definition(self):
        if self.show_class_definition_var.get():
            self.rowconfigure(3, weight=2, minsize=120)
            self.class_definition_frame.grid()
            self.refresh_class_definition()
            return
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.config(state='disabled')
        self.class_definition_frame.grid_remove()
        self.rowconfigure(3, weight=0, minsize=0)

    def formatted_class_definition(self, class_definition):
        class_name = class_definition.get('class_name') or ''
        superclass_name = class_definition.get('superclass_name') or 'Object'
        package_name = class_definition.get('package_name') or ''
        inst_var_names = class_definition.get('inst_var_names') or []
        class_var_names = class_definition.get('class_var_names') or []
        class_inst_var_names = class_definition.get('class_inst_var_names') or []
        pool_dictionary_names = class_definition.get('pool_dictionary_names') or []
        return (
            f"{superclass_name} subclass: '{class_name}'\n"
            f'    instVarNames: {self.symbol_array_literal(inst_var_names)}\n'
            f'    classVars: {self.symbol_array_literal(class_var_names)}\n'
            f'    classInstVars: {self.symbol_array_literal(class_inst_var_names)}\n'
            f'    poolDictionaries: {self.symbol_array_literal(pool_dictionary_names)}\n'
            f'    inDictionary: {package_name}'
        )

    def symbol_array_literal(self, symbol_names):
        if not symbol_names:
            return '#()'
        return '#(%s)' % ' '.join(symbol_names)

    def refresh_class_definition(self):
        if not self.show_class_definition_var.get():
            return
        class_definition_text = ''
        selected_class = self.gemstone_session_record.selected_class
        if selected_class:
            try:
                class_definition = (
                    self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        selected_class,
                    )
                )
                class_definition_text = self.formatted_class_definition(
                    class_definition,
                )
            except (GemstoneDomainException, GemstoneError):
                class_definition_text = ''
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.insert('1.0', class_definition_text)
        self.class_definition_text.config(state='disabled')
        self.class_definition_cursor_position_indicator.update_position()

    def run_all_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            'Running tests in %s...' % class_name
        )
        try:
            try:
                result = self.gemstone_session_record.run_gemstone_tests(class_name)
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Run All Tests', str(domain_exception))
            except GemstoneError as e:
                self.browser_window.application.open_debugger(e)
        finally:
            self.browser_window.application.end_foreground_activity()

                    
class CategorySelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        # Create InteractiveSelectionList for categories
        self.selection_list = InteractiveSelectionList(self, self.get_all_categories, self.get_selected_category, self.select_category)
        self.selection_list.grid(row=0, column=0, sticky="nsew")

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

    def repopulate_class_and_instance(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            self.selected_category = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_category(self.selected_category)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
        except IndexError:
            pass
        
    def repopulate(self, origin=None):
        if origin is self:
            return
        self.selection_list.repopulate()

    def get_all_categories(self):
        if self.gemstone_session_record.selected_class:
            # Repopulate InteractiveSelectionList with new options based on the selected class
            return ['all'] + list(self.gemstone_session_record.get_categories_in_class(
                self.gemstone_session_record.selected_class, 
                self.gemstone_session_record.show_instance_side
            ))
        else:
            return  []

    def get_selected_category(self):
        return self.gemstone_session_record.selected_method_category

    def select_category(self, selected_category):
        self.gemstone_session_record.select_method_category(selected_category)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)

        
class MethodSelection(FramedWidget):        
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        # Create InteractiveSelectionList for methods
        self.selection_list = InteractiveSelectionList(self, self.get_all_methods, self.get_selected_method, self.select_method)
        self.selection_list.grid(row=0, column=0, sticky="nsew")
        self.controls_frame = ttk.Frame(self)
        self.controls_frame.grid(row=1, column=0, sticky='ew')
        self.controls_frame.columnconfigure(0, weight=1)
        self.show_method_hierarchy_var = tk.BooleanVar(value=False)
        self.show_method_hierarchy_checkbox = tk.Checkbutton(
            self.controls_frame,
            text='Show Method Inheritance',
            variable=self.show_method_hierarchy_var,
            command=self.toggle_method_hierarchy,
        )
        self.show_method_hierarchy_checkbox.grid(row=0, column=0, sticky='w')
        self.add_method_button = tk.Button(
            self.controls_frame,
            text='Add Method',
            command=self.add_method,
        )
        self.add_method_button.grid(row=0, column=1, sticky='e')
        self.method_hierarchy_tree = ttk.Treeview(
            self,
            show='tree',
        )
        self.method_hierarchy_tree.heading('#0', text='Class')
        self.method_hierarchy_tree.column('#0', width=240, anchor='w')
        self.method_hierarchy_tree.grid(row=2, column=0, sticky='nsew')
        self.method_hierarchy_tree.grid_remove()
        self.method_hierarchy_tree.bind(
            '<<TreeviewSelect>>',
            self.method_hierarchy_selected,
        )
        self.syncing_method_hierarchy_selection = False

        # Configure the grid layout to expand properly
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        # Subscribe to event_queue events
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('MethodSelected', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_method = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_symbol(selected_method)
            self.selection_changed = False
            self.event_queue.publish('MethodSelected', origin=self)

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
        self.event_queue.publish('MethodSelected', origin=self)

    def new_method_argument_names(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        if selector_tokens:
            return [
                f'argument{index + 1}'
                for index in range(len(selector_tokens))
            ]
        if self.is_binary_selector(method_selector):
            return ['argument1']
        return []

    def keyword_selector_tokens(self, method_selector):
        if ':' not in method_selector:
            return []
        selector_parts = method_selector.split(':')
        if not selector_parts or selector_parts[-1] != '':
            return []
        keyword_tokens = []
        for selector_part in selector_parts[:-1]:
            is_valid_selector_part = re.fullmatch(
                r'[A-Za-z][A-Za-z0-9_]*',
                selector_part,
            )
            if is_valid_selector_part is None:
                return []
            keyword_tokens.append(f'{selector_part}:')
        return keyword_tokens

    def is_binary_selector(self, method_selector):
        if not method_selector:
            return False
        binary_characters = '+-*/\\~<>=@%,|&?!'
        return all(
            character in binary_characters
            for character in method_selector
        )

    def new_method_header(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        argument_names = self.new_method_argument_names(method_selector)
        if selector_tokens:
            return ' '.join(
                [
                    f'{selector_tokens[token_index]} {argument_names[token_index]}'
                    for token_index in range(len(selector_tokens))
                ]
            )
        if self.is_binary_selector(method_selector):
            return f'{method_selector} {argument_names[0]}'
        return method_selector

    def new_method_source(self, method_selector):
        method_header = self.new_method_header(method_selector)
        return f'{method_header}\n    ^self'

    def add_method(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            messagebox.showerror('Add Method', 'Select a class first.')
            return
        method_selector = simpledialog.askstring('Add Method', 'Method selector:')
        if method_selector is None:
            return
        method_selector = method_selector.strip()
        if not method_selector:
            return
        method_category = 'as yet unclassified'
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
            self.event_queue.publish('SelectedClassChanged', origin=self)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Method', str(error))

    def toggle_method_hierarchy(self):
        if self.show_method_hierarchy_var.get():
            self.method_hierarchy_tree.grid()
            self.refresh_method_hierarchy()
        else:
            self.method_hierarchy_tree.delete(
                *self.method_hierarchy_tree.get_children(),
            )
            self.method_hierarchy_tree.grid_remove()

    def refresh_method_hierarchy(self):
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        inheritance_entries = self.method_inheritance_entries()
        parent_item_id = ''
        selected_item_id = None
        selected_class = self.gemstone_session_record.selected_class
        for inheritance_entry in inheritance_entries:
            item_id = self.method_hierarchy_tree.insert(
                parent_item_id,
                'end',
                text=inheritance_entry['class_name'],
            )
            if inheritance_entry['class_name'] == selected_class:
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
                        'class_name': class_name,
                        'method_selector': method_selector,
                    },
                )
        return inheritance_entries

    def superclass_chain_for_method_inheritance(self, class_name):
        superclass_chain = []
        current_class_name = class_name
        while current_class_name:
            superclass_chain.append(current_class_name)
            try:
                class_definition = (
                    self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        current_class_name,
                    )
                )
            except GemstoneDomainException:
                class_definition = {}
            current_class_name = class_definition.get('superclass_name')
        superclass_chain.reverse()
        return superclass_chain

    def method_hierarchy_selected(self, event):
        if self.syncing_method_hierarchy_selection:
            return
        try:
            selected_item_id = event.widget.selection()[0]
        except IndexError:
            return
        selected_class = event.widget.item(selected_item_id, 'text')
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
            selected_method_category = (
                self.gemstone_session_record.gemstone_browser_session.get_method_category(
                    selected_class,
                    selected_method,
                    show_instance_side,
                )
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(selected_class)
            self.gemstone_session_record.select_method_category(
                selected_method_category,
            )
            self.gemstone_session_record.select_method_symbol(selected_method)
        self.event_queue.publish('SelectedClassChanged', origin=self)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)
        self.event_queue.publish('MethodSelected', origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            idx = listbox.nearest(event.y)
            listbox.selection_clear(0, 'end')
            listbox.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        read_only = self.browser_window.application.integrated_session_state.is_mcp_busy()
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = (
            write_command_state if has_selection else tk.DISABLED
        )
        menu.add_command(
            label='Add Method',
            command=self.add_method,
            state=write_command_state,
        )
        menu.add_command(
            label='Delete Method',
            command=self.delete_method,
            state=delete_command_state,
        )
        menu.add_separator()
        menu.add_command(
            label='Run Test',
            command=self.run_test,
            state=run_command_state,
        )
        menu.add_command(
            label='Debug Test',
            command=self.debug_test,
            state=run_command_state,
        )
        menu.tk_popup(event.x_root, event.y_root)

    def delete_method(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        show_instance_side = self.gemstone_session_record.show_instance_side
        method_selector = listbox.get(selection[0])
        should_delete = messagebox.askyesno(
            'Delete Method',
            (
                'Delete %s>>%s? This cannot be undone.'
            )
            % (class_name, method_selector),
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
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Method', str(error))

    def run_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            'Running test %s>>%s...' % (class_name, method_selector)
        )
        try:
            try:
                result = self.gemstone_session_record.run_test_method(
                    class_name,
                    method_selector,
                )
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Run Test', str(domain_exception))
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
            'Debugging test %s>>%s...' % (class_name, method_selector)
        )
        try:
            try:
                self.gemstone_session_record.debug_test_method(
                    class_name,
                    method_selector,
                )
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Debug Test', str(domain_exception))
            except GemstoneError as e:
                self.browser_window.application.open_debugger(e)
        finally:
            self.browser_window.application.end_foreground_activity()

        
class MethodNavigationHistory:
    def __init__(self, maximum_entries=200):
        self.maximum_entries = maximum_entries
        self.entries = []
        self.current_index = -1

    def current_method(self):
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    def record(self, method_context):
        if method_context is None:
            return
        if self.current_method() == method_context:
            return
        if self.current_index < len(self.entries) - 1:
            self.entries = self.entries[: self.current_index + 1]
        self.entries.append(method_context)
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
        return self.current_method()

    def go_forward(self):
        if not self.can_go_forward():
            return None
        self.current_index += 1
        return self.current_method()

    def jump_to(self, history_index):
        if history_index < 0:
            return None
        if history_index >= len(self.entries):
            return None
        self.current_index = history_index
        return self.current_method()

    def entries_with_current_marker(self):
        entry_details = []
        for index, method_context in enumerate(self.entries):
            entry_details.append(
                {
                    'history_index': index,
                    'method_context': method_context,
                    'is_current': index == self.current_index,
                },
            )
        return entry_details


class MethodEditor(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, browser_window, event_queue, row, column, colspan=colspan)

        self.current_menu = None
        self.method_navigation_history = MethodNavigationHistory()
        self.history_choice_indices = []

        self.navigation_bar = ttk.Frame(self)
        self.navigation_bar.grid(row=0, column=0, sticky='ew')
        self.navigation_bar.columnconfigure(0, weight=1)

        self.label_bar = tk.Label(self.navigation_bar, text='Method Editor', anchor='w')
        self.label_bar.grid(row=0, column=0, sticky='ew')

        self.back_button = ttk.Button(
            self.navigation_bar,
            text='Back',
            command=self.go_to_previous_method,
        )
        self.back_button.grid(row=0, column=1, padx=(6, 0))

        self.forward_button = ttk.Button(
            self.navigation_bar,
            text='Forward',
            command=self.go_to_next_method,
        )
        self.forward_button.grid(row=0, column=2, padx=(4, 0))

        self.history_combobox = ttk.Combobox(
            self.navigation_bar,
            state='readonly',
            width=44,
        )
        self.history_combobox.grid(row=0, column=3, padx=(6, 0), sticky='e')
        self.history_combobox.bind(
            '<<ComboboxSelected>>',
            self.jump_to_selected_history_entry,
        )

        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.grid(row=1, column=0, sticky='nsew')
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.editor_notebook.bind('<Motion>', self.on_tab_motion)
        self.editor_notebook.bind('<Leave>', self.on_tab_leave)

        self.open_tabs = {}

        self.event_queue.subscribe('MethodSelected', self.open_method)
        self.event_queue.subscribe(
            'MethodSelected',
            self.record_method_navigation,
        )
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe(
            'McpBusyStateChanged',
            self.handle_mcp_busy_state_changed,
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
        tab_id = self.open_tabs[tab.tab_key]
        self.editor_notebook.forget(tab_id)
        if tab.tab_key in self.open_tabs:
            del self.open_tabs[tab.tab_key]

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
            return f'{class_name}>>{method_symbol}'
        return f'{class_name} class>>{method_symbol}'

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
            history_index = history_entry['history_index']
            method_context = history_entry['method_context']
            history_labels.append(self.method_context_label(method_context))
            self.history_choice_indices.append(history_index)
        self.history_combobox['values'] = history_labels

        if len(history_labels) > 0:
            current_history_index = self.method_navigation_history.current_index
            selected_index = len(history_labels) - current_history_index - 1
            self.history_combobox.current(selected_index)
        if len(history_labels) == 0:
            self.history_combobox.set('')

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

        if method_context in self.open_tabs:
            self.editor_notebook.select(self.open_tabs[method_context])
            return

        new_tab = EditorTab(
            self.editor_notebook,
            self.browser_window,
            self,
            method_context,
        )
        self.editor_notebook.add(new_tab, text=selected_method_symbol)
        self.editor_notebook.select(new_tab)
        self.open_tabs[method_context] = new_tab
        new_tab.code_panel.set_read_only(
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )

    def set_read_only(self, read_only):
        for open_tab in self.open_tabs.values():
            open_tab.code_panel.set_read_only(read_only)

    def handle_mcp_busy_state_changed(self, is_busy=False, operation_name=''):
        self.set_read_only(is_busy)

    def on_tab_motion(self, event):
        try:
            tab_index = self.editor_notebook.index('@%d,%d' % (event.x, event.y))
            if tab_index is not None:
                tab_key = self.get_tab(tab_index).tab_key
                if tab_key[1]:
                    text = f'{tab_key[0]}>>{tab_key[2]}'
                else:
                    text = f'{tab_key[0]} class>>{tab_key[2]}'
                self.label_bar.config(text=text)
        except tk.TclError:
            pass

    def on_tab_leave(self, event):
        self.label_bar.config(text='Method Editor')


class CodePanel(tk.Frame):
    def __init__(self, parent, application, tab_key=None):
        super().__init__(parent)

        self.application = application
        self.tab_key = tab_key

        self.text_editor = tk.Text(self, tabs=('4',), wrap='none', undo=True)

        self.scrollbar_y = tk.Scrollbar(
            self,
            orient='vertical',
            command=self.text_editor.yview,
        )
        self.scrollbar_x = tk.Scrollbar(
            self,
            orient='horizontal',
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
            sticky='ns',
        )
        self.text_editor.grid(row=0, column=1, sticky='nsew')
        self.scrollbar_y.grid(row=0, column=2, sticky='ns')
        self.scrollbar_x.grid(row=1, column=1, sticky='ew')
        self.cursor_position_label = ttk.Label(self, text='Ln 1, Col 1')
        self.cursor_position_label.grid(
            row=2,
            column=1,
            sticky='e',
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

        self.text_editor.bind('<Control-a>', self.select_all_text_editor)
        self.text_editor.bind('<Control-A>', self.select_all_text_editor)
        self.text_editor.bind('<Control-c>', self.copy_text_editor_selection)
        self.text_editor.bind('<Control-C>', self.copy_text_editor_selection)
        self.text_editor.bind('<Control-v>', self.paste_into_text_editor)
        self.text_editor.bind('<Control-V>', self.paste_into_text_editor)
        self.text_editor.bind('<Control-z>', self.undo_text_editor)
        self.text_editor.bind('<Control-Z>', self.undo_text_editor)
        self.text_editor.bind('<KeyPress>', self.replace_selected_text_editor_before_typing, add='+')
        self.text_editor.bind("<KeyRelease>", self.on_key_release)
        self.text_editor.bind("<Button-3>", self.open_text_menu)

        self.current_context_menu = None
        self.text_editor.bind("<Button-1>", self.close_context_menu, add="+")

    def is_read_only(self):
        return self.application.integrated_session_state.is_mcp_busy()

    def set_read_only(self, read_only):
        text_state = tk.NORMAL
        if read_only:
            text_state = tk.DISABLED
        self.text_editor.configure(state=text_state)

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
        has_complete_context = (
            class_name is not None and method_selector is not None
        )
        if not has_complete_context:
            return None
        return (class_name, show_instance_side, method_selector)

    def selected_text(self):
        try:
            return self.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            return ''

    def select_all_text_editor(self, event=None):
        select_all_in_text_widget(self.text_editor)
        return 'break'

    def copy_text_editor_selection(self, event=None):
        copy_selection_from_text_widget(self, self.text_editor)
        return 'break'

    def paste_into_text_editor(self, event=None):
        paste_text_into_widget(self, self.text_editor)
        return 'break'

    def undo_text_editor(self, event=None):
        undo_text_widget_edit(self.text_editor)
        return 'break'

    def replace_selected_text_editor_before_typing(self, event):
        replace_selected_range_before_typing(self.text_editor, event)

    def selector_token(self, token_text):
        candidate = (token_text or '').strip()
        if not candidate:
            return None
        is_identifier_selector = re.fullmatch(
            r'[A-Za-z_]\w*(?::[A-Za-z_]\w*)*:?',
            candidate,
        )
        if is_identifier_selector:
            return candidate
        keyword_tokens = re.findall(
            r'[A-Za-z_]\w*:',
            candidate,
        )
        if keyword_tokens:
            return ''.join(keyword_tokens)
        is_binary_selector = re.fullmatch(r'[-+*/\\~<>=@%,|&?!]+', candidate)
        if is_binary_selector:
            return candidate
        return None

    def cursor_offset(self):
        cursor_index = self.text_editor.index(tk.INSERT)
        characters = self.text_editor.count('1.0', cursor_index, 'chars')
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
        for send_entry in sends_payload.get('sends', []):
            starts_before_or_at_cursor = (
                send_entry['start_offset'] <= cursor_offset
            )
            ends_after_cursor = cursor_offset < send_entry['end_offset']
            if starts_before_or_at_cursor and ends_after_cursor:
                return send_entry
        return None

    def word_under_cursor(self):
        line, column = self.text_editor.index(tk.INSERT).split('.')
        line_text = self.text_editor.get(f'{line}.0', f'{line}.end')
        cursor_column = int(column)
        token_matches = [
            match
            for match in re.finditer(
                r'[-+*/\\~<>=@%,|&?!]+|[A-Za-z_]\w*:?',
                line_text,
            )
            if match.start() <= cursor_column <= match.end()
        ]
        token_match = token_matches[0] if token_matches else None
        if token_match is None:
            return ''
        return token_match.group(0)

    def selector_for_navigation(self):
        selected_text = self.selected_text()
        selector_from_selection = self.selector_token(selected_text)
        if selector_from_selection is not None:
            return selector_from_selection
        send_entry = self.selector_entry_at_cursor()
        if send_entry is not None:
            return send_entry['selector']
        selector_from_cursor = self.selector_token(self.word_under_cursor())
        if selector_from_cursor is not None:
            return selector_from_cursor
        method_context = self.method_context()
        if method_context is None:
            return None
        return method_context[2]

    def open_text_menu(self, event):
        self.text_editor.mark_set(tk.INSERT, f'@{event.x},{event.y}')
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
            label='Select All',
            command=self.select_all_text_editor,
        )
        self.current_context_menu.add_command(
            label='Copy',
            command=self.copy_text_editor_selection,
        )
        self.current_context_menu.add_command(
            label='Paste',
            command=self.paste_into_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Undo',
            command=self.undo_text_editor,
            state=write_command_state,
        )
        self.current_context_menu.add_separator()
        active_editor_tab = self.active_editor_tab()
        if active_editor_tab is not None:
            self.current_context_menu.add_command(
                label='Jump to Class',
                command=self.jump_to_method_context,
            )
            self.current_context_menu.add_separator()
            self.current_context_menu.add_command(
                label='Save',
                command=self.save_current_tab,
                state=write_command_state,
            )
            self.current_context_menu.add_command(
                label='Close',
                command=self.close_current_tab,
            )
            self.current_context_menu.add_separator()
        selected_text = self.selected_text()
        if selected_text:
            self.current_context_menu.add_command(
                label='Run',
                command=lambda: self.run_selected_text(selected_text),
                state=run_command_state,
            )
            self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Find Implementors',
            command=self.open_implementors_from_source,
        )
        self.current_context_menu.add_command(
            label='Find Senders',
            command=self.open_senders_from_source,
        )
        self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Method Sends',
            command=self.show_method_sends,
        )
        self.current_context_menu.add_command(
            label='Method Structure',
            command=self.show_method_structure,
        )
        self.current_context_menu.add_command(
            label='Method Control Flow',
            command=self.show_method_control_flow,
        )
        self.current_context_menu.add_command(
            label='Method AST',
            command=self.show_method_ast,
        )
        self.current_context_menu.add_separator()
        self.current_context_menu.add_command(
            label='Apply Rename Method',
            command=self.apply_method_rename,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Apply Move Method',
            command=self.apply_method_move,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Apply Add Parameter',
            command=self.apply_method_add_parameter,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Apply Remove Parameter',
            command=self.apply_method_remove_parameter,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Apply Extract Method',
            command=self.apply_method_extract,
            state=write_command_state,
        )
        self.current_context_menu.add_command(
            label='Apply Inline Method',
            command=self.apply_method_inline,
            state=write_command_state,
        )
        self.current_context_menu.post(event.x_root, event.y_root)

    def active_editor_tab(self):
        parent_widget = self.master
        has_editor_tab_shape = (
            parent_widget is not None
            and hasattr(parent_widget, 'save')
            and hasattr(parent_widget, 'method_editor')
        )
        if not has_editor_tab_shape:
            return None
        return parent_widget

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

    def jump_to_method_context(self):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
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
                'Read Only',
                'MCP is busy. Run is disabled until MCP finishes.',
            )
            return
        self.application.run_code(selected_text)

    def open_implementors_from_source(self):
        selector = self.selector_for_navigation()
        if selector is None:
            messagebox.showwarning(
                'No Selector',
                'Could not determine a selector at the current cursor position.',
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
        self.application.open_senders_dialog(method_symbol=selector)

    def run_method_analysis(self, analysis_function, title):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
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
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(self.application, title, analysis_result)

    def show_method_sends(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_sends,
            'Method Sends',
        )

    def show_method_structure(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_structure_summary,
            'Method Structure',
        )

    def show_method_control_flow(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_control_flow_summary,
            'Method Control Flow',
        )

    def show_method_ast(self):
        self.run_method_analysis(
            self.gemstone_session_record.method_ast,
            'Method AST',
        )

    def new_selector_name(self, default_selector):
        return simpledialog.askstring(
            'Rename Method',
            'New selector name:',
            initialvalue=default_selector,
            parent=self.application,
        )

    def run_method_rename(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, old_selector = method_context
        new_selector = self.new_selector_name(old_selector)
        if not new_selector:
            return
        if apply_change:
            should_apply = messagebox.askyesno(
                'Confirm Rename',
                (
                    'Apply rename of %s to %s on %s (%s side)?'
                    % (
                        old_selector,
                        new_selector,
                        class_name,
                        'instance' if show_instance_side else 'class',
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
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Method Rename %s' % ('Apply' if apply_change else 'Preview'),
            rename_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_rename(self):
        self.run_method_rename(apply_change=False)

    def apply_method_rename(self):
        self.run_method_rename(apply_change=True)

    def side_input_to_boolean(self, side_input):
        normalized_side = (side_input or '').strip().lower()
        if normalized_side in ('instance', 'instance side', 'i'):
            return True
        if normalized_side in ('class', 'class side', 'meta', 'c'):
            return False
        return None

    def move_target_details(self, show_instance_side):
        target_class_name = simpledialog.askstring(
            'Move Method',
            'Target class name:',
            parent=self.application,
        )
        if not target_class_name:
            return None
        default_side = 'instance' if show_instance_side else 'class'
        target_side = simpledialog.askstring(
            'Move Method',
            'Target side (instance/class):',
            initialvalue=default_side,
            parent=self.application,
        )
        target_show_instance_side = self.side_input_to_boolean(target_side)
        if target_show_instance_side is None:
            messagebox.showerror(
                'Invalid Side',
                'Target side must be instance or class.',
            )
            return None
        return (target_class_name, target_show_instance_side)

    def run_method_move(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
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
                'Move Method',
                'Overwrite target method when it already exists?',
            )
            delete_source_method = messagebox.askyesno(
                'Move Method',
                'Delete source method after move?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Move',
                (
                    'Apply move of %s from %s (%s side) to %s (%s side)?'
                    % (
                        method_selector,
                        source_class_name,
                        'instance' if source_show_instance_side else 'class',
                        target_class_name,
                        'instance' if target_show_instance_side else 'class',
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
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Method Move %s' % ('Apply' if apply_change else 'Preview'),
            move_result,
        )
        if apply_change:
            self.application.event_queue.publish('SelectedClassChanged')
            self.application.event_queue.publish('SelectedCategoryChanged')
            self.application.event_queue.publish('MethodSelected')

    def preview_method_move(self):
        self.run_method_move(apply_change=False)

    def apply_method_move(self):
        self.run_method_move(apply_change=True)

    def parameter_keyword_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Parameter keyword (for example with:):',
            initialvalue='with:',
            parent=self.application,
        )

    def parameter_name_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Parameter name:',
            initialvalue='newValue',
            parent=self.application,
        )

    def default_argument_source_input(self):
        return simpledialog.askstring(
            'Add Parameter',
            'Default argument source expression:',
            initialvalue='nil',
            parent=self.application,
        )

    def run_method_add_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
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
                'Confirm Add Parameter',
                (
                    'Apply add-parameter on %s>>%s with keyword %s?'
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
                add_parameter_result = self.gemstone_session_record.apply_method_add_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    parameter_name,
                    default_argument_source,
                )
            else:
                add_parameter_result = self.gemstone_session_record.preview_method_add_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    parameter_name,
                    default_argument_source,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Add Parameter %s' % ('Apply' if apply_change else 'Preview'),
            add_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=False)

    def apply_method_add_parameter(self):
        self.run_method_add_parameter(apply_change=True)

    def remove_parameter_keyword_input(self):
        return simpledialog.askstring(
            'Remove Parameter',
            'Parameter keyword to remove:',
            parent=self.application,
        )

    def run_method_remove_parameter(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        parameter_keyword = self.remove_parameter_keyword_input()
        if not parameter_keyword:
            return
        rewrite_source_senders = messagebox.askyesno(
            'Remove Parameter',
            'Rewrite same-class senders that use this keyword selector?',
        )
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                'Remove Parameter',
                'Overwrite generated selector when it already exists?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Remove Parameter',
                (
                    'Apply remove-parameter on %s>>%s removing %s?'
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
                remove_parameter_result = self.gemstone_session_record.apply_method_remove_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    overwrite_new_method=overwrite_new_method,
                    rewrite_source_senders=rewrite_source_senders,
                )
            else:
                remove_parameter_result = self.gemstone_session_record.preview_method_remove_parameter(
                    class_name,
                    show_instance_side,
                    method_selector,
                    parameter_keyword,
                    rewrite_source_senders=rewrite_source_senders,
                )
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Remove Parameter %s' % ('Apply' if apply_change else 'Preview'),
            remove_parameter_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

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
        characters = self.text_editor.count('1.0', text_index, 'chars')
        if not characters:
            return 0
        return int(characters[0])

    def selected_text_offsets(self):
        try:
            selection_start_index = self.text_editor.index(tk.SEL_FIRST)
            selection_end_index = self.text_editor.index(tk.SEL_LAST)
        except tk.TclError:
            return None
        selection_start_offset = self.text_offset_for_index(
            selection_start_index
        )
        selection_end_offset = self.text_offset_for_index(selection_end_index)
        if selection_start_offset <= selection_end_offset:
            return (selection_start_offset, selection_end_offset)
        return (selection_end_offset, selection_start_offset)

    def selector_from_words(self, text):
        words = re.findall(r'[A-Za-z0-9]+', text)
        if not words:
            return 'extractedPart'
        capitalized_words = ''.join(
            word[0:1].upper() + word[1:]
            for word in words
            if word
        )
        if not capitalized_words:
            return 'extractedPart'
        selector = 'extracted%s' % capitalized_words
        normalized_selector = re.sub(r'[^A-Za-z0-9_]', '', selector)
        if not normalized_selector:
            return 'extractedPart'
        if normalized_selector[0].isdigit():
            normalized_selector = 'extracted%s' % normalized_selector
        return (
            normalized_selector[0].lower()
            + normalized_selector[1:]
        )

    def method_argument_names_from_ast_header(
        self,
        method_ast_payload,
        method_selector,
    ):
        selector_tokens = [
            '%s:' % selector_part
            for selector_part in method_selector.split(':')
            if selector_part
        ]
        if not selector_tokens:
            return []
        header_source = method_ast_payload.get('header_source', '')
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
                r'[A-Za-z_][A-Za-z0-9_]*',
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
        method_temporaries = method_ast_payload.get('temporaries', [])
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
                r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=',
                statement_entry.get('source', ''),
            )
            has_assignment = assignment_match is not None
            if has_assignment:
                target_name = assignment_match.group(1)
                if target_name not in assignment_targets:
                    assignment_targets.append(target_name)
        inferred_argument_names = []
        for statement_entry in selected_statement_entries:
            statement_source = statement_entry.get('source', '')
            identifier_matches = re.finditer(
                r'[A-Za-z_][A-Za-z0-9_]*',
                statement_source,
            )
            for identifier_match in identifier_matches:
                identifier_name = identifier_match.group(0)
                is_scoped = identifier_name in scoped_names
                is_assigned = identifier_name in assignment_targets
                is_already_inferred = (
                    identifier_name in inferred_argument_names
                )
                if is_scoped and not is_assigned and not is_already_inferred:
                    inferred_argument_names.append(identifier_name)
        return inferred_argument_names

    def suggested_extract_selector(
        self,
        selected_statement_entries,
        inferred_argument_names,
    ):
        if not selected_statement_entries:
            return 'extractedPart'
        first_statement = selected_statement_entries[0]
        statement_source = first_statement.get('source', '').strip()
        assignment_match = re.match(
            r'([A-Za-z_]\w*)\s*:=',
            statement_source,
        )
        if assignment_match:
            variable_name = assignment_match.group(1)
            base_selector = self.selector_from_words(
                'compute %s' % variable_name
            )
        else:
            sends = first_statement.get('sends', [])
            if sends:
                base_selector = self.selector_from_words(
                    sends[0].get('selector', '')
                )
            else:
                base_selector = self.selector_from_words(statement_source)
        if not inferred_argument_names:
            return base_selector
        keyword_tokens = ['%s:' % base_selector]
        for argument_name in inferred_argument_names[1:]:
            keyword_token = (
                re.sub(r'[^A-Za-z0-9_]', '', argument_name) or 'with'
            )
            keyword_tokens.append('%s:' % keyword_token)
        return ''.join(keyword_tokens)

    def selected_statement_entries_from_offsets(
        self,
        method_ast_payload,
        selection_offsets,
    ):
        if selection_offsets is None:
            raise DomainException(
                'Select one or more top-level statements before extracting.'
            )
        statements = method_ast_payload.get('statements', [])
        if not statements:
            raise DomainException('No extractable top-level statements found.')
        selection_start_offset, selection_end_offset = selection_offsets
        selected_statement_entries = [
            statement_entry
            for statement_entry in statements
            if (
                statement_entry['start_offset'] >= selection_start_offset
                and statement_entry['end_offset'] <= selection_end_offset
            )
        ]
        if not selected_statement_entries:
            raise DomainException(
                (
                    'Selection must fully cover one or more '
                    'top-level statements.'
                )
            )
        sorted_statement_entries = sorted(
            selected_statement_entries,
            key=lambda statement_entry: statement_entry['statement_index'],
        )
        statement_indexes = [
            statement_entry['statement_index']
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
                'Selection must cover contiguous top-level statements.'
            )
        return sorted_statement_entries

    def run_method_extract(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, method_selector = method_context
        try:
            selection_offsets = self.selected_text_offsets()
            if selection_offsets is None:
                raise DomainException(
                    'Select one or more top-level statements before extracting.'
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
                statement_entry['statement_index']
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
                'Extract Method',
                str(domain_exception),
            )
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Extract Method', str(gemstone_exception))
            return
        new_selector = self.new_selector_input(
            'Extract Method',
            'Name for extracted method:',
            initial_value=suggested_selector,
        )
        if not new_selector:
            return
        overwrite_new_method = False
        if apply_change:
            overwrite_new_method = messagebox.askyesno(
                'Extract Method',
                'Overwrite extracted method when it already exists?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Extract Method',
                (
                    'Apply extract-method on %s>>%s to %s using statements %s?'
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
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Extract Method %s' % ('Apply' if apply_change else 'Preview'),
            extract_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_extract(self):
        self.run_method_extract(apply_change=False)

    def apply_method_extract(self):
        self.run_method_extract(apply_change=True)

    def inline_selector_input(self):
        return self.new_selector_input(
            'Inline Method',
            'Inline selector:',
        )

    def run_method_inline(self, apply_change):
        method_context = self.method_context()
        if method_context is None:
            messagebox.showwarning(
                'No Method Context',
                'Select or open a method before running this operation.',
            )
            return
        class_name, show_instance_side, caller_selector = method_context
        inline_selector = self.inline_selector_input()
        if not inline_selector:
            return
        delete_inlined_method = False
        if apply_change:
            delete_inlined_method = messagebox.askyesno(
                'Inline Method',
                'Delete the inlined callee method after rewriting caller?',
            )
            should_apply = messagebox.askyesno(
                'Confirm Inline Method',
                (
                    'Apply inline-method in %s>>%s for selector %s?'
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
            messagebox.showerror('Operation Failed', str(domain_exception))
            return
        except GemstoneError as gemstone_exception:
            messagebox.showerror('Operation Failed', str(gemstone_exception))
            return
        JsonResultDialog(
            self.application,
            'Inline Method %s' % ('Apply' if apply_change else 'Preview'),
            inline_result,
        )
        if apply_change:
            self.application.event_queue.publish('MethodSelected', origin=self)

    def preview_method_inline(self):
        self.run_method_inline(apply_change=False)

    def apply_method_inline(self):
        self.run_method_inline(apply_change=True)

    def apply_syntax_highlighting(self, text):
        for match in re.finditer(r'\b(class|self|super|true|false|nil)\b', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_keyword", f"1.0 + {start} chars", f"1.0 + {end} chars")

        for match in re.finditer(r'".*?"', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_comment", f"1.0 + {start} chars", f"1.0 + {end} chars")

        for match in re.finditer(r'\'.*?\'', text):
            start, end = match.span()
            self.text_editor.tag_add("smalltalk_string", f"1.0 + {start} chars", f"1.0 + {end} chars")

    def on_key_release(self, event):
        text = self.text_editor.get("1.0", tk.END)
        self.apply_syntax_highlighting(text)

    def refresh(self, source, mark=None):
        text_editor_was_disabled = (
            self.text_editor.cget('state') == tk.DISABLED
        )
        if text_editor_was_disabled:
            self.text_editor.configure(state=tk.NORMAL)
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", source)
        if mark is not None and mark >= 0:
            position = self.text_editor.index(f"1.0 + {mark-1} chars")
            self.text_editor.tag_add("highlight", position, f"{position} + 1c")
        self.apply_syntax_highlighting(source)
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
        self.code_panel.grid(row=0, column=0, sticky='nsew')

        # Configure the grid weights for resizing
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.repopulate()

    def open_tab_menu(self, event):
        return None

    def save(self):
        (selected_class, show_instance_side, method_symbol) = self.tab_key
        self.browser_window.gemstone_session_record.update_method_source(selected_class, show_instance_side, method_symbol, self.code_panel.text_editor.get("1.0", "end-1c"))
        self.browser_window.event_queue.publish('MethodSelected', origin=self)
        self.repopulate()
        
    def repopulate(self):
        (selected_class, show_instance_side, method_symbol) = self.tab_key
        gemstone_method = self.browser_window.gemstone_session_record.get_method(*self.tab_key)
        if gemstone_method:
            method_source = gemstone_method.sourceString().to_py
            self.code_panel.refresh(method_source)
        else:
            self.method_editor.close_tab(self)
        
        
class BrowserWindow(ttk.PanedWindow):
    def __init__(self, parent, application):
        super().__init__(parent, orient=tk.VERTICAL)  # Make BrowserWindow a vertical paned window

        self.application = application

        # Create two frames to act as rows in the PanedWindow
        self.top_frame = ttk.Frame(self)
        self.bottom_frame = ttk.Frame(self)

        # Add frames to the PanedWindow
        self.add(self.top_frame)   # Add the top frame (row 0)
        self.add(self.bottom_frame)  # Add the bottom frame (row 1)

        # Add widgets to top_frame (similar to row 0 previously)
        self.packages_widget = PackageSelection(self.top_frame, self, self.event_queue, 0, 0)
        self.classes_widget = ClassSelection(self.top_frame, self, self.event_queue, 0, 1)
        self.categories_widget = CategorySelection(self.top_frame, self, self.event_queue, 0, 2)
        self.methods_widget = MethodSelection(self.top_frame, self, self.event_queue, 0, 3)

        # Add MethodEditor to bottom_frame (similar to row 1 previously)
        self.editor_area_widget = MethodEditor(self.bottom_frame, self, self.event_queue, 0, 0, colspan=4)

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
    def __init__(self, parent, an_object=None, values=None):
        super().__init__(parent)
        self.inspected_object = an_object
        self.page_size = 100
        self.current_page = 0
        self.total_items = 0
        self.pagination_mode = None
        self.dictionary_keys = []
        self.actual_values = []
        self.treeview_heading = 'Name'

        # Create a Treeview widget in the inspector
        self.treeview = ttk.Treeview(self, columns=('Name', 'Class', 'Value'), show='headings')
        self.treeview.heading('Name', text='Name')
        self.treeview.heading('Class', text='Class')
        self.treeview.heading('Value', text='Value')
        self.treeview.grid(row=0, column=0, sticky='nsew')

        self.footer = ttk.Frame(self)
        self.footer.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        self.status_label = ttk.Label(self.footer, text='')
        self.status_label.grid(row=0, column=0, sticky='w')
        self.previous_button = ttk.Button(self.footer, text='Previous', command=self.on_previous_page)
        self.previous_button.grid(row=0, column=1, padx=(8, 0))
        self.next_button = ttk.Button(self.footer, text='Next', command=self.on_next_page)
        self.next_button.grid(row=0, column=2, padx=(4, 0))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.footer.columnconfigure(0, weight=1)

        if values is not None:
            self.pagination_mode = None
            self.load_rows(list(values.items()), 'Name', len(values))
        else:
            self.inspect_object(an_object)

        # Bind double-click event to open nested inspectors
        self.treeview.bind('<Double-1>', self.on_item_double_click)

    def class_name_of(self, an_object):
        class_name = 'Unknown'
        if an_object is not None:
            try:
                class_name = an_object.gemstone_class().asString().to_py
            except GemstoneError:
                pass
        return class_name

    def value_label(self, an_object):
        label = '<unavailable>'
        if an_object is not None:
            try:
                label = an_object.asString().to_py
            except GemstoneError:
                label = f'<{self.class_name_of(an_object)}>'
        return label

    def class_name_has_dictionary_semantics(self, class_name):
        dictionary_markers = ('Dictionary', 'KeyValue')
        return any(marker in class_name for marker in dictionary_markers)

    def class_name_has_indexed_collection_semantics(self, class_name):
        indexed_markers = ('Array', 'OrderedCollection', 'SortedCollection', 'SequenceableCollection', 'List')
        return any(marker in class_name for marker in indexed_markers)

    def inspect_object(self, an_object):
        if an_object is None:
            self.pagination_mode = None
            self.load_rows([], 'Name', 0)
            return

        try:
            is_class = an_object.isBehavior().to_py
        except GemstoneError:
            is_class = False

        if is_class:
            self.pagination_mode = None
            inspected_values = self.inspect_class(an_object)
            self.load_rows(list(inspected_values.items()), 'Name', len(inspected_values))
            return

        class_name = self.class_name_of(an_object)
        dictionary_is_configured = False
        if self.class_name_has_dictionary_semantics(class_name):
            dictionary_is_configured = self.configure_dictionary_rows(an_object)
        if dictionary_is_configured:
            return

        indexed_collection_is_configured = False
        if self.class_name_has_indexed_collection_semantics(class_name):
            indexed_collection_is_configured = self.configure_indexed_collection_rows(an_object)
        if indexed_collection_is_configured:
            return

        self.pagination_mode = None
        inspected_values = self.inspect_instance(an_object)
        self.load_rows(list(inspected_values.items()), 'Name', len(inspected_values))

    def configure_dictionary_rows(self, an_object):
        try:
            self.dictionary_keys = list(an_object.keys())
        except GemstoneError:
            return False

        self.pagination_mode = 'dictionary'
        self.current_page = 0
        self.total_items = len(self.dictionary_keys)
        self.treeview_heading = 'Key'
        self.refresh_rows_for_current_page()
        return True

    def configure_indexed_collection_rows(self, an_object):
        try:
            total_items = an_object.size().to_py
        except GemstoneError:
            return False

        can_access_index_one = True
        if total_items > 0:
            try:
                an_object.at(1)
            except GemstoneError:
                can_access_index_one = False
        if not can_access_index_one:
            return False

        self.pagination_mode = 'indexed'
        self.current_page = 0
        self.total_items = total_items
        self.treeview_heading = 'Index'
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
                rows.append((f'[{one_based_index}]', value))
        return rows

    def refresh_rows_for_current_page(self):
        start_index, end_index = self.row_range_for_current_page()
        rows = []
        if self.pagination_mode == 'dictionary':
            rows = self.dictionary_rows_for_range(start_index, end_index)
        if self.pagination_mode == 'indexed':
            rows = self.indexed_rows_for_range(start_index, end_index)
        self.load_rows(rows, self.treeview_heading, self.total_items)

    def inspect_instance(self, an_object):
        # AI: Regular instances expose their instance variables via instVarNamed:.
        values = {}
        for i, instvar_name in enumerate(an_object.gemstone_class().allInstVarNames(), start=1):
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
        except GemstoneError:
            pass
        for i, instvar_name in enumerate(an_object.gemstone_class().allInstVarNames(), start=1):
            try:
                values[instvar_name.to_py] = an_object.instVarAt(i)
            except GemstoneError:
                pass
        return values

    def load_rows(self, rows, first_column_title, total_items):
        self.treeview_heading = first_column_title
        self.total_items = total_items
        self.treeview.heading('Name', text=self.treeview_heading)

        for existing_item in self.treeview.get_children():
            self.treeview.delete(existing_item)
        self.actual_values = []

        for row_name, row_value in rows:
            self.treeview.insert(
                '',
                'end',
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
        show_page_window = self.pagination_mode in ('dictionary', 'indexed') and self.total_items > self.page_size
        if show_page_window:
            self.status_label.configure(text=f'Items {start_index + 1}-{end_index} of {self.total_items}')
        if not show_page_window:
            if self.total_items == 1:
                self.status_label.configure(text='1 item')
            if self.total_items != 1:
                self.status_label.configure(text=f'{self.total_items} items')

        self.previous_button.configure(state=tk.DISABLED)
        self.next_button.configure(state=tk.DISABLED)
        if show_page_window:
            if self.current_page > 0:
                self.previous_button.configure(state=tk.NORMAL)
            if end_index < self.total_items:
                self.next_button.configure(state=tk.NORMAL)

    def on_previous_page(self):
        can_page_backwards = self.pagination_mode in ('dictionary', 'indexed') and self.current_page > 0
        if can_page_backwards:
            self.current_page -= 1
            self.refresh_rows_for_current_page()

    def on_next_page(self):
        start_index, end_index = self.row_range_for_current_page()
        can_page_forwards = self.pagination_mode in ('dictionary', 'indexed') and end_index < self.total_items
        if can_page_forwards:
            self.current_page += 1
            self.refresh_rows_for_current_page()

    def on_item_double_click(self, event):
        selected_item = self.treeview.focus()
        if selected_item:
            index = self.treeview.index(selected_item)
            value = None
            if index < len(self.actual_values):
                value = self.actual_values[index]
            if value is None:
                return

            for tab_id in self.master.tabs():
                inspected_widget = self.master.nametowidget(tab_id)
                tab_matches_object = isinstance(inspected_widget, ObjectInspector) and inspected_widget.inspected_object is value
                if tab_matches_object:
                    self.master.select(tab_id)
                    return

            tab_label = self.class_name_of(value)
            try:
                new_tab = ObjectInspector(self.master, an_object=value)
            except GemstoneError as e:
                messagebox.showerror('Inspector', f'Cannot inspect this object:\n{e}')
                return
            self.master.add(new_tab, text=tab_label)
            self.master.select(new_tab)                



class Explorer(ttk.Notebook):
    def __init__(self, parent, an_object=None, values=None):
        super().__init__(parent)

        # Create a new ObjectInspector for the 'context' tab
        context_frame = ObjectInspector(self, an_object=an_object, values=values)
        self.add(context_frame, text='Context')


class InspectorTab(ttk.Frame):
    def __init__(self, parent, application, an_object=None):
        super().__init__(parent)
        self.application = application

        self.explorer = Explorer(self, an_object=an_object)
        self.explorer.grid(row=0, column=0, sticky='nsew')

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=1, column=0, sticky='e', padx=10, pady=(0, 10))
        self.close_button = ttk.Button(
            self.button_frame,
            text='Close Inspector',
            command=self.application.close_inspector_tab,
        )
        self.close_button.grid(row=0, column=0)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)


class DebuggerWindow(ttk.PanedWindow):
    def __init__(self, parent, application, gemstone_session_record, event_queue, exception):
        super().__init__(parent, orient=tk.VERTICAL)  # Make DebuggerWindow a vertical paned window

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
        self.debugger_controls = DebuggerControls(self.call_stack_frame, self, self.event_queue)
        self.debugger_controls.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Add a Treeview widget to the top frame, below DebuggerControls, to represent the three-column list
        self.listbox = ttk.Treeview(self.call_stack_frame, columns=('Level', 'Column1', 'Column2'), show='headings')
        self.listbox.heading('Level', text='Level')
        self.listbox.heading('Column1', text='Class Name')
        self.listbox.heading('Column2', text='Method Name')
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
            self.listbox.insert('', 'end', iid=iid, values=(frame.level, frame.class_name, frame.method_name))
        
        # Select the first entry in the listbox by iid
        if self.stack_frames:
            first_iid = str(1)
            self.listbox.selection_set(first_iid)
            self.listbox.focus(first_iid)

            self.code_panel.refresh(self.stack_frames[1].method_source, mark=self.stack_frames[1].step_point_offset)
            self.refresh_explorer(self.stack_frames[1])

    def refresh_explorer(self, frame):
        # Clear existing widgets in the explorer_frame
        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        # Create an Explorer widget in the explorer_frame
        explorer = Explorer(self.explorer_frame, frame, values=dict([('self', frame.self)] + list(frame.vars.items())))
        explorer.grid(row=0, column=0, sticky="nsew")
    
    def on_listbox_select(self, event):
        frame = self.get_selected_stack_frame()
        if frame:
            self.code_panel.refresh(frame.method_source, mark=frame.step_point_offset)
            self.refresh_explorer(frame)

    def open_method_from_selected_frame(self, event):
        self.open_selected_frame_method()
            
    def get_selected_stack_frame(self):
        selected_item = self.listbox.focus()
        if selected_item:
            return self.stack_frames[int(selected_item)]
        return None

    def frame_method_context(self, frame):
        if frame is None:
            return None
        class_name = frame.class_name
        show_instance_side = True
        class_side_suffix = ' class'
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
            messagebox.showerror('Browse Frame Method', str(error))

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

        # Create and add a Text widget to display the result
        self.result_text = tk.Text(self)
        self.result_text.insert('1.0', result.asString().to_py)
        self.result_text.pack(fill='both', expand=True)
        self.close_button = ttk.Button(
            self,
            text='Close Debugger',
            command=self.dismiss,
        )
        self.close_button.pack(anchor='e', padx=5, pady=5)
        
            
class DebuggerControls(ttk.Frame):
    def __init__(self, parent, debugger, event_queue):
        super().__init__(parent)
        self.debugger = debugger
        self.event_queue = event_queue

        # Create buttons for Debugger Controls
        self.continue_button = ttk.Button(self, text="Continue", command=self.handle_continue)
        self.continue_button.grid(row=0, column=0, padx=5, pady=5)

        self.over_button = ttk.Button(self, text="Over", command=self.handle_over)
        self.over_button.grid(row=0, column=1, padx=5, pady=5)

        self.into_button = ttk.Button(self, text="Into", command=self.handle_into)
        self.into_button.grid(row=0, column=2, padx=5, pady=5)

        self.through_button = ttk.Button(self, text="Through", command=self.handle_through)
        self.through_button.grid(row=0, column=3, padx=5, pady=5)

        self.stop_button = ttk.Button(self, text="Stop", command=self.handle_stop)
        self.stop_button.grid(row=0, column=4, padx=5, pady=5)

        self.browse_button = ttk.Button(
            self,
            text='Browse Method',
            command=self.handle_browse,
        )
        self.browse_button.grid(row=0, column=5, padx=5, pady=5)

    def handle_continue(self):
        self.debugger.continue_running()

    def handle_over(self):
        self.debugger.step_over()

    def handle_into(self):
        self.debugger.step_into()
        
    def handle_through(self):
        self.debugger.step_through()

    def handle_stop(self):
        self.debugger.stop()

    def handle_browse(self):
        self.debugger.open_selected_frame_method()


        
class LoginFrame(ttk.Frame):
    def __init__(self, parent, default_stone_name='gs64stone'):
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
            sticky='n',
            padx=20,
            pady=20,
        )
        self.form_frame.columnconfigure(0, weight=0)
        self.form_frame.columnconfigure(1, weight=1)

        ttk.Label(
            self.form_frame,
            text='Connect to GemStone',
        ).grid(
            column=0,
            row=0,
            columnspan=2,
            sticky='w',
            pady=(0, 12),
        )

        # Username label and entry
        ttk.Label(self.form_frame, text='Username:').grid(
            column=0,
            row=1,
            sticky='e',
            padx=(0, 8),
            pady=2,
        )
        self.username_entry = ttk.Entry(self.form_frame)
        self.username_entry.insert(0, 'DataCurator')
        self.username_entry.grid(column=1, row=1, sticky='ew', pady=2)

        # Password label and entry
        ttk.Label(self.form_frame, text='Password:').grid(
            column=0,
            row=2,
            sticky='e',
            padx=(0, 8),
            pady=2,
        )
        self.password_entry = ttk.Entry(self.form_frame, show='*')
        self.password_entry.insert(0, 'swordfish')
        self.password_entry.grid(column=1, row=2, sticky='ew', pady=2)

        ttk.Label(self.form_frame, text='Stone name:').grid(
            column=0,
            row=3,
            sticky='e',
            padx=(0, 8),
            pady=2,
        )
        self.stone_name_entry = ttk.Entry(self.form_frame)
        self.stone_name_entry.insert(0, default_stone_name)
        self.stone_name_entry.grid(column=1, row=3, sticky='ew', pady=2)

        # Remote checkbox
        self.remote_var = tk.BooleanVar()
        self.remote_checkbox = ttk.Checkbutton(
            self.form_frame,
            text='Login RPC?',
            variable=self.remote_var,
            command=self.toggle_remote_widgets,
        )
        self.remote_checkbox.grid(
            column=0,
            row=4,
            columnspan=2,
            sticky='w',
            pady=(8, 2),
        )

        # Remote widgets (initially hidden)
        self.netldi_name_label = ttk.Label(self.form_frame, text='Netldi name:')
        self.netldi_name_entry = ttk.Entry(self.form_frame)
        self.netldi_name_entry.insert(0, 'gs64-ldi')

        self.rpc_hostname_label = ttk.Label(self.form_frame, text='RPC host name:')
        self.rpc_hostname_entry = ttk.Entry(self.form_frame)
        self.rpc_hostname_entry.insert(0, 'localhost')

        # Login button
        ttk.Button(self.form_frame, text='Login', command=self.attempt_login).grid(
            column=1,
            row=8,
            sticky='e',
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
                sticky='e',
                padx=(0, 8),
                pady=2,
            )
            self.netldi_name_entry.grid(column=1, row=5, sticky='ew', pady=2)
            self.rpc_hostname_label.grid(
                column=0,
                row=6,
                sticky='e',
                padx=(0, 8),
                pady=2,
            )
            self.rpc_hostname_entry.grid(column=1, row=6, sticky='ew', pady=2)
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
                gemstone_session_record = GemstoneSessionRecord.log_in_rpc(username, password, rpc_hostname, stone_name, netldi_name)
            else:
                gemstone_session_record = GemstoneSessionRecord.log_in_linked(username, password, stone_name)
            self.parent.event_queue.publish('LoggedInSuccessfully', gemstone_session_record)
        except DomainException as ex:
            self.error_label = ttk.Label(
                self.form_frame,
                text=str(ex),
                foreground='red',
            )
            self.error_label.grid(
                column=0,
                row=7,
                columnspan=2,
                sticky='w',
                pady=(8, 0),
            )


def new_application_argument_parser(default_mode='ide'):
    argument_parser = argparse.ArgumentParser(
        description='Run Swordfish IDE and MCP server.'
    )
    default_headless_mcp = default_mode == 'mcp-headless'
    argument_parser.add_argument(
        'stone_name',
        nargs='?',
        default='gs64stone',
        help='GemStone stone name to prefill in login form.',
    )
    argument_parser.add_argument(
        '--headless-mcp',
        action='store_true',
        default=default_headless_mcp,
        help='Run MCP only (headless, no GUI).',
    )
    argument_parser.add_argument(
        '--mode',
        default=None,
        choices=['ide', 'mcp-headless'],
        help=argparse.SUPPRESS,
    )
    argument_parser.add_argument(
        '--transport',
        default='stdio',
        choices=['stdio', 'streamable-http'],
        help='MCP transport type for --headless-mcp mode.',
    )
    argument_parser.add_argument(
        '--mcp-host',
        default='127.0.0.1',
        help='Host interface for embedded MCP and streamable-http mode.',
    )
    argument_parser.add_argument(
        '--mcp-port',
        default=8000,
        type=int,
        help='TCP port for embedded MCP and streamable-http mode.',
    )
    argument_parser.add_argument(
        '--mcp-http-path',
        default='/mcp',
        help='HTTP path for embedded MCP and streamable-http mode.',
    )
    argument_parser.add_argument(
        '--allow-eval',
        action='store_true',
        help='Enable gs_eval and gs_debug_eval (disabled by default).',
    )
    argument_parser.add_argument(
        '--allow-compile',
        action='store_true',
        help='Enable gs_compile_method tool (disabled by default).',
    )
    argument_parser.add_argument(
        '--allow-commit',
        action='store_true',
        help='Enable gs_commit tool (disabled by default).',
    )
    argument_parser.add_argument(
        '--allow-mcp-commit-when-gui',
        action='store_true',
        help=(
            'Allow gs_commit even when MCP is attached to an IDE-owned '
            'session (disabled by default).'
        ),
    )
    argument_parser.add_argument(
        '--allow-tracing',
        action='store_true',
        help='Enable gs_tracer_* and evidence tools (disabled by default).',
    )
    argument_parser.add_argument(
        '--require-gemstone-ast',
        action='store_true',
        help=(
            'Require real GemStone AST backend for refactoring tools. '
            'When enabled, heuristic refactorings are blocked.'
        ),
    )
    return argument_parser


def run_mcp_server(arguments, integrated_session_state=None):
    mcp_server = create_server(
        allow_eval=arguments.allow_eval,
        allow_compile=arguments.allow_compile,
        allow_commit=arguments.allow_commit,
        allow_tracing=arguments.allow_tracing,
        allow_commit_when_gui=arguments.allow_mcp_commit_when_gui,
        integrated_session_state=integrated_session_state,
        require_gemstone_ast=arguments.require_gemstone_ast,
        mcp_host=arguments.mcp_host,
        mcp_port=arguments.mcp_port,
        mcp_streamable_http_path=arguments.mcp_http_path,
    )
    mcp_server.run(transport=arguments.transport)


def validate_application_arguments(argument_parser, arguments):
    if arguments.mcp_port <= 0:
        argument_parser.error('--mcp-port must be greater than zero.')
    if not arguments.mcp_http_path.startswith('/'):
        argument_parser.error('--mcp-http-path must start with /.')


def runtime_mcp_config_from_arguments(arguments):
    return McpRuntimeConfig(
        allow_eval=arguments.allow_eval,
        allow_compile=arguments.allow_compile,
        allow_commit=arguments.allow_commit,
        allow_tracing=arguments.allow_tracing,
        allow_mcp_commit_when_gui=arguments.allow_mcp_commit_when_gui,
        require_gemstone_ast=arguments.require_gemstone_ast,
        mcp_host=arguments.mcp_host,
        mcp_port=arguments.mcp_port,
        mcp_http_path=arguments.mcp_http_path,
    )


def run_application(default_mode='ide'):
    argument_parser = new_application_argument_parser(default_mode=default_mode)
    arguments = argument_parser.parse_args()
    validate_application_arguments(argument_parser, arguments)
    run_headless_mcp = arguments.headless_mcp
    if arguments.mode == 'mcp-headless':
        run_headless_mcp = True
    if arguments.mode == 'ide':
        run_headless_mcp = False
    if run_headless_mcp:
        run_mcp_server(arguments)
        return
    app = Swordfish(
        default_stone_name=arguments.stone_name,
        start_embedded_mcp=True,
        mcp_runtime_config=runtime_mcp_config_from_arguments(arguments),
    )
    app.mainloop()

if __name__ == "__main__":
    run_application()
