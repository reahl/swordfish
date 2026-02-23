import os
import re

from reahl.ptongue import GemstoneApiError
from reahl.ptongue import GemstoneError
from reahl.swordfish.mcp.ast_assets import ast_support_source
from reahl.swordfish.mcp.ast_assets import ast_support_source_hash
from reahl.swordfish.mcp.ast_assets import AST_SUPPORT_VERSION

from reahl.swordfish.gemstone.session import DomainException
from reahl.swordfish.gemstone.session import render_result


class GemstoneBrowserSession:
    def __init__(
        self,
        gemstone_session,
        require_gemstone_ast=None,
    ):
        self.gemstone_session = gemstone_session
        if require_gemstone_ast is None:
            require_gemstone_ast = self.boolean_flag_from_environment(
                'SWORDFISH_REQUIRE_GEMSTONE_AST'
            )
        self.require_gemstone_ast = require_gemstone_ast
        self.real_gemstone_ast_backend_available = None

    def boolean_flag_from_environment(self, environment_name):
        environment_value = os.environ.get(environment_name, '')
        normalized_environment_value = environment_value.strip().lower()
        return normalized_environment_value in {
            '1',
            'true',
            'yes',
            'on',
        }

    def can_attempt_ast_support_auto_install(self):
        return (
            self.gemstone_session is not None
            and hasattr(self.gemstone_session, 'resolve_symbol')
            and hasattr(self.gemstone_session, 'execute')
        )

    def ast_support_manifest_matches_expected(self):
        if not self.can_attempt_ast_support_auto_install():
            return False
        manifest_exists = self.gemstone_session.execute(
            'UserGlobals includesKey: #SwordfishMcpAstManifest'
        ).to_py
        if not manifest_exists:
            return False
        installed_source_hash = self.gemstone_session.execute(
            (
                '(UserGlobals at: #SwordfishMcpAstManifest) '
                "at: #sourceHash ifAbsent: ['']"
            )
        ).to_py
        installed_version = self.gemstone_session.execute(
            (
                '(UserGlobals at: #SwordfishMcpAstManifest) '
                "at: #version ifAbsent: ['']"
            )
        ).to_py
        return (
            installed_source_hash == ast_support_source_hash()
            and installed_version == AST_SUPPORT_VERSION
        )

    def ast_support_manifest_install_script(self):
        expected_source_hash_literal = self.smalltalk_string_literal(
            ast_support_source_hash()
        )
        expected_version_literal = self.smalltalk_string_literal(
            AST_SUPPORT_VERSION
        )
        installed_by_literal = self.smalltalk_string_literal('swordfish-ide')
        return (
            '| manifest |\n'
            'manifest := Dictionary new.\n'
            'manifest at: #version put: %s.\n'
            'manifest at: #sourceHash put: %s.\n'
            'manifest at: #installedBy put: %s.\n'
            'manifest at: #installedAt put: DateAndTime now printString.\n'
            'UserGlobals at: #SwordfishMcpAstManifest put: manifest.\n'
            'true'
        ) % (
            expected_version_literal,
            expected_source_hash_literal,
            installed_by_literal,
        )

    def install_or_refresh_ast_support(self):
        self.run_code(ast_support_source())
        self.run_code(self.ast_support_manifest_install_script())
        self.real_gemstone_ast_backend_available = None

    def has_real_gemstone_ast_backend(self):
        if self.real_gemstone_ast_backend_available is not None:
            return self.real_gemstone_ast_backend_available
        if not self.can_attempt_ast_support_auto_install():
            self.real_gemstone_ast_backend_available = False
            return False
        try:
            if self.require_gemstone_ast:
                manifest_matches = (
                    self.ast_support_manifest_matches_expected()
                )
                if not manifest_matches:
                    self.real_gemstone_ast_backend_available = False
                    return False
                ast_support_exists = self.gemstone_session.execute(
                    'UserGlobals includesKey: #SwordfishMcpAstSupport'
                ).to_py
                if not ast_support_exists:
                    self.real_gemstone_ast_backend_available = False
                    return False
            probe_compiled_method = self.get_compiled_method(
                'Object',
                'yourself',
                True,
            )
            probe_compiled_method.numArgs()
            probe_compiled_method.argsAndTemps()
            self.real_gemstone_ast_backend_available = True
        except (GemstoneError, GemstoneApiError, DomainException):
            self.real_gemstone_ast_backend_available = False
        return self.real_gemstone_ast_backend_available

    def ast_backend_status(self):
        return {
            'active_backend': (
                'gemstone_compiled_method_metadata'
                if self.has_real_gemstone_ast_backend()
                else 'source_heuristic'
            ),
            'require_gemstone_ast': self.require_gemstone_ast,
            'real_gemstone_ast_available': (
                self.has_real_gemstone_ast_backend()
            ),
        }

    def ensure_refactoring_uses_real_ast(self, refactoring_name):
        if not self.require_gemstone_ast:
            return
        has_real_backend = self.has_real_gemstone_ast_backend()
        if not has_real_backend and self.can_attempt_ast_support_auto_install():
            try:
                self.install_or_refresh_ast_support()
            except (GemstoneError, GemstoneApiError, DomainException):
                pass
            has_real_backend = self.has_real_gemstone_ast_backend()
        if not has_real_backend:
            raise DomainException(
                (
                    '%s requires real GemStone AST, but only '
                    'source-heuristic analysis is available. Disable strict '
                    'mode (SWORDFISH_REQUIRE_GEMSTONE_AST=false or '
                    'start without --require-gemstone-ast) or install AST '
                    'support in the image via gs_ast_install. Swordfish '
                    'attempted automatic installation when possible.'
                )
                % refactoring_name
            )

    @property
    def class_organizer(self):
        return self.gemstone_session.ClassOrganizer.new()

    @property
    def package_library(self):
        return self.gemstone_session.execute('GsPackageLibrary packageLibrary')

    def list_packages(self):
        package_names_from_categories = []
        package_names_from_library = []
        try:
            package_names_from_categories = [
                gemstone_package.to_py
                for gemstone_package in self.class_organizer.categories().keys()
            ]
        except GemstoneError:
            package_names_from_categories = []
        except GemstoneApiError:
            package_names_from_categories = []

        try:
            package_names_from_library = [
                gemstone_package.name().to_py
                for gemstone_package in self.package_library
            ]
        except GemstoneError:
            package_names_from_library = []
        except GemstoneApiError:
            package_names_from_library = []

        all_package_names = (
            set(package_names_from_categories) | set(package_names_from_library)
        )
        return sorted(all_package_names)

    def package_exists(self, package_name):
        return package_name in self.list_packages()

    def create_package(self, package_name):
        package_name_literal = self.smalltalk_string_literal(package_name)
        return self.run_code(
            'GsPackageLibrary createPackageNamed: %s' % package_name_literal
        )

    def install_package(self, package_name):
        package_name_literal = self.smalltalk_string_literal(package_name)
        return self.run_code(
            'GsPackageLibrary installPackageNamed: %s' % package_name_literal
        )

    def create_and_install_package(self, package_name):
        self.create_package(package_name)
        return self.install_package(package_name)

    def list_classes(self, package_name):
        if not package_name:
            return []
        try:
            gemstone_classes = self.class_organizer.categories().at(package_name)
        except GemstoneError:
            return []
        except GemstoneApiError:
            return []
        except KeyError:
            return []
        return [gemstone_class.name().to_py for gemstone_class in gemstone_classes]

    def list_method_categories(self, class_name, show_instance_side):
        if not class_name:
            return []
        class_to_query = self.class_to_query(class_name, show_instance_side)
        categories = [
            gemstone_category.to_py
            for gemstone_category in class_to_query.categoryNames().asSortedCollection()
        ]
        return ['all'] + categories

    def list_methods(
        self,
        class_name,
        method_category,
        show_instance_side,
    ):
        if not class_name or not method_category:
            return []
        class_to_query = self.class_to_query(class_name, show_instance_side)
        if method_category == 'all':
            selectors = class_to_query.selectors().asSortedCollection()
        else:
            selectors = class_to_query.selectorsIn(method_category).asSortedCollection()
        return [gemstone_selector.to_py for gemstone_selector in selectors]

    def get_compiled_method(self, class_name, method_selector, show_instance_side):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        return class_to_query.compiledMethodAt(method_selector)

    def get_method_source(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        compiled_method = self.get_compiled_method(
            class_name,
            method_selector,
            show_instance_side,
        )
        return compiled_method.sourceString().to_py

    def get_method_category(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        return class_to_query.categoryOfSelector(method_selector).to_py

    def method_sends(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        return self.source_method_sends(source)

    def method_structure_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        return self.source_method_structure_summary(source)

    def method_control_flow_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        return self.source_method_control_flow_summary(source)

    def query_methods_by_ast_pattern(
        self,
        ast_pattern,
        package_name=None,
        class_name=None,
        show_instance_side=True,
        method_category='all',
        max_results=None,
        sort_by='scan_order',
        sort_descending=False,
    ):
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        sort_by = self.validated_ast_query_sort_by(sort_by)
        sort_descending = self.validated_boolean_flag(
            sort_descending,
            'sort_descending',
        )
        class_names = self.query_scope_class_names(
            package_name,
            class_name,
        )
        matches = []
        scanned_method_count = 0
        for scoped_class_name in class_names:
            selector_names = self.selector_names_for_scope(
                scoped_class_name,
                show_instance_side,
                method_category,
            )
            for selector_name in selector_names:
                scanned_method_count = scanned_method_count + 1
                method_source = self.get_method_source(
                    scoped_class_name,
                    selector_name,
                    show_instance_side,
                )
                pattern_evaluation = self.pattern_evaluation_for_method(
                    method_source,
                    selector_name,
                    ast_pattern,
                    sort_by,
                )
                if pattern_evaluation['matches']:
                    structure_summary = pattern_evaluation[
                        'structure_summary'
                    ]
                    control_flow_summary = pattern_evaluation[
                        'control_flow_summary'
                    ]
                    matches.append(
                        {
                            'class_name': scoped_class_name,
                            'show_instance_side': show_instance_side,
                            'method_selector': selector_name,
                            'method_category': self.get_method_category(
                                scoped_class_name,
                                selector_name,
                                show_instance_side,
                            ),
                            'send_count': structure_summary['send_count'],
                            'keyword_send_count': structure_summary[
                                'keyword_send_count'
                            ],
                            'unary_send_count': structure_summary[
                                'unary_send_count'
                            ],
                            'binary_send_count': structure_summary[
                                'binary_send_count'
                            ],
                            'block_count': structure_summary[
                                'block_open_count'
                            ],
                            'return_count': structure_summary[
                                'return_count'
                            ],
                            'cascade_count': structure_summary[
                                'cascade_count'
                            ],
                            'assignment_count': structure_summary[
                                'assignment_count'
                            ],
                            'statement_terminator_count': structure_summary[
                                'statement_terminator_count'
                            ],
                            'explicit_self_send_count': structure_summary[
                                'explicit_self_send_count'
                            ],
                            'explicit_super_send_count': structure_summary[
                                'explicit_super_send_count'
                            ],
                            'body_line_count': structure_summary[
                                'body_line_count'
                            ],
                            'statement_count': pattern_evaluation[
                                'statement_count'
                            ],
                            'temporary_count': pattern_evaluation[
                                'temporary_count'
                            ],
                            'branch_selector_count': (
                                control_flow_summary[
                                    'branch_selector_count'
                                ]
                                if control_flow_summary is not None
                                else 0
                            ),
                            'loop_selector_count': (
                                control_flow_summary['loop_selector_count']
                                if control_flow_summary is not None
                                else 0
                            ),
                            'max_block_nesting_depth': (
                                control_flow_summary[
                                    'max_block_nesting_depth'
                                ]
                                if control_flow_summary is not None
                                else 0
                            ),
                        }
                    )
                    if (
                        sort_by == 'scan_order'
                        and
                        max_results is not None
                        and len(matches) >= max_results
                    ):
                        return {
                            'matches': matches,
                            'match_count': len(matches),
                            'scanned_method_count': scanned_method_count,
                            'truncated': True,
                            'sort_by': sort_by,
                            'sort_descending': sort_descending,
                        }
        if sort_by != 'scan_order':
            matches = sorted(
                matches,
                key=lambda entry: self.ast_query_sort_key(entry, sort_by),
                reverse=sort_descending,
            )
        truncated = (
            max_results is not None
            and len(matches) > max_results
        )
        if max_results is not None:
            matches = matches[:max_results]
        return {
            'matches': matches,
            'match_count': len(matches),
            'scanned_method_count': scanned_method_count,
            'truncated': truncated,
            'sort_by': sort_by,
            'sort_descending': sort_descending,
        }

    def supported_ast_query_sort_fields(self):
        return [
            'scan_order',
            'class_name',
            'method_selector',
            'send_count',
            'keyword_send_count',
            'unary_send_count',
            'binary_send_count',
            'block_count',
            'return_count',
            'cascade_count',
            'assignment_count',
            'statement_terminator_count',
            'explicit_self_send_count',
            'explicit_super_send_count',
            'body_line_count',
            'statement_count',
            'temporary_count',
            'branch_selector_count',
            'loop_selector_count',
            'max_block_nesting_depth',
        ]

    def validated_ast_query_sort_by(self, sort_by):
        if not isinstance(sort_by, str) or not sort_by:
            raise DomainException('sort_by must be a non-empty string.')
        supported_fields = self.supported_ast_query_sort_fields()
        if sort_by not in supported_fields:
            raise DomainException(
                (
                    'sort_by must be one of: %s.'
                )
                % ', '.join(supported_fields)
            )
        return sort_by

    def ast_query_sort_key(self, match_entry, sort_by):
        if sort_by == 'scan_order':
            return 0
        value = match_entry.get(sort_by)
        if value is None:
            return -1
        return value

    def compiled_method_argument_and_temporary_names(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        compiled_method = self.get_compiled_method(
            class_name,
            method_selector,
            show_instance_side,
        )
        all_names = []
        args_and_temps = compiled_method.argsAndTemps()
        num_args = compiled_method.numArgs().to_py
        size = args_and_temps.size().to_py
        for index in range(1, size + 1):
            all_names.append(args_and_temps.at(index).to_py)
        return {
            'argument_names': all_names[:num_args],
            'temporary_names': all_names[num_args:],
        }

    def method_header_for_selector_and_argument_names(
        self,
        method_selector,
        argument_names,
    ):
        selector_tokens = self.selector_keyword_tokens(method_selector)
        if selector_tokens:
            expected_argument_count = len(selector_tokens)
            actual_argument_count = len(argument_names)
            if actual_argument_count != expected_argument_count:
                raise DomainException(
                    (
                        'Expected %s arguments for %s, found %s.'
                    )
                    % (
                        expected_argument_count,
                        method_selector,
                        actual_argument_count,
                    )
                )
            return self.keyword_header_for_selector_tokens_and_arguments(
                selector_tokens,
                argument_names,
            )
        selector_uses_binary_syntax = (
            bool(method_selector)
            and all(
                self.is_binary_selector_character(character)
                for character in method_selector
            )
        )
        if selector_uses_binary_syntax:
            if len(argument_names) != 1:
                raise DomainException(
                    'Binary selector %s requires one argument.'
                    % method_selector
                )
            return '%s %s' % (method_selector, argument_names[0])
        if argument_names:
            raise DomainException(
                (
                    'Unary selector %s cannot declare arguments (%s).'
                )
                % (
                    method_selector,
                    ', '.join(argument_names),
                )
            )
        return method_selector

    def method_argument_names_for_method(
        self,
        class_name,
        show_instance_side,
        method_selector,
    ):
        names = self.compiled_method_argument_and_temporary_names(
            class_name,
            method_selector,
            show_instance_side,
        )
        return names['argument_names']

    def method_ast(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        source_ast = self.source_method_ast(source, method_selector)
        names = self.compiled_method_argument_and_temporary_names(
            class_name,
            method_selector,
            show_instance_side,
        )
        source_ast['argument_names'] = names['argument_names']
        source_ast['temporaries'] = names['temporary_names']
        source_ast['header_source'] = (
            self.method_header_for_selector_and_argument_names(
                method_selector,
                names['argument_names'],
            )
        )
        source_ast['analysis_backend'] = (
            'gemstone_compiled_method_metadata'
        )
        source_ast['analysis_limitations'] = (
            [
                (
                    'Arguments and temporaries are derived from GemStone '
                    'compiled method metadata.'
                ),
            ]
            + source_ast['analysis_limitations']
        )
        return source_ast

    def source_method_sends(self, source):
        code_character_map = self.source_code_character_map(source)
        line_column_map = self.source_line_column_map(source)
        body_start_offset = self.body_start_offset_for_method_source(source)
        if body_start_offset >= len(source):
            body_start_offset = 0
        _, statements_start_offset = self.source_temporaries_after_body_start(
            source,
            code_character_map,
            body_start_offset,
        )
        keyword_entries = self.keyword_send_entries_in_source(
            source,
            code_character_map,
            line_column_map,
            statements_start_offset,
        )
        explicit_receiver_entries = self.explicit_receiver_send_entries_in_source(
            source,
            code_character_map,
            line_column_map,
            statements_start_offset,
        )
        expression_receiver_entries = self.expression_receiver_send_entries_in_source(
            source,
            code_character_map,
            line_column_map,
            statements_start_offset,
        )
        cascade_entries = self.cascade_send_entries_in_source(
            source,
            code_character_map,
            line_column_map,
            statements_start_offset,
        )
        send_entries = []
        seen_send_keys = set()
        for send_entry in (
            keyword_entries
            + explicit_receiver_entries
            + expression_receiver_entries
            + cascade_entries
        ):
            send_key = (
                send_entry['start_offset'],
                send_entry['end_offset'],
                send_entry['selector'],
                send_entry['send_type'],
            )
            has_seen_send = send_key in seen_send_keys
            if not has_seen_send:
                send_entries.append(send_entry)
                seen_send_keys.add(send_key)
        return {
            'total_count': len(send_entries),
            'sends': sorted(
                send_entries,
                key=lambda send_entry: (
                    send_entry['start_offset'],
                    send_entry['end_offset'],
                    send_entry['selector'],
                ),
            ),
            'analysis_limitations': [
                (
                    'Send detection is source-based and heuristic; '
                    'runtime dispatch targets still depend on dynamic receiver classes.'
                ),
                (
                    'Unary and binary sends are inferred for explicit receivers, '
                    'common expression receivers, and cascades; uncommon layouts '
                    'may still be missed.'
                ),
            ],
        }

    def source_method_structure_summary(self, source):
        code_character_map = self.source_code_character_map(source)
        body_start_offset = self.body_start_offset_for_method_source(source)
        if body_start_offset >= len(source):
            body_start_offset = 0
        body_source = source[body_start_offset:]
        method_sends = self.source_method_sends(source)
        block_open_count = 0
        block_close_count = 0
        return_count = 0
        cascade_count = 0
        assignment_count = 0
        statement_terminator_count = 0
        code_character_count = 0
        non_code_character_count = 0
        index = body_start_offset
        while index < len(source):
            is_code_character = code_character_map[index]
            character = source[index]
            if is_code_character:
                code_character_count = code_character_count + 1
                if character == '[':
                    block_open_count = block_open_count + 1
                if character == ']':
                    block_close_count = block_close_count + 1
                if character == '^':
                    return_count = return_count + 1
                if character == ';':
                    cascade_count = cascade_count + 1
                if character == '.':
                    statement_terminator_count = (
                        statement_terminator_count + 1
                    )
                has_next_character = index + 1 < len(source)
                has_assignment = (
                    character == ':'
                    and has_next_character
                    and source[index + 1] == '='
                    and code_character_map[index + 1]
                )
                if has_assignment:
                    assignment_count = assignment_count + 1
            else:
                non_code_character_count = non_code_character_count + 1
            index = index + 1
        keyword_send_count = 0
        unary_send_count = 0
        binary_send_count = 0
        explicit_self_send_count = 0
        explicit_super_send_count = 0
        for send_entry in method_sends['sends']:
            if send_entry['send_type'] == 'keyword':
                keyword_send_count = keyword_send_count + 1
            if send_entry['send_type'] == 'unary':
                unary_send_count = unary_send_count + 1
            if send_entry['send_type'] == 'binary':
                binary_send_count = binary_send_count + 1
            if send_entry['receiver_hint'] == 'self':
                explicit_self_send_count = explicit_self_send_count + 1
            if send_entry['receiver_hint'] == 'super':
                explicit_super_send_count = explicit_super_send_count + 1
        return {
            'body_start_offset': body_start_offset,
            'body_line_count': (
                body_source.count('\n') + 1
                if body_source
                else 0
            ),
            'source_character_count': len(source),
            'body_character_count': len(body_source),
            'code_character_count': code_character_count,
            'non_code_character_count': non_code_character_count,
            'block_open_count': block_open_count,
            'block_close_count': block_close_count,
            'return_count': return_count,
            'cascade_count': cascade_count,
            'assignment_count': assignment_count,
            'statement_terminator_count': statement_terminator_count,
            'send_count': method_sends['total_count'],
            'keyword_send_count': keyword_send_count,
            'unary_send_count': unary_send_count,
            'binary_send_count': binary_send_count,
            'explicit_self_send_count': explicit_self_send_count,
            'explicit_super_send_count': explicit_super_send_count,
            'analysis_limitations': method_sends['analysis_limitations'],
        }

    def source_method_control_flow_summary(self, source):
        structure_summary = self.source_method_structure_summary(source)
        method_sends = self.source_method_sends(source)
        control_selector_counts = {
            'ifTrue:': 0,
            'ifFalse:': 0,
            'ifTrue:ifFalse:': 0,
            'ifNil:': 0,
            'ifNotNil:': 0,
            'whileTrue:': 0,
            'whileFalse:': 0,
            'to:do:': 0,
        }
        for send_entry in method_sends['sends']:
            send_selector = send_entry['selector']
            if send_selector in control_selector_counts:
                control_selector_counts[send_selector] = (
                    control_selector_counts[send_selector] + 1
                )
        body_start_offset = self.body_start_offset_for_method_source(source)
        code_character_map = self.source_code_character_map(source)
        block_nesting_depth = 0
        max_block_nesting_depth = 0
        index = body_start_offset
        while index < len(source):
            if code_character_map[index]:
                if source[index] == '[':
                    block_nesting_depth = block_nesting_depth + 1
                    if block_nesting_depth > max_block_nesting_depth:
                        max_block_nesting_depth = block_nesting_depth
                if source[index] == ']' and block_nesting_depth > 0:
                    block_nesting_depth = block_nesting_depth - 1
            index = index + 1
        branch_selector_count = (
            control_selector_counts['ifTrue:']
            + control_selector_counts['ifFalse:']
            + control_selector_counts['ifTrue:ifFalse:']
            + control_selector_counts['ifNil:']
            + control_selector_counts['ifNotNil:']
        )
        loop_selector_count = (
            control_selector_counts['whileTrue:']
            + control_selector_counts['whileFalse:']
            + control_selector_counts['to:do:']
        )
        return {
            'control_selector_counts': control_selector_counts,
            'branch_selector_count': branch_selector_count,
            'loop_selector_count': loop_selector_count,
            'max_block_nesting_depth': max_block_nesting_depth,
            'statement_terminator_count': structure_summary[
                'statement_terminator_count'
            ],
            'return_count': structure_summary['return_count'],
            'analysis_limitations': [
                (
                    'Control-flow summary is heuristic and selector-based; '
                    'dynamic dispatch and non-standard control abstractions '
                    'are not resolved.'
                ),
            ],
        }

    def query_scope_class_names(self, package_name, class_name):
        if class_name is not None:
            return [class_name]
        if package_name is not None:
            return sorted(self.list_classes(package_name))
        return sorted(self.all_class_names())

    def selector_names_for_scope(
        self,
        class_name,
        show_instance_side,
        method_category,
    ):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        if method_category == 'all':
            return self.sorted_selectors(class_to_query)
        selectors = class_to_query.selectorsIn(method_category).asSortedCollection()
        return [selector.to_py for selector in selectors]

    def pattern_evaluation_for_method(
        self,
        method_source,
        method_selector,
        ast_pattern,
        sort_by='scan_order',
    ):
        structure_summary = self.source_method_structure_summary(
            method_source
        )
        sends_payload = self.source_method_sends(method_source)
        send_selector_names = [
            send_entry['selector']
            for send_entry in sends_payload['sends']
        ]
        send_type_names = sorted(
            {
                send_entry['send_type']
                for send_entry in sends_payload['sends']
            }
        )
        receiver_hint_names = sorted(
            {
                send_entry['receiver_hint']
                for send_entry in sends_payload['sends']
            }
        )
        statement_count = None
        temporary_count = None
        statement_count_requested = (
            'min_statement_count' in ast_pattern
            or 'max_statement_count' in ast_pattern
            or sort_by == 'statement_count'
        )
        temporary_count_requested = (
            'min_temporary_count' in ast_pattern
            or 'max_temporary_count' in ast_pattern
            or sort_by == 'temporary_count'
        )
        if statement_count_requested or temporary_count_requested:
            method_ast = self.source_method_ast(
                method_source,
                method_selector,
            )
            statement_count = method_ast['statement_count']
            temporary_count = len(method_ast['temporaries'])
        else:
            statement_count = structure_summary['statement_terminator_count']
            temporary_count = 0
        control_flow_summary = None
        control_flow_requested = (
            'min_branch_selector_count' in ast_pattern
            or 'max_branch_selector_count' in ast_pattern
            or 'min_loop_selector_count' in ast_pattern
            or 'max_loop_selector_count' in ast_pattern
            or 'min_max_block_nesting_depth' in ast_pattern
            or 'max_max_block_nesting_depth' in ast_pattern
            or sort_by in (
                'branch_selector_count',
                'loop_selector_count',
                'max_block_nesting_depth',
            )
        )
        if control_flow_requested:
            control_flow_summary = self.source_method_control_flow_summary(
                method_source
            )
        matches = self.method_matches_ast_pattern(
            ast_pattern,
            method_selector,
            structure_summary,
            send_selector_names,
            send_type_names,
            receiver_hint_names,
            statement_count,
            temporary_count,
            control_flow_summary,
        )
        return {
            'matches': matches,
            'structure_summary': structure_summary,
            'statement_count': statement_count,
            'temporary_count': temporary_count,
            'control_flow_summary': control_flow_summary,
        }

    def method_matches_ast_pattern(
        self,
        ast_pattern,
        method_selector,
        structure_summary,
        send_selector_names,
        send_type_names,
        receiver_hint_names,
        statement_count,
        temporary_count,
        control_flow_summary,
    ):
        range_checks = [
            (
                'min_send_count',
                'max_send_count',
                structure_summary['send_count'],
            ),
            (
                'min_keyword_send_count',
                'max_keyword_send_count',
                structure_summary['keyword_send_count'],
            ),
            (
                'min_unary_send_count',
                'max_unary_send_count',
                structure_summary['unary_send_count'],
            ),
            (
                'min_binary_send_count',
                'max_binary_send_count',
                structure_summary['binary_send_count'],
            ),
            (
                'min_block_count',
                'max_block_count',
                structure_summary['block_open_count'],
            ),
            (
                'min_return_count',
                'max_return_count',
                structure_summary['return_count'],
            ),
            (
                'min_cascade_count',
                'max_cascade_count',
                structure_summary['cascade_count'],
            ),
            (
                'min_assignment_count',
                'max_assignment_count',
                structure_summary['assignment_count'],
            ),
            (
                'min_statement_terminator_count',
                'max_statement_terminator_count',
                structure_summary['statement_terminator_count'],
            ),
            (
                'min_explicit_self_send_count',
                'max_explicit_self_send_count',
                structure_summary['explicit_self_send_count'],
            ),
            (
                'min_explicit_super_send_count',
                'max_explicit_super_send_count',
                structure_summary['explicit_super_send_count'],
            ),
            (
                'min_body_line_count',
                'max_body_line_count',
                structure_summary['body_line_count'],
            ),
            (
                'min_statement_count',
                'max_statement_count',
                statement_count,
            ),
            (
                'min_temporary_count',
                'max_temporary_count',
                temporary_count,
            ),
        ]
        if control_flow_summary is not None:
            range_checks = range_checks + [
                (
                    'min_branch_selector_count',
                    'max_branch_selector_count',
                    control_flow_summary['branch_selector_count'],
                ),
                (
                    'min_loop_selector_count',
                    'max_loop_selector_count',
                    control_flow_summary['loop_selector_count'],
                ),
                (
                    'min_max_block_nesting_depth',
                    'max_max_block_nesting_depth',
                    control_flow_summary['max_block_nesting_depth'],
                ),
            ]
        for min_key, max_key, value in range_checks:
            if min_key in ast_pattern and value is not None:
                if value < ast_pattern[min_key]:
                    return False
            if max_key in ast_pattern and value is not None:
                if value > ast_pattern[max_key]:
                    return False
        required_selectors = ast_pattern.get('required_selectors', [])
        for required_selector in required_selectors:
            if required_selector not in send_selector_names:
                return False
        any_required_selectors = ast_pattern.get('any_required_selectors', [])
        if any_required_selectors and not any(
            selector_name in send_selector_names
            for selector_name in any_required_selectors
        ):
            return False
        excluded_selectors = ast_pattern.get('excluded_selectors', [])
        for excluded_selector in excluded_selectors:
            if excluded_selector in send_selector_names:
                return False
        required_send_types = ast_pattern.get('required_send_types', [])
        for required_send_type in required_send_types:
            if required_send_type not in send_type_names:
                return False
        excluded_send_types = ast_pattern.get('excluded_send_types', [])
        for excluded_send_type in excluded_send_types:
            if excluded_send_type in send_type_names:
                return False
        required_receiver_hints = ast_pattern.get(
            'required_receiver_hints',
            [],
        )
        for required_receiver_hint in required_receiver_hints:
            if required_receiver_hint not in receiver_hint_names:
                return False
        excluded_receiver_hints = ast_pattern.get(
            'excluded_receiver_hints',
            [],
        )
        for excluded_receiver_hint in excluded_receiver_hints:
            if excluded_receiver_hint in receiver_hint_names:
                return False
        method_selector_regex = ast_pattern.get('method_selector_regex')
        if method_selector_regex is not None:
            if re.search(method_selector_regex, method_selector) is None:
                return False
        return True

    def source_method_ast(self, source, method_selector=None):
        code_character_map = self.source_code_character_map(source)
        line_column_map = self.source_line_column_map(source)
        body_start_offset = self.body_start_offset_for_method_source(source)
        temporaries, statements_start_offset = (
            self.source_temporaries_after_body_start(
                source,
                code_character_map,
                body_start_offset,
            )
        )
        method_sends = self.source_method_sends(source)
        structure_summary = self.source_method_structure_summary(source)
        statement_entries = self.source_method_statements(
            source,
            code_character_map,
            line_column_map,
            statements_start_offset,
            method_sends['sends'],
        )
        return {
            'schema_version': 1,
            'node_type': 'method',
            'selector': method_selector,
            'header_source': source[:body_start_offset].rstrip('\n'),
            'body_start_offset': body_start_offset,
            'argument_names': [],
            'temporaries': temporaries,
            'statement_count': len(statement_entries),
            'statements': statement_entries,
            'sends': method_sends['sends'],
            'structure_summary': structure_summary,
            'analysis_backend': 'source_heuristic',
            'analysis_limitations': [
                (
                    'This AST is a lightweight source-based approximation; '
                    'it is not the GemStone parser internal tree.'
                ),
                (
                    'Statement boundaries are inferred from top-level periods '
                    'and can miss edge cases with unusual syntax.'
                ),
            ]
            + method_sends['analysis_limitations'],
        }

    def source_temporaries_after_body_start(
        self,
        source,
        code_character_map,
        body_start_offset,
    ):
        cursor = body_start_offset
        while cursor < len(source) and source[cursor].isspace():
            cursor = cursor + 1
        temporaries = []
        body_content_start = cursor
        has_temporary_bar = (
            cursor < len(source)
            and source[cursor] == '|'
            and code_character_map[cursor]
        )
        if has_temporary_bar:
            closing_bar_offset = cursor + 1
            found_closing_bar = False
            while closing_bar_offset < len(source) and not found_closing_bar:
                is_code_character = code_character_map[closing_bar_offset]
                if is_code_character and source[closing_bar_offset] == '|':
                    found_closing_bar = True
                else:
                    closing_bar_offset = closing_bar_offset + 1
            if found_closing_bar:
                temporaries_source = source[cursor + 1:closing_bar_offset]
                temporaries = re.findall(
                    '[A-Za-z][A-Za-z0-9_]*',
                    temporaries_source,
                )
                body_content_start = closing_bar_offset + 1
        return temporaries, body_content_start

    def source_method_statements(
        self,
        source,
        code_character_map,
        line_column_map,
        statements_start_offset,
        method_sends,
    ):
        statement_entries = []
        statement_start = statements_start_offset
        index = statements_start_offset
        bracket_depth = 0
        parenthesis_depth = 0
        brace_depth = 0
        while index < len(source):
            is_code_character = code_character_map[index]
            if is_code_character:
                character = source[index]
                if character == '[':
                    bracket_depth = bracket_depth + 1
                if character == ']' and bracket_depth > 0:
                    bracket_depth = bracket_depth - 1
                if character == '(':
                    parenthesis_depth = parenthesis_depth + 1
                if character == ')' and parenthesis_depth > 0:
                    parenthesis_depth = parenthesis_depth - 1
                if character == '{':
                    brace_depth = brace_depth + 1
                if character == '}' and brace_depth > 0:
                    brace_depth = brace_depth - 1
                has_statement_end = (
                    character == '.'
                    and bracket_depth == 0
                    and parenthesis_depth == 0
                    and brace_depth == 0
                )
                if has_statement_end:
                    statement_entry = self.statement_entry_in_source(
                        source,
                        code_character_map,
                        line_column_map,
                        statement_start,
                        index,
                        len(statement_entries) + 1,
                        method_sends,
                    )
                    if statement_entry is not None:
                        statement_entries.append(statement_entry)
                    statement_start = index + 1
            index = index + 1
        final_statement_entry = self.statement_entry_in_source(
            source,
            code_character_map,
            line_column_map,
            statement_start,
            len(source),
            len(statement_entries) + 1,
            method_sends,
        )
        if final_statement_entry is not None:
            statement_entries.append(final_statement_entry)
        return statement_entries

    def statement_entry_in_source(
        self,
        source,
        code_character_map,
        line_column_map,
        raw_start_offset,
        raw_end_offset,
        statement_index,
        method_sends,
    ):
        start_offset, end_offset = self.trimmed_code_range(
            source,
            code_character_map,
            raw_start_offset,
            raw_end_offset,
        )
        has_content = (
            start_offset is not None
            and end_offset is not None
            and start_offset < end_offset
        )
        if not has_content:
            return None
        statement_source = source[start_offset:end_offset]
        statement_sends = [
            send_entry
            for send_entry in method_sends
            if (
                send_entry['start_offset'] >= start_offset
                and send_entry['end_offset'] <= end_offset
            )
        ]
        stripped_statement = statement_source.lstrip()
        statement_kind = 'expression'
        if stripped_statement.startswith('^'):
            statement_kind = 'return'
        if ':=' in statement_source and statement_kind != 'return':
            statement_kind = 'assignment'
        coordinates = self.source_range_coordinates(
            source,
            line_column_map,
            start_offset,
            end_offset,
        )
        return {
            'node_type': 'statement',
            'statement_index': statement_index,
            'statement_kind': statement_kind,
            'source': statement_source,
            'start_offset': start_offset,
            'end_offset': end_offset,
            'start_line': coordinates['start_line'],
            'start_column': coordinates['start_column'],
            'end_line': coordinates['end_line'],
            'end_column': coordinates['end_column'],
            'send_count': len(statement_sends),
            'sends': statement_sends,
        }

    def trimmed_code_range(
        self,
        source,
        code_character_map,
        raw_start_offset,
        raw_end_offset,
    ):
        start_offset = raw_start_offset
        end_offset = raw_end_offset
        while (
            start_offset < end_offset
            and (
                not code_character_map[start_offset]
                or source[start_offset].isspace()
            )
        ):
            start_offset = start_offset + 1
        while (
            end_offset > start_offset
            and (
                not code_character_map[end_offset - 1]
                or source[end_offset - 1].isspace()
            )
        ):
            end_offset = end_offset - 1
        if start_offset >= end_offset:
            return None, None
        return start_offset, end_offset

    def body_start_offset_for_method_source(self, source):
        header_separator_offset = source.find('\n')
        if header_separator_offset == -1:
            return len(source)
        return header_separator_offset + 1

    def source_line_column_map(self, source):
        line_column_map = []
        line_number = 1
        column_number = 1
        for character in source:
            line_column_map.append(
                (line_number, column_number)
            )
            if character == '\n':
                line_number = line_number + 1
                column_number = 1
            else:
                column_number = column_number + 1
        return line_column_map

    def source_range_coordinates(
        self,
        source,
        line_column_map,
        start_offset,
        end_offset,
    ):
        has_source = len(source) > 0
        safe_start_offset = (
            start_offset
            if start_offset < len(source)
            else len(source) - 1
        )
        safe_end_offset = (
            end_offset - 1
            if end_offset > 0
            else 0
        )
        if safe_end_offset >= len(source):
            safe_end_offset = len(source) - 1
        if not has_source:
            return {
                'start_line': 1,
                'start_column': 1,
                'end_line': 1,
                'end_column': 1,
            }
        start_line, start_column = line_column_map[safe_start_offset]
        end_line, end_column = line_column_map[safe_end_offset]
        return {
            'start_line': start_line,
            'start_column': start_column,
            'end_line': end_line,
            'end_column': end_column,
        }

    def keyword_send_entries_in_source(
        self,
        source,
        code_character_map,
        line_column_map,
        body_start_offset,
    ):
        send_entries = []
        search_start = body_start_offset
        found_more_tokens = True
        while found_more_tokens:
            first_token_range = self.next_keyword_token_range(
                source,
                search_start,
                code_character_map,
            )
            if first_token_range is None:
                found_more_tokens = False
            else:
                token_ranges = [first_token_range]
                next_token_search_start = first_token_range[1]
                found_next_token = True
                while found_next_token:
                    next_token_range = self.next_keyword_token_range_in_statement(
                        source,
                        next_token_search_start,
                        code_character_map,
                    )
                    if next_token_range is None:
                        found_next_token = False
                    else:
                        token_ranges.append(next_token_range)
                        next_token_search_start = next_token_range[1]
                selector = ''.join(
                    source[token_range[0]:token_range[1]]
                    for token_range in token_ranges
                )
                first_token_start = token_ranges[0][0]
                last_token_end = token_ranges[-1][1]
                coordinates = self.source_range_coordinates(
                    source,
                    line_column_map,
                    first_token_start,
                    last_token_end,
                )
                send_entries.append(
                    {
                        'selector': selector,
                        'send_type': 'keyword',
                        'receiver_hint': 'unknown',
                        'start_offset': first_token_start,
                        'end_offset': last_token_end,
                        'token_count': len(token_ranges),
                        **coordinates,
                    }
                )
                search_start = last_token_end
        return send_entries

    def next_keyword_token_range(
        self,
        source,
        search_start,
        code_character_map,
    ):
        token_range = None
        index = search_start
        maximum_index = len(source)
        while index < maximum_index and token_range is None:
            is_code_character = code_character_map[index]
            starts_identifier = is_code_character and source[index].isalpha()
            if starts_identifier:
                identifier_end = self.identifier_end_index(source, index)
                has_colon = (
                    identifier_end < len(source)
                    and source[identifier_end] == ':'
                )
                token_end = identifier_end + 1 if has_colon else identifier_end
                has_boundaries = (
                    has_colon
                    and self.selector_token_in_source_has_boundaries(
                        source,
                        index,
                        token_end,
                    )
                )
                is_symbol_literal = index > 0 and source[index - 1] == '#'
                token_is_code = (
                    has_colon
                    and self.token_range_is_code(
                        code_character_map,
                        index,
                        token_end,
                    )
                )
                has_token = (
                    has_colon
                    and has_boundaries
                    and token_is_code
                    and not is_symbol_literal
                )
                if has_token:
                    token_range = (index, token_end)
                index = identifier_end if identifier_end > index else index + 1
            else:
                index = index + 1
        return token_range

    def next_keyword_token_range_in_statement(
        self,
        source,
        search_start,
        code_character_map,
    ):
        token_range = None
        index = search_start
        parenthesis_depth = 0
        bracket_depth = 0
        brace_depth = 0
        can_search = True
        maximum_index = len(source)
        while index < maximum_index and token_range is None and can_search:
            is_code_character = code_character_map[index]
            if is_code_character:
                character = source[index]
                if character == '(':
                    parenthesis_depth = parenthesis_depth + 1
                elif character == ')':
                    parenthesis_depth = (
                        parenthesis_depth - 1
                        if parenthesis_depth > 0
                        else 0
                    )
                elif character == '[':
                    bracket_depth = bracket_depth + 1
                elif character == ']':
                    bracket_depth = (
                        bracket_depth - 1
                        if bracket_depth > 0
                        else 0
                    )
                elif character == '{':
                    brace_depth = brace_depth + 1
                elif character == '}':
                    brace_depth = (
                        brace_depth - 1
                        if brace_depth > 0
                        else 0
                    )
                at_statement_level = (
                    parenthesis_depth == 0
                    and bracket_depth == 0
                    and brace_depth == 0
                )
                is_statement_delimiter = (
                    character in '.;^' and at_statement_level
                )
                if is_statement_delimiter:
                    can_search = False
                starts_identifier = at_statement_level and source[index].isalpha()
                if starts_identifier and can_search:
                    identifier_end = self.identifier_end_index(source, index)
                    has_colon = (
                        identifier_end < len(source)
                        and source[identifier_end] == ':'
                    )
                    token_end = (
                        identifier_end + 1
                        if has_colon
                        else identifier_end
                    )
                    has_boundaries = (
                        has_colon
                        and self.selector_token_in_source_has_boundaries(
                            source,
                            index,
                            token_end,
                        )
                    )
                    is_symbol_literal = index > 0 and source[index - 1] == '#'
                    token_is_code = (
                        has_colon
                        and self.token_range_is_code(
                            code_character_map,
                            index,
                            token_end,
                        )
                    )
                    has_token = (
                        has_colon
                        and has_boundaries
                        and token_is_code
                        and not is_symbol_literal
                    )
                    if has_token:
                        token_range = (index, token_end)
                    index = (
                        identifier_end
                        if identifier_end > index
                        else index + 1
                    )
                else:
                    index = index + 1
            else:
                index = index + 1
        return token_range

    def identifier_end_index(self, source, start_index):
        index = start_index
        has_more_identifier_characters = True
        while has_more_identifier_characters:
            has_more_source = index < len(source)
            has_identifier_character = (
                has_more_source
                and self.is_identifier_character(source[index])
            )
            if has_identifier_character:
                index = index + 1
            else:
                has_more_identifier_characters = False
        return index

    def explicit_receiver_send_entries_in_source(
        self,
        source,
        code_character_map,
        line_column_map,
        body_start_offset,
    ):
        unary_pattern = re.compile(
            '\\b(self|super)\\s+([A-Za-z][A-Za-z0-9_]*)\\b'
        )
        binary_pattern = re.compile(
            '\\b(self|super)\\s*([+\\-*/\\\\~<>=@%|&?,]{1,3})'
        )
        send_entries = []
        for match in unary_pattern.finditer(source, body_start_offset):
            receiver_name = match.group(1)
            selector_name = match.group(2)
            selector_start = match.start(2)
            selector_end = match.end(2)
            next_character = (
                source[selector_end]
                if selector_end < len(source)
                else ''
            )
            has_keyword_suffix = next_character == ':'
            token_is_code = self.token_range_is_code(
                code_character_map,
                match.start(1),
                selector_end,
            )
            if token_is_code and not has_keyword_suffix:
                coordinates = self.source_range_coordinates(
                    source,
                    line_column_map,
                    selector_start,
                    selector_end,
                )
                send_entries.append(
                    {
                        'selector': selector_name,
                        'send_type': 'unary',
                        'receiver_hint': receiver_name,
                        'start_offset': selector_start,
                        'end_offset': selector_end,
                        'token_count': 1,
                        **coordinates,
                    }
                )
        for match in binary_pattern.finditer(source, body_start_offset):
            receiver_name = match.group(1)
            selector_name = match.group(2)
            selector_start = match.start(2)
            selector_end = match.end(2)
            token_is_code = self.token_range_is_code(
                code_character_map,
                match.start(1),
                selector_end,
            )
            if token_is_code:
                coordinates = self.source_range_coordinates(
                    source,
                    line_column_map,
                    selector_start,
                    selector_end,
                )
                send_entries.append(
                    {
                        'selector': selector_name,
                        'send_type': 'binary',
                        'receiver_hint': receiver_name,
                        'start_offset': selector_start,
                        'end_offset': selector_end,
                        'token_count': 1,
                        **coordinates,
                    }
                )
        return send_entries

    def expression_receiver_send_entries_in_source(
        self,
        source,
        code_character_map,
        line_column_map,
        search_start_offset,
    ):
        unary_pattern = re.compile(
            '([A-Za-z][A-Za-z0-9_]*|[)\\]\\}]|[0-9]+(?:\\.[0-9]+)?)'
            '\\s+'
            '([A-Za-z][A-Za-z0-9_]*)\\b'
        )
        binary_pattern = re.compile(
            '([A-Za-z][A-Za-z0-9_]*|[)\\]\\}]|[0-9]+(?:\\.[0-9]+)?)'
            '\\s*'
            '([+\\-*/\\\\~<>=@%|&?,]{1,3})'
            '\\s*'
        )
        send_entries = []
        for match in unary_pattern.finditer(source, search_start_offset):
            receiver_name = match.group(1)
            selector_name = match.group(2)
            selector_start = match.start(2)
            selector_end = match.end(2)
            next_character = (
                source[selector_end]
                if selector_end < len(source)
                else ''
            )
            has_keyword_suffix = next_character == ':'
            is_symbol_literal = (
                selector_start > 0
                and source[selector_start - 1] == '#'
            )
            token_is_code = self.token_range_is_code(
                code_character_map,
                match.start(1),
                selector_end,
            )
            has_entry = (
                token_is_code
                and not has_keyword_suffix
                and not is_symbol_literal
            )
            if has_entry:
                coordinates = self.source_range_coordinates(
                    source,
                    line_column_map,
                    selector_start,
                    selector_end,
                )
                receiver_hint = (
                    receiver_name
                    if receiver_name in ('self', 'super')
                    else 'unknown'
                )
                send_entries.append(
                    {
                        'selector': selector_name,
                        'send_type': 'unary',
                        'receiver_hint': receiver_hint,
                        'start_offset': selector_start,
                        'end_offset': selector_end,
                        'token_count': 1,
                        **coordinates,
                    }
                )
        for match in binary_pattern.finditer(source, search_start_offset):
            receiver_name = match.group(1)
            selector_name = match.group(2)
            selector_start = match.start(2)
            selector_end = match.end(2)
            token_is_code = self.token_range_is_code(
                code_character_map,
                match.start(1),
                selector_end,
            )
            if token_is_code:
                coordinates = self.source_range_coordinates(
                    source,
                    line_column_map,
                    selector_start,
                    selector_end,
                )
                receiver_hint = (
                    receiver_name
                    if receiver_name in ('self', 'super')
                    else 'unknown'
                )
                send_entries.append(
                    {
                        'selector': selector_name,
                        'send_type': 'binary',
                        'receiver_hint': receiver_hint,
                        'start_offset': selector_start,
                        'end_offset': selector_end,
                        'token_count': 1,
                        **coordinates,
                    }
                )
        return send_entries

    def cascade_send_entries_in_source(
        self,
        source,
        code_character_map,
        line_column_map,
        search_start_offset,
    ):
        send_entries = []
        index = search_start_offset
        while index < len(source):
            is_cascade_separator = (
                code_character_map[index]
                and source[index] == ';'
            )
            if is_cascade_separator:
                token_start = index + 1
                found_token_start = False
                while token_start < len(source) and not found_token_start:
                    is_token_space = source[token_start].isspace()
                    is_token_code = code_character_map[token_start]
                    has_token_start = (
                        not is_token_space
                        and is_token_code
                    )
                    if has_token_start:
                        found_token_start = True
                    else:
                        token_start = token_start + 1
                if found_token_start:
                    starts_identifier = source[token_start].isalpha()
                    starts_binary_token = self.is_binary_selector_character(
                        source[token_start]
                    )
                    if starts_identifier:
                        identifier_end = self.identifier_end_index(
                            source,
                            token_start,
                        )
                        selector_name = source[token_start:identifier_end]
                        has_keyword_suffix = (
                            identifier_end < len(source)
                            and source[identifier_end] == ':'
                        )
                        if not has_keyword_suffix:
                            coordinates = self.source_range_coordinates(
                                source,
                                line_column_map,
                                token_start,
                                identifier_end,
                            )
                            send_entries.append(
                                {
                                    'selector': selector_name,
                                    'send_type': 'unary',
                                    'receiver_hint': 'cascade',
                                    'start_offset': token_start,
                                    'end_offset': identifier_end,
                                    'token_count': 1,
                                    **coordinates,
                                }
                            )
                    if starts_binary_token:
                        token_end = token_start + 1
                        while (
                            token_end < len(source)
                            and self.is_binary_selector_character(
                                source[token_end]
                            )
                            and token_end - token_start < 3
                        ):
                            token_end = token_end + 1
                        coordinates = self.source_range_coordinates(
                            source,
                            line_column_map,
                            token_start,
                            token_end,
                        )
                        send_entries.append(
                            {
                                'selector': source[token_start:token_end],
                                'send_type': 'binary',
                                'receiver_hint': 'cascade',
                                'start_offset': token_start,
                                'end_offset': token_end,
                                'token_count': 1,
                                **coordinates,
                            }
                        )
            index = index + 1
        return send_entries

    def is_binary_selector_character(self, character):
        return character in '+-*/\\~<>=@%|&?,'

    def compile_method(
        self,
        class_name,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        symbol_list = self.gemstone_session.execute('System myUserProfile symbolList')
        return class_to_query.compileMethod_dictionaries_category_environmentId(
            source,
            symbol_list,
            method_category,
            0,
        )

    def compile_method_in_dictionary(
        self,
        class_name,
        in_dictionary,
        show_instance_side,
        source,
        method_category='as yet unclassified',
    ):
        class_literal = self.smalltalk_string_literal(class_name)
        source_literal = self.smalltalk_string_literal(source)
        method_category_literal = self.smalltalk_string_literal(method_category)
        dictionary_expression = self.dictionary_reference_expression(in_dictionary)
        class_side_suffix = '' if show_instance_side else ' class'
        return self.run_code(
            (
                '| classToQuery symbolList |\n'
                'classToQuery := (%s at: (%s asSymbol)).\n'
                'symbolList := System myUserProfile symbolList.\n'
                'classToQuery%s\n'
                '    compileMethod: %s\n'
                '    dictionaries: symbolList\n'
                '    category: %s\n'
                '    environmentId: 0'
            )
            % (
                dictionary_expression,
                class_literal,
                class_side_suffix,
                source_literal,
                method_category_literal,
            )
        )

    def create_class(
        self,
        class_name,
        superclass_name='Object',
        inst_var_names=None,
        class_var_names=None,
        class_inst_var_names=None,
        pool_dictionary_names=None,
        in_dictionary='UserGlobals',
    ):
        inst_var_names = inst_var_names if inst_var_names is not None else []
        class_var_names = class_var_names if class_var_names is not None else []
        class_inst_var_names = (
            class_inst_var_names if class_inst_var_names is not None else []
        )
        pool_dictionary_names = (
            pool_dictionary_names if pool_dictionary_names is not None else []
        )
        source = (
            '%s subclass: #%s\n'
            '    instVarNames: %s\n'
            '    classVars: %s\n'
            '    classInstVars: %s\n'
            '    poolDictionaries: %s\n'
            '    inDictionary: %s'
        ) % (
            superclass_name,
            class_name,
            self.symbol_array_literal(inst_var_names),
            self.symbol_array_literal(class_var_names),
            self.symbol_array_literal(class_inst_var_names),
            self.symbol_array_literal(pool_dictionary_names),
            self.dictionary_reference_expression(in_dictionary),
        )
        return self.run_code(source)

    def create_test_case_class(
        self,
        class_name,
        in_dictionary='UserGlobals',
    ):
        return self.create_class(
            class_name=class_name,
            superclass_name='TestCase',
            in_dictionary=in_dictionary,
        )

    def run_code(self, source):
        return self.gemstone_session.execute(source)

    def symbol_array_literal(self, symbol_names):
        if not symbol_names:
            return '#()'
        return '#(%s)' % ' '.join(symbol_names)

    def smalltalk_string_literal(self, value):
        return "'%s'" % value.replace("'", "''")

    def dictionary_reference_expression(self, in_dictionary):
        if re.match('^[A-Za-z][A-Za-z0-9_]*$', in_dictionary):
            return in_dictionary
        dictionary_literal = self.smalltalk_string_literal(in_dictionary)
        return '(GsPackageLibrary packageLibrary objectNamed: %s)' % (
            dictionary_literal,
        )

    def smalltalk_literal(self, value):
        if value is None:
            return 'nil'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return self.smalltalk_string_literal(value)
        raise DomainException(
            'literal_value must be None, bool, int, float, or string.'
        )

    def class_reference_expression(self, class_name, show_instance_side):
        if show_instance_side:
            return class_name
        return '%s class' % class_name

    def selector_reference_expression(self, method_selector):
        selector_literal = self.smalltalk_string_literal(method_selector)
        return '(%s asSymbol)' % selector_literal

    def evaluate_source(self, source):
        result = self.run_code(source)
        return {
            'result': render_result(result),
        }

    def run_gemstone_tests(self, test_case_class_name):
        test_case_class = self.gemstone_session.resolve_symbol(test_case_class_name)
        test_suite = test_case_class.suite()
        test_result = test_suite.run()
        return self.summarized_test_result(test_result)

    def run_test_method(self, test_case_class_name, test_method_selector):
        selector_literal = self.smalltalk_string_literal(test_method_selector)
        test_result = self.run_code(
            (
                '| testCaseClass testCase testSuite |\n'
                'testCaseClass := %s.\n'
                'testCase := testCaseClass selector: (%s asSymbol).\n'
                'testSuite := TestSuite named: testCaseClass name.\n'
                'testSuite addTest: testCase.\n'
                'testSuite run'
            )
            % (test_case_class_name, selector_literal)
        )
        return self.summarized_test_result(test_result)

    def debug_test_method(self, test_case_class_name, test_method_selector):
        selector_literal = self.smalltalk_string_literal(test_method_selector)
        self.run_code(
            (
                '| testCase |\n'
                'testCase := %s selector: (%s asSymbol).\n'
                'testCase runCase'
            )
            % (test_case_class_name, selector_literal)
        )

    def summarized_test_result(self, test_result):
        failure_entries = [
            failure.printString().to_py
            for failure in test_result.failures().asSortedCollection()
        ]
        error_entries = [
            error.printString().to_py
            for error in test_result.errors().asSortedCollection()
        ]
        return {
            'run_count': test_result.runCount().to_py,
            'failure_count': test_result.failureCount().to_py,
            'error_count': test_result.errorCount().to_py,
            'has_passed': test_result.hasPassed().to_py,
            'failures': failure_entries,
            'errors': error_entries,
        }

    def run_tests_in_package(self, package_name):
        test_case_classes = self.list_test_case_classes(package_name)
        run_count = 0
        failure_count = 0
        error_count = 0
        has_passed = True
        failure_entries = []
        error_entries = []
        for test_case_class_name in test_case_classes:
            test_result = self.run_gemstone_tests(test_case_class_name)
            run_count += test_result['run_count']
            failure_count += test_result['failure_count']
            error_count += test_result['error_count']
            has_passed = has_passed and test_result['has_passed']
            failure_entries += test_result['failures']
            error_entries += test_result['errors']
        return {
            'package_name': package_name,
            'test_case_classes': test_case_classes,
            'run_count': run_count,
            'failure_count': failure_count,
            'error_count': error_count,
            'has_passed': has_passed,
            'failures': failure_entries,
            'errors': error_entries,
        }

    def get_class_definition(self, class_name):
        gemstone_class = self.resolved_class(class_name)
        if gemstone_class is None:
            raise DomainException('Unknown class_name.')
        superclass = gemstone_class.superclass()
        superclass_name = None
        if not superclass.isNil().to_py:
            superclass_name = superclass.name().to_py
        pool_names = [
            gemstone_pool.name().to_py
            for gemstone_pool in gemstone_class.allSharedPools()
        ]
        return {
            'class_name': gemstone_class.name().to_py,
            'superclass_name': superclass_name,
            'package_name': gemstone_class.category().to_py,
            'inst_var_names': [
                gemstone_name.to_py
                for gemstone_name in gemstone_class.instVarNames()
            ],
            'class_var_names': [
                gemstone_name.to_py
                for gemstone_name in gemstone_class.classVarNames()
            ],
            'class_inst_var_names': [
                gemstone_name.to_py
                for gemstone_name in gemstone_class.gemstone_class().instVarNames()
            ],
            'pool_dictionary_names': pool_names,
        }

    def delete_class(self, class_name, in_dictionary='UserGlobals'):
        return self.run_code(
            (
                '| classToDelete |\n'
                'classToDelete := %s at: #%s ifAbsent: [ nil ].\n'
                'classToDelete ifNotNil: [\n'
                '    classToDelete removeAllMethods: 0.\n'
                '    classToDelete class removeAllMethods: 0.\n'
                '    %s removeKey: #%s ifAbsent: [].\n'
                '].'
            )
            % (in_dictionary, class_name, in_dictionary, class_name)
        )

    def delete_method(self, class_name, method_selector, show_instance_side):
        class_reference = self.class_reference_expression(
            class_name,
            show_instance_side,
        )
        selector_literal = self.smalltalk_string_literal(method_selector)
        return self.run_code(
            (
                '%s removeSelector: (%s asSymbol) '
                'environmentId: 0 ifAbsent: []'
            )
            % (class_reference, selector_literal)
        )

    def set_method_category(
        self,
        class_name,
        method_selector,
        method_category,
        show_instance_side,
    ):
        method_source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        return self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=method_source,
            method_category=method_category,
        )

    def class_inherits_from(self, class_name, ancestor_class_name):
        source = '%s inheritsFrom: %s' % (class_name, ancestor_class_name)
        return self.run_code(source).to_py

    def list_test_case_classes(self, package_name=None):
        class_names = (
            self.list_classes(package_name)
            if package_name
            else self.all_class_names()
        )
        return sorted(
            [
                class_name
                for class_name in class_names
                if self.class_inherits_from(class_name, 'TestCase')
            ]
        )

    def method_move_preview(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        self.ensure_refactoring_uses_real_ast('method move preview')
        source_show_instance_side = self.validated_show_instance_side(
            source_show_instance_side
        )
        target_show_instance_side = self.validated_show_instance_side(
            target_show_instance_side
        )
        move_plan = self.method_move_plan(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
        )
        return self.method_move_summary(move_plan)

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
        self.ensure_refactoring_uses_real_ast('method move apply')
        source_show_instance_side = self.validated_show_instance_side(
            source_show_instance_side
        )
        target_show_instance_side = self.validated_show_instance_side(
            target_show_instance_side
        )
        overwrite_target_method = self.validated_boolean_flag(
            overwrite_target_method,
            'overwrite_target_method',
        )
        delete_source_method = self.validated_boolean_flag(
            delete_source_method,
            'delete_source_method',
        )
        move_plan = self.method_move_plan(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
        )
        if move_plan['target_has_method'] and not overwrite_target_method:
            raise DomainException(
                (
                    'Target %s (%s side) already defines %s. '
                    'Pass overwrite_target_method=true to replace it.'
                )
                % (
                    target_class_name,
                    'instance'
                    if target_show_instance_side
                    else 'class',
                    method_selector,
                )
            )
        self.compile_method(
            class_name=target_class_name,
            show_instance_side=target_show_instance_side,
            source=move_plan['source_method_source'],
            method_category=move_plan['source_method_category'],
        )
        source_deleted = False
        if delete_source_method:
            self.delete_method(
                class_name=source_class_name,
                method_selector=method_selector,
                show_instance_side=source_show_instance_side,
            )
            source_deleted = True
        summary = self.method_move_summary(move_plan)
        summary['applied'] = True
        summary['overwrite_target_method'] = overwrite_target_method
        summary['delete_source_method'] = delete_source_method
        summary['source_deleted'] = source_deleted
        return summary

    def method_move_plan(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        source_show_instance_side = self.validated_show_instance_side(
            source_show_instance_side
        )
        target_show_instance_side = self.validated_show_instance_side(
            target_show_instance_side
        )
        is_same_source_and_target = (
            source_class_name == target_class_name
            and source_show_instance_side == target_show_instance_side
        )
        if is_same_source_and_target:
            raise DomainException(
                (
                    'source_class_name/source_show_instance_side and '
                    'target_class_name/target_show_instance_side '
                    'must identify different method dictionaries.'
                )
            )
        source_method_source = self.get_method_source(
            source_class_name,
            method_selector,
            source_show_instance_side,
        )
        source_method_category = self.get_method_category(
            source_class_name,
            method_selector,
            source_show_instance_side,
        )
        target_class_to_query = self.class_to_query(
            target_class_name,
            target_show_instance_side,
        )
        target_selector_names = self.sorted_selectors(target_class_to_query)
        target_has_method = method_selector in target_selector_names
        sender_summaries = self.selector_occurrence_summaries(
            method_selector,
            'senders',
        )
        source_sender_summaries = [
            sender_summary
            for sender_summary in sender_summaries
            if (
                sender_summary['class_name'] == source_class_name
                and sender_summary['show_instance_side']
                == source_show_instance_side
            )
        ]
        return {
            'source_class_name': source_class_name,
            'source_show_instance_side': source_show_instance_side,
            'target_class_name': target_class_name,
            'target_show_instance_side': target_show_instance_side,
            'method_selector': method_selector,
            'source_method_category': source_method_category,
            'source_method_source': source_method_source,
            'source_method_character_count': len(source_method_source),
            'target_has_method': target_has_method,
            'total_sender_count': len(sender_summaries),
            'source_sender_count': len(source_sender_summaries),
            'sender_examples': self.limited_entries(sender_summaries, 20),
        }

    def method_move_summary(self, move_plan):
        warnings = []
        if move_plan['target_has_method']:
            warnings.append(
                (
                    'Target %s (%s side) already defines %s.'
                )
                % (
                    move_plan['target_class_name'],
                    'instance'
                    if move_plan['target_show_instance_side']
                    else 'class',
                    move_plan['method_selector'],
                )
            )
        if move_plan['source_sender_count'] > 0:
            warnings.append(
                (
                    '%s methods in source class/side send %s and may break '
                    'if source method is deleted.'
                )
                % (
                    move_plan['source_sender_count'],
                    move_plan['method_selector'],
                )
            )
        cross_class_sender_count = (
            move_plan['total_sender_count'] - move_plan['source_sender_count']
        )
        if cross_class_sender_count > 0:
            warnings.append(
                (
                    '%s additional static senders outside source class/side '
                    'also send %s; receiver type is dynamic.'
                )
                % (
                    cross_class_sender_count,
                    move_plan['method_selector'],
                )
            )
        return {
            'source_class_name': move_plan['source_class_name'],
            'source_show_instance_side': (
                move_plan['source_show_instance_side']
            ),
            'target_class_name': move_plan['target_class_name'],
            'target_show_instance_side': (
                move_plan['target_show_instance_side']
            ),
            'method_selector': move_plan['method_selector'],
            'source_method_category': move_plan['source_method_category'],
            'source_method_character_count': (
                move_plan['source_method_character_count']
            ),
            'target_has_method': move_plan['target_has_method'],
            'total_sender_count': move_plan['total_sender_count'],
            'source_sender_count': move_plan['source_sender_count'],
            'sender_examples': move_plan['sender_examples'],
            'warnings': warnings,
        }

    def method_add_parameter_preview(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        self.ensure_refactoring_uses_real_ast('add parameter preview')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        add_parameter_plan = self.method_add_parameter_plan(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )
        return self.method_add_parameter_summary(add_parameter_plan)

    def apply_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        self.ensure_refactoring_uses_real_ast('add parameter apply')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        add_parameter_plan = self.method_add_parameter_plan(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=add_parameter_plan['new_method_source'],
            method_category=add_parameter_plan['method_category'],
        )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=add_parameter_plan['compatibility_wrapper_source'],
            method_category=add_parameter_plan['method_category'],
        )
        summary = self.method_add_parameter_summary(add_parameter_plan)
        summary['applied'] = True
        return summary

    def method_add_parameter_plan(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        selector_tokens = self.selector_keyword_tokens(method_selector)
        if not selector_tokens:
            raise DomainException(
                'method_selector must be a keyword selector.'
            )
        method_source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        method_category = self.get_method_category(
            class_name,
            method_selector,
            show_instance_side,
        )
        old_arguments = self.method_argument_names_for_method(
            class_name,
            show_instance_side,
            method_selector,
        )
        method_header, method_body, old_arguments = (
            self.keyword_method_header_body_and_arguments(
                method_source,
                selector_tokens,
                method_selector,
                old_arguments,
            )
        )
        new_selector = method_selector + parameter_keyword
        new_method_header = (
            method_header
            + ' '
            + parameter_keyword
            + ' '
            + parameter_name
        )
        new_method_source = self.method_source_from_header_and_body(
            new_method_header,
            method_body,
        )
        new_selector_exists = self.method_exists(
            class_name,
            new_selector,
            show_instance_side,
        )
        forward_segments = []
        for token_index in range(len(selector_tokens)):
            forward_segments.append(
                '%s %s'
                % (
                    selector_tokens[token_index],
                    old_arguments[token_index],
                )
            )
        forward_segments.append(
            '%s %s'
            % (
                parameter_keyword,
                default_argument_source,
            )
        )
        compatibility_wrapper_header = method_header
        compatibility_wrapper_body = '    ^self %s' % ' '.join(forward_segments)
        compatibility_wrapper_source = self.method_source_from_header_and_body(
            compatibility_wrapper_header,
            compatibility_wrapper_body,
        )
        sender_summaries = self.selector_occurrence_summaries(
            method_selector,
            'senders',
        )
        source_sender_summaries = [
            sender_summary
            for sender_summary in sender_summaries
            if (
                sender_summary['class_name'] == class_name
                and sender_summary['show_instance_side'] == show_instance_side
            )
        ]
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'old_selector': method_selector,
            'new_selector': new_selector,
            'parameter_keyword': parameter_keyword,
            'parameter_name': parameter_name,
            'default_argument_source': default_argument_source,
            'method_category': method_category,
            'new_selector_exists': new_selector_exists,
            'new_method_source': new_method_source,
            'compatibility_wrapper_source': compatibility_wrapper_source,
            'total_sender_count': len(sender_summaries),
            'source_sender_count': len(source_sender_summaries),
            'sender_examples': self.limited_entries(sender_summaries, 20),
        }

    def method_add_parameter_summary(self, add_parameter_plan):
        warnings = []
        if add_parameter_plan['new_selector_exists']:
            warnings.append(
                (
                    '%s already exists on %s (%s side) and will be replaced.'
                )
                % (
                    add_parameter_plan['new_selector'],
                    add_parameter_plan['class_name'],
                    'instance'
                    if add_parameter_plan['show_instance_side']
                    else 'class',
                )
            )
        if add_parameter_plan['total_sender_count'] > 0:
            warnings.append(
                (
                    '%s static senders still target %s and will route through '
                    'the compatibility wrapper.'
                )
                % (
                    add_parameter_plan['total_sender_count'],
                    add_parameter_plan['old_selector'],
                )
            )
        return {
            'class_name': add_parameter_plan['class_name'],
            'show_instance_side': add_parameter_plan['show_instance_side'],
            'old_selector': add_parameter_plan['old_selector'],
            'new_selector': add_parameter_plan['new_selector'],
            'parameter_keyword': add_parameter_plan['parameter_keyword'],
            'parameter_name': add_parameter_plan['parameter_name'],
            'default_argument_source': (
                add_parameter_plan['default_argument_source']
            ),
            'method_category': add_parameter_plan['method_category'],
            'new_selector_exists': add_parameter_plan['new_selector_exists'],
            'compatibility_wrapper': True,
            'total_sender_count': add_parameter_plan['total_sender_count'],
            'source_sender_count': add_parameter_plan['source_sender_count'],
            'sender_examples': add_parameter_plan['sender_examples'],
            'warnings': warnings,
        }

    def method_remove_parameter_preview(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        rewrite_source_senders=False,
    ):
        self.ensure_refactoring_uses_real_ast('remove parameter preview')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        rewrite_source_senders = self.validated_boolean_flag(
            rewrite_source_senders,
            'rewrite_source_senders',
        )
        remove_parameter_plan = self.method_remove_parameter_plan(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            rewrite_source_senders=rewrite_source_senders,
        )
        return self.method_remove_parameter_summary(remove_parameter_plan)

    def apply_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        overwrite_new_method=False,
        rewrite_source_senders=False,
    ):
        self.ensure_refactoring_uses_real_ast('remove parameter apply')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        overwrite_new_method = self.validated_boolean_flag(
            overwrite_new_method,
            'overwrite_new_method',
        )
        rewrite_source_senders = self.validated_boolean_flag(
            rewrite_source_senders,
            'rewrite_source_senders',
        )
        remove_parameter_plan = self.method_remove_parameter_plan(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            rewrite_source_senders=rewrite_source_senders,
        )
        if (
            remove_parameter_plan['new_selector_exists']
            and not overwrite_new_method
        ):
            raise DomainException(
                (
                    '%s already exists on %s (%s side). '
                    'Pass overwrite_new_method=true to replace it.'
                )
                % (
                    remove_parameter_plan['new_selector'],
                    class_name,
                    'instance' if show_instance_side else 'class',
                )
            )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=remove_parameter_plan['new_method_source'],
            method_category=remove_parameter_plan['method_category'],
        )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=remove_parameter_plan['compatibility_wrapper_source'],
            method_category=remove_parameter_plan['method_category'],
        )
        if rewrite_source_senders:
            for caller_rewrite_plan in remove_parameter_plan[
                'source_sender_rewrite_plans'
            ]:
                self.compile_method(
                    class_name=class_name,
                    show_instance_side=show_instance_side,
                    source=caller_rewrite_plan['updated_source'],
                    method_category=caller_rewrite_plan['method_category'],
                )
        summary = self.method_remove_parameter_summary(remove_parameter_plan)
        summary['applied'] = True
        summary['overwrite_new_method'] = overwrite_new_method
        summary['rewrite_source_senders'] = rewrite_source_senders
        summary['rewritten_source_sender_count'] = len(
            remove_parameter_plan['source_sender_rewrite_plans']
        )
        return summary

    def method_remove_parameter_plan(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        rewrite_source_senders=False,
    ):
        rewrite_source_senders = self.validated_boolean_flag(
            rewrite_source_senders,
            'rewrite_source_senders',
        )
        selector_tokens = self.selector_keyword_tokens(method_selector)
        if not selector_tokens:
            raise DomainException(
                'method_selector must be a keyword selector.'
            )
        if parameter_keyword not in selector_tokens:
            raise DomainException(
                '%s is not part of %s.'
                % (
                    parameter_keyword,
                    method_selector,
                )
            )
        parameter_index = selector_tokens.index(parameter_keyword)
        method_source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        method_category = self.get_method_category(
            class_name,
            method_selector,
            show_instance_side,
        )
        old_arguments = self.method_argument_names_for_method(
            class_name,
            show_instance_side,
            method_selector,
        )
        method_header, method_body, old_arguments = (
            self.keyword_method_header_body_and_arguments(
                method_source,
                selector_tokens,
                method_selector,
                old_arguments,
            )
        )
        removed_argument_name = old_arguments[parameter_index]
        if self.method_body_references_argument_name(
            method_body,
            removed_argument_name,
        ):
            raise DomainException(
                (
                    'Cannot remove %s from %s because argument %s is '
                    'referenced in the method body.'
                )
                % (
                    parameter_keyword,
                    method_selector,
                    removed_argument_name,
                )
            )
        new_selector_tokens = [
            selector_tokens[token_index]
            for token_index in range(len(selector_tokens))
            if token_index != parameter_index
        ]
        new_argument_names = [
            old_arguments[token_index]
            for token_index in range(len(old_arguments))
            if token_index != parameter_index
        ]
        new_selector = ''.join(new_selector_tokens)
        creates_unary_selector = not new_selector
        if creates_unary_selector:
            new_selector = parameter_keyword[:-1]
        new_method_header = self.keyword_header_for_selector_tokens_and_arguments(
            new_selector_tokens,
            new_argument_names,
            unary_selector=new_selector,
        )
        new_method_source = self.method_source_from_header_and_body(
            new_method_header,
            method_body,
        )
        new_selector_exists = self.method_exists(
            class_name,
            new_selector,
            show_instance_side,
        )
        forward_segments = []
        for token_index in range(len(new_selector_tokens)):
            forward_segments.append(
                '%s %s'
                % (
                    new_selector_tokens[token_index],
                    new_argument_names[token_index],
                )
            )
        if forward_segments:
            compatibility_wrapper_body = (
                '    ^self %s' % ' '.join(forward_segments)
            )
        else:
            compatibility_wrapper_body = '    ^self %s' % new_selector
        compatibility_wrapper_source = self.method_source_from_header_and_body(
            method_header,
            compatibility_wrapper_body,
        )
        sender_summaries = self.selector_occurrence_summaries(
            method_selector,
            'senders',
        )
        source_sender_summaries = [
            sender_summary
            for sender_summary in sender_summaries
            if (
                sender_summary['class_name'] == class_name
                and sender_summary['show_instance_side'] == show_instance_side
            )
        ]
        source_sender_rewrite_plans = []
        if rewrite_source_senders:
            source_sender_rewrite_plans = (
                self.method_remove_parameter_caller_rewrite_plans(
                    class_name,
                    show_instance_side,
                    source_sender_summaries,
                    method_selector,
                    selector_tokens,
                    parameter_index,
                    new_selector,
                )
            )
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'old_selector': method_selector,
            'new_selector': new_selector,
            'parameter_keyword': parameter_keyword,
            'removed_argument_name': removed_argument_name,
            'creates_unary_selector': creates_unary_selector,
            'method_category': method_category,
            'new_selector_exists': new_selector_exists,
            'new_method_source': new_method_source,
            'compatibility_wrapper_source': compatibility_wrapper_source,
            'total_sender_count': len(sender_summaries),
            'source_sender_count': len(source_sender_summaries),
            'rewrite_source_senders': rewrite_source_senders,
            'source_sender_rewrite_plan_count': len(
                source_sender_rewrite_plans
            ),
            'source_sender_rewrite_plans': source_sender_rewrite_plans,
            'source_sender_rewrite_examples': self.limited_entries(
                [
                    {
                        'method_selector': caller_rewrite_plan[
                            'method_selector'
                        ],
                        'rewritten_send_count': caller_rewrite_plan[
                            'rewritten_send_count'
                        ],
                    }
                    for caller_rewrite_plan in source_sender_rewrite_plans
                ],
                20,
            ),
            'sender_examples': self.limited_entries(sender_summaries, 20),
        }

    def method_remove_parameter_summary(self, remove_parameter_plan):
        warnings = []
        if remove_parameter_plan['new_selector_exists']:
            warnings.append(
                (
                    '%s already exists on %s (%s side) and will be replaced.'
                )
                % (
                    remove_parameter_plan['new_selector'],
                    remove_parameter_plan['class_name'],
                    'instance'
                    if remove_parameter_plan['show_instance_side']
                    else 'class',
                )
            )
        rewritten_source_sender_count = remove_parameter_plan[
            'source_sender_rewrite_plan_count'
        ]
        remaining_sender_count = (
            remove_parameter_plan['total_sender_count']
            - rewritten_source_sender_count
        )
        if (
            remove_parameter_plan['rewrite_source_senders']
            and rewritten_source_sender_count > 0
        ):
            warnings.append(
                (
                    '%s same-class sender methods will be rewritten to %s.'
                )
                % (
                    rewritten_source_sender_count,
                    remove_parameter_plan['new_selector'],
                )
            )
        if remaining_sender_count > 0:
            warnings.append(
                (
                    '%s static senders still target %s and will route '
                    'through the compatibility wrapper.'
                )
                % (
                    remaining_sender_count,
                    remove_parameter_plan['old_selector'],
                )
            )
        return {
            'class_name': remove_parameter_plan['class_name'],
            'show_instance_side': remove_parameter_plan['show_instance_side'],
            'old_selector': remove_parameter_plan['old_selector'],
            'new_selector': remove_parameter_plan['new_selector'],
            'parameter_keyword': remove_parameter_plan['parameter_keyword'],
            'removed_argument_name': remove_parameter_plan[
                'removed_argument_name'
            ],
            'creates_unary_selector': remove_parameter_plan[
                'creates_unary_selector'
            ],
            'method_category': remove_parameter_plan['method_category'],
            'new_selector_exists': remove_parameter_plan[
                'new_selector_exists'
            ],
            'compatibility_wrapper': True,
            'total_sender_count': remove_parameter_plan[
                'total_sender_count'
            ],
            'source_sender_count': remove_parameter_plan[
                'source_sender_count'
            ],
            'rewrite_source_senders': remove_parameter_plan[
                'rewrite_source_senders'
            ],
            'source_sender_rewrite_plan_count': remove_parameter_plan[
                'source_sender_rewrite_plan_count'
            ],
            'source_sender_rewrite_examples': remove_parameter_plan[
                'source_sender_rewrite_examples'
            ],
            'sender_examples': remove_parameter_plan['sender_examples'],
            'warnings': warnings,
        }

    def method_remove_parameter_caller_rewrite_plans(
        self,
        class_name,
        show_instance_side,
        source_sender_summaries,
        old_selector,
        old_selector_tokens,
        parameter_index,
        new_selector,
    ):
        rewrite_plans = []
        seen_selectors = set()
        for sender_summary in source_sender_summaries:
            method_selector = sender_summary['method_selector']
            if method_selector == old_selector:
                continue
            if method_selector in seen_selectors:
                continue
            seen_selectors.add(method_selector)
            caller_source = self.get_method_source(
                class_name,
                method_selector,
                show_instance_side,
            )
            replacement_plan = (
                self.remove_keyword_send_parameter_replacement_plan_in_source(
                    caller_source,
                    old_selector_tokens,
                    parameter_index,
                )
            )
            if not replacement_plan:
                continue
            updated_source = self.source_with_replaced_selector_tokens(
                caller_source,
                replacement_plan,
            )
            if updated_source == caller_source:
                continue
            rewrite_plans.append(
                {
                    'class_name': class_name,
                    'show_instance_side': show_instance_side,
                    'method_selector': method_selector,
                    'method_category': self.get_method_category(
                        class_name,
                        method_selector,
                        show_instance_side,
                    ),
                    'new_selector': new_selector,
                    'rewritten_send_count': len(replacement_plan),
                    'updated_source': updated_source,
                }
            )
        return sorted(
            rewrite_plans,
            key=lambda rewrite_plan: rewrite_plan['method_selector'],
        )

    def remove_keyword_send_parameter_replacement_plan_in_source(
        self,
        source,
        selector_tokens,
        parameter_index,
    ):
        code_character_map = self.source_code_character_map(source)
        token_ranges_by_send = self.selector_token_ranges_in_source(
            source,
            selector_tokens,
        )
        replacement_plan = []
        for token_ranges in token_ranges_by_send:
            if parameter_index >= len(token_ranges):
                continue
            removed_token_start = token_ranges[parameter_index][0]
            if parameter_index + 1 < len(token_ranges):
                removed_token_end = token_ranges[parameter_index + 1][0]
            else:
                removed_token_end = self.keyword_argument_end_offset_in_source(
                    source,
                    code_character_map,
                    token_ranges[parameter_index][1],
                )
            if removed_token_end > removed_token_start:
                replacement_plan.append(
                    (
                        removed_token_start,
                        removed_token_end,
                        '',
                    )
                )
        return sorted(
            replacement_plan,
            key=lambda replacement: replacement[0],
        )

    def keyword_argument_end_offset_in_source(
        self,
        source,
        code_character_map,
        argument_start_offset,
    ):
        cursor = argument_start_offset
        while cursor < len(source) and source[cursor].isspace():
            cursor = cursor + 1
        index = cursor
        parenthesis_depth = 0
        bracket_depth = 0
        brace_depth = 0
        while index < len(source):
            if code_character_map[index]:
                character = source[index]
                if character == '(':
                    parenthesis_depth = parenthesis_depth + 1
                elif character == ')':
                    if parenthesis_depth > 0:
                        parenthesis_depth = parenthesis_depth - 1
                    else:
                        return index
                elif character == '[':
                    bracket_depth = bracket_depth + 1
                elif character == ']':
                    if bracket_depth > 0:
                        bracket_depth = bracket_depth - 1
                    else:
                        return index
                elif character == '{':
                    brace_depth = brace_depth + 1
                elif character == '}':
                    if brace_depth > 0:
                        brace_depth = brace_depth - 1
                    else:
                        return index
                at_argument_level = (
                    parenthesis_depth == 0
                    and bracket_depth == 0
                    and brace_depth == 0
                )
                if at_argument_level and character in '.;':
                    return index
            index = index + 1
        return len(source)

    def method_extract_preview(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
    ):
        self.ensure_refactoring_uses_real_ast('extract method preview')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        extract_plan = self.method_extract_plan(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        )
        return self.method_extract_summary(extract_plan)

    def apply_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
        overwrite_new_method=False,
    ):
        self.ensure_refactoring_uses_real_ast('extract method apply')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        overwrite_new_method = self.validated_boolean_flag(
            overwrite_new_method,
            'overwrite_new_method',
        )
        extract_plan = self.method_extract_plan(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        )
        if extract_plan['new_selector_exists'] and not overwrite_new_method:
            raise DomainException(
                (
                    '%s already exists on %s (%s side). '
                    'Pass overwrite_new_method=true to replace it.'
                )
                % (
                    new_selector,
                    class_name,
                    'instance' if show_instance_side else 'class',
                )
            )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=extract_plan['new_method_source'],
            method_category=extract_plan['method_category'],
        )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=extract_plan['updated_method_source'],
            method_category=extract_plan['method_category'],
        )
        summary = self.method_extract_summary(extract_plan)
        summary['applied'] = True
        summary['overwrite_new_method'] = overwrite_new_method
        return summary

    def method_extract_plan(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
    ):
        selector_tokens = self.selector_keyword_tokens(new_selector)
        is_keyword_selector = bool(selector_tokens)
        is_unary_selector = self.is_unary_selector(new_selector)
        if not is_keyword_selector and not is_unary_selector:
            raise DomainException(
                'new_selector must be unary or keyword.'
            )
        source_method_source = self.get_method_source(
            class_name,
            method_selector,
            show_instance_side,
        )
        method_category = self.get_method_category(
            class_name,
            method_selector,
            show_instance_side,
        )
        source_method_ast = self.method_ast(
            class_name,
            method_selector,
            show_instance_side,
        )
        selected_statement_entries = self.selected_statement_entries(
            source_method_ast['statements'],
            statement_indexes,
        )
        selected_statement_indexes = [
            statement_entry['statement_index']
            for statement_entry in selected_statement_entries
        ]
        expected_statement_indexes = list(
            range(
                selected_statement_indexes[0],
                selected_statement_indexes[0]
                + len(selected_statement_indexes),
            )
        )
        if selected_statement_indexes != expected_statement_indexes:
            raise DomainException(
                'statement_indexes must be contiguous.'
            )
        return_statement_entries = [
            statement_entry
            for statement_entry in selected_statement_entries
            if statement_entry['statement_kind'] == 'return'
        ]
        if return_statement_entries:
            raise DomainException(
                'Extract cannot include return statements.'
            )
        extraction_start_offset = selected_statement_entries[0][
            'start_offset'
        ]
        extraction_end_offset = selected_statement_entries[-1]['end_offset']
        extracted_body = self.extracted_method_body_from_statement_entries(
            selected_statement_entries
        )
        source_method_argument_names = self.method_argument_names_for_method(
            class_name,
            show_instance_side,
            method_selector,
        )
        extracted_argument_names = self.extraction_argument_names(
            source_method_source,
            selected_statement_entries,
            source_method_argument_names,
            source_method_ast['temporaries'],
        )
        extracted_argument_count = len(extracted_argument_names)
        if is_keyword_selector:
            expected_argument_count = len(selector_tokens)
            if expected_argument_count != extracted_argument_count:
                raise DomainException(
                    (
                        '%s has %s keyword arguments but extracted statements '
                        'require %s arguments (%s).'
                    )
                    % (
                        new_selector,
                        expected_argument_count,
                        extracted_argument_count,
                        ', '.join(extracted_argument_names)
                        if extracted_argument_names
                        else 'none',
                    )
                )
            new_method_header = self.keyword_header_for_selector_tokens_and_arguments(
                selector_tokens,
                extracted_argument_names,
            )
            call_segments = []
            for argument_index in range(len(selector_tokens)):
                call_segments.append(
                    '%s %s'
                    % (
                        selector_tokens[argument_index],
                        extracted_argument_names[argument_index],
                    )
                )
            call_source = 'self %s' % ' '.join(call_segments)
        else:
            if extracted_argument_names:
                raise DomainException(
                    (
                        'Extracted statements reference caller variables (%s). '
                        'Use a keyword selector with %s arguments.'
                    )
                    % (
                        ', '.join(extracted_argument_names),
                        extracted_argument_count,
                    )
                )
            new_method_header = new_selector
            call_source = 'self %s' % new_selector
        new_method_source = self.method_source_from_header_and_body(
            new_method_header,
            extracted_body,
        )
        updated_method_source = self.source_with_single_replacement(
            source_method_source,
            extraction_start_offset,
            extraction_end_offset,
            call_source,
        )
        new_selector_exists = self.method_exists(
            class_name,
            new_selector,
            show_instance_side,
        )
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'method_selector': method_selector,
            'new_selector': new_selector,
            'statement_indexes': selected_statement_indexes,
            'method_category': method_category,
            'new_selector_exists': new_selector_exists,
            'new_method_source': new_method_source,
            'updated_method_source': updated_method_source,
            'extracted_statement_count': len(selected_statement_entries),
            'extracted_argument_count': extracted_argument_count,
            'extracted_argument_names': extracted_argument_names,
            'extracted_source_character_count': (
                extraction_end_offset - extraction_start_offset
            ),
        }

    def method_extract_summary(self, extract_plan):
        warnings = []
        if extract_plan['new_selector_exists']:
            warnings.append(
                (
                    '%s already exists on %s (%s side) and will be replaced.'
                )
                % (
                    extract_plan['new_selector'],
                    extract_plan['class_name'],
                    'instance'
                    if extract_plan['show_instance_side']
                    else 'class',
                )
            )
        return {
            'class_name': extract_plan['class_name'],
            'show_instance_side': extract_plan['show_instance_side'],
            'method_selector': extract_plan['method_selector'],
            'new_selector': extract_plan['new_selector'],
            'statement_indexes': extract_plan['statement_indexes'],
            'method_category': extract_plan['method_category'],
            'new_selector_exists': extract_plan['new_selector_exists'],
            'extracted_statement_count': extract_plan[
                'extracted_statement_count'
            ],
            'extracted_argument_count': extract_plan[
                'extracted_argument_count'
            ],
            'extracted_argument_names': extract_plan[
                'extracted_argument_names'
            ],
            'extracted_source_character_count': extract_plan[
                'extracted_source_character_count'
            ],
            'warnings': warnings,
        }

    def is_unary_selector(self, selector):
        return re.fullmatch('[A-Za-z][A-Za-z0-9_]*', selector) is not None

    def method_argument_names(self, method_source, method_selector):
        selector_tokens = self.selector_keyword_tokens(method_selector)
        if selector_tokens:
            _, _, argument_names = (
                self.keyword_method_header_body_and_arguments(
                    method_source,
                    selector_tokens,
                    method_selector,
                )
            )
            return argument_names
        is_binary_selector = (
            bool(method_selector)
            and all(
                self.is_binary_selector_character(character)
                for character in method_selector
            )
        )
        if is_binary_selector:
            method_header, _ = self.method_header_and_body(method_source)
            binary_match = re.match(
                r'^\s*%s\s+([A-Za-z][A-Za-z0-9_]*)\s*$'
                % re.escape(method_selector),
                method_header,
            )
            if binary_match is None:
                raise DomainException(
                    'Could not parse binary method header.'
                )
            return [binary_match.group(1)]
        return []

    def extraction_argument_names(
        self,
        source_method_source,
        selected_statement_entries,
        method_argument_names,
        temporary_names,
    ):
        scoped_names = []
        for candidate_name in method_argument_names + temporary_names:
            if candidate_name not in scoped_names:
                scoped_names.append(candidate_name)
        if not scoped_names:
            return []
        assigned_names = []
        for statement_entry in selected_statement_entries:
            assignment_match = re.match(
                r'\s*([A-Za-z][A-Za-z0-9_]*)\s*:=',
                statement_entry['source'],
            )
            has_assignment = assignment_match is not None
            if has_assignment:
                assigned_name = assignment_match.group(1)
                if assigned_name not in assigned_names:
                    assigned_names.append(assigned_name)
        selected_ranges = [
            (
                statement_entry['start_offset'],
                statement_entry['end_offset'],
            )
            for statement_entry in selected_statement_entries
        ]
        identifier_occurrences = self.identifier_occurrences_in_ranges(
            source_method_source,
            selected_ranges,
        )
        argument_names = []
        for occurrence in identifier_occurrences:
            name = occurrence['name']
            is_scoped = name in scoped_names
            is_assigned_name = name in assigned_names
            is_already_added = name in argument_names
            if is_scoped and not is_assigned_name and not is_already_added:
                argument_names.append(name)
        return argument_names

    def identifier_occurrences_in_ranges(self, source, selected_ranges):
        code_character_map = self.source_code_character_map(source)
        occurrences = []
        for selected_range in selected_ranges:
            range_start, range_end = selected_range
            cursor = max(0, range_start)
            safe_end = min(len(source), range_end)
            while cursor < safe_end:
                character = source[cursor]
                previous_character = source[cursor - 1] if cursor > 0 else ''
                starts_identifier = (
                    code_character_map[cursor]
                    and (character.isalpha() or character == '_')
                    and (
                        not previous_character
                        or not self.is_identifier_character(
                            previous_character
                        )
                    )
                )
                if starts_identifier:
                    token_end = cursor + 1
                    while (
                        token_end < safe_end
                        and code_character_map[token_end]
                        and self.is_identifier_character(source[token_end])
                    ):
                        token_end = token_end + 1
                    occurrences.append(
                        {
                            'name': source[cursor:token_end],
                            'start_offset': cursor,
                            'end_offset': token_end,
                        }
                    )
                    cursor = token_end
                else:
                    cursor = cursor + 1
        return occurrences

    def method_inline_preview(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
    ):
        self.ensure_refactoring_uses_real_ast('inline method preview')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        inline_plan = self.method_inline_plan(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
        )
        return self.method_inline_summary(inline_plan)

    def apply_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
        delete_inlined_method=False,
    ):
        self.ensure_refactoring_uses_real_ast('inline method apply')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        delete_inlined_method = self.validated_boolean_flag(
            delete_inlined_method,
            'delete_inlined_method',
        )
        inline_plan = self.method_inline_plan(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
        )
        self.compile_method(
            class_name=class_name,
            show_instance_side=show_instance_side,
            source=inline_plan['updated_caller_source'],
            method_category=inline_plan['caller_method_category'],
        )
        if delete_inlined_method:
            self.delete_method(
                class_name=class_name,
                method_selector=inline_selector,
                show_instance_side=show_instance_side,
            )
        summary = self.method_inline_summary(inline_plan)
        summary['applied'] = True
        summary['delete_inlined_method'] = delete_inlined_method
        return summary

    def method_inline_plan(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
    ):
        if ':' in inline_selector:
            raise DomainException('inline_selector must be a unary selector.')
        inline_method_source = self.get_method_source(
            class_name,
            inline_selector,
            show_instance_side,
        )
        inline_method_ast = self.method_ast(
            class_name,
            inline_selector,
            show_instance_side,
        )
        inline_expression = self.method_inline_expression_from_callee(
            inline_method_source,
            inline_selector,
            inline_method_ast=inline_method_ast,
        )
        caller_method_source = self.get_method_source(
            class_name,
            caller_selector,
            show_instance_side,
        )
        caller_method_category = self.get_method_category(
            class_name,
            caller_selector,
            show_instance_side,
        )
        replacement_plan = self.self_unary_send_replacement_plan_in_source(
            caller_method_source,
            inline_selector,
            '(%s)' % inline_expression,
        )
        if not replacement_plan:
            raise DomainException(
                (
                    'Could not find self %s sends in %s for inline.'
                )
                % (
                    inline_selector,
                    caller_selector,
                )
            )
        updated_caller_source = self.source_with_replaced_selector_tokens(
            caller_method_source,
            replacement_plan,
        )
        inline_sender_summaries = self.selector_occurrence_summaries(
            inline_selector,
            'senders',
        )
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'caller_selector': caller_selector,
            'inline_selector': inline_selector,
            'caller_method_category': caller_method_category,
            'inline_expression': inline_expression,
            'updated_caller_source': updated_caller_source,
            'replacement_count': len(replacement_plan),
            'total_sender_count': len(inline_sender_summaries),
            'sender_examples': self.limited_entries(
                inline_sender_summaries,
                20,
            ),
        }

    def method_inline_summary(self, inline_plan):
        warnings = []
        if inline_plan['total_sender_count'] > inline_plan['replacement_count']:
            warnings.append(
                (
                    '%s static senders exist for %s; only %s sends in caller '
                    'will be inlined by this workflow.'
                )
                % (
                    inline_plan['total_sender_count'],
                    inline_plan['inline_selector'],
                    inline_plan['replacement_count'],
                )
            )
        return {
            'class_name': inline_plan['class_name'],
            'show_instance_side': inline_plan['show_instance_side'],
            'caller_selector': inline_plan['caller_selector'],
            'inline_selector': inline_plan['inline_selector'],
            'inline_expression': inline_plan['inline_expression'],
            'replacement_count': inline_plan['replacement_count'],
            'total_sender_count': inline_plan['total_sender_count'],
            'sender_examples': inline_plan['sender_examples'],
            'warnings': warnings,
        }

    def method_header_and_body(self, method_source):
        header_separator_offset = method_source.find('\n')
        if header_separator_offset == -1:
            return method_source, ''
        return (
            method_source[:header_separator_offset],
            method_source[header_separator_offset + 1:],
        )

    def method_source_from_header_and_body(self, method_header, method_body):
        if method_body:
            return '%s\n%s' % (method_header, method_body)
        return method_header

    def keyword_method_header_body_and_arguments(
        self,
        method_source,
        selector_tokens,
        method_selector,
        argument_names=None,
    ):
        if argument_names is None:
            header_end_offset, argument_names = (
                self.keyword_header_end_and_argument_names(
                    method_source,
                    selector_tokens,
                )
            )
        else:
            header_end_offset = (
                self.keyword_header_end_for_selector_tokens_and_argument_names(
                    method_source,
                    selector_tokens,
                    argument_names,
                )
            )
        method_header = method_source[:header_end_offset].strip()
        method_body = method_source[header_end_offset:]
        if method_body.startswith('\n'):
            method_body = method_body[1:]
        else:
            method_body = method_body.lstrip()
        if method_body and not method_body.startswith('    '):
            method_body = '    ' + method_body
        expected_argument_count = len(selector_tokens)
        actual_argument_count = len(argument_names)
        if actual_argument_count != expected_argument_count:
            raise DomainException(
                (
                    'Could not parse keyword header for %s. '
                    'Expected %s arguments, found %s.'
                )
                % (
                    method_selector,
                    expected_argument_count,
                    actual_argument_count,
                )
            )
        return method_header, method_body, argument_names

    def keyword_header_end_for_selector_tokens_and_argument_names(
        self,
        method_source,
        selector_tokens,
        argument_names,
    ):
        expected_argument_count = len(selector_tokens)
        actual_argument_count = len(argument_names)
        if actual_argument_count != expected_argument_count:
            raise DomainException(
                (
                    'Could not parse keyword method header. '
                    'Expected %s argument names, found %s.'
                )
                % (
                    expected_argument_count,
                    actual_argument_count,
                )
            )
        cursor = 0
        for selector_token, argument_name in zip(
            selector_tokens,
            argument_names,
        ):
            while cursor < len(method_source) and method_source[cursor].isspace():
                cursor = cursor + 1
            if not method_source.startswith(selector_token, cursor):
                raise DomainException(
                    'Could not parse keyword method header.'
                )
            cursor = cursor + len(selector_token)
            while cursor < len(method_source) and method_source[cursor].isspace():
                cursor = cursor + 1
            if not method_source.startswith(argument_name, cursor):
                raise DomainException(
                    (
                        'Could not parse keyword method header argument %s.'
                    )
                    % argument_name
                )
            cursor = cursor + len(argument_name)
        return cursor

    def keyword_header_end_and_argument_names(
        self,
        method_source,
        selector_tokens,
    ):
        argument_names = []
        cursor = 0
        for selector_token in selector_tokens:
            while cursor < len(method_source) and method_source[cursor].isspace():
                cursor = cursor + 1
            if not method_source.startswith(selector_token, cursor):
                raise DomainException(
                    'Could not parse keyword method header.'
                )
            cursor = cursor + len(selector_token)
            while cursor < len(method_source) and method_source[cursor].isspace():
                cursor = cursor + 1
            argument_match = re.match(
                '[A-Za-z][A-Za-z0-9_]*',
                method_source[cursor:],
            )
            if argument_match is None:
                raise DomainException(
                    'Could not parse keyword method header argument.'
                )
            argument_name = argument_match.group(0)
            argument_names.append(argument_name)
            cursor = cursor + len(argument_name)
        return cursor, argument_names

    def keyword_header_for_selector_tokens_and_arguments(
        self,
        selector_tokens,
        argument_names,
        unary_selector=None,
    ):
        if selector_tokens:
            if len(selector_tokens) != len(argument_names):
                raise DomainException(
                    (
                        'Cannot build keyword method header: '
                        '%s selector tokens but %s arguments.'
                    )
                    % (
                        len(selector_tokens),
                        len(argument_names),
                    )
                )
            segments = []
            for token_index in range(len(selector_tokens)):
                segments.append(
                    '%s %s'
                    % (
                        selector_tokens[token_index],
                        argument_names[token_index],
                    )
                )
            return ' '.join(segments)
        if unary_selector is None:
            raise DomainException(
                'Cannot build method header without selector tokens.'
            )
        return unary_selector

    def method_body_references_argument_name(
        self,
        method_body,
        argument_name,
    ):
        argument_pattern = re.compile(
            r'(^|[^A-Za-z0-9_])%s([^A-Za-z0-9_]|$)'
            % re.escape(argument_name)
        )
        return argument_pattern.search(method_body) is not None

    def source_with_single_replacement(
        self,
        source,
        replacement_start_offset,
        replacement_end_offset,
        replacement_source,
    ):
        replacement_plan = [
            (
                replacement_start_offset,
                replacement_end_offset,
                replacement_source,
            )
        ]
        return self.source_with_replaced_selector_tokens(
            source,
            replacement_plan,
        )

    def selected_statement_entries(
        self,
        statement_entries,
        statement_indexes,
    ):
        normalized_indexes = self.sorted_unique_positive_indexes(
            statement_indexes
        )
        statement_entries_by_index = {
            statement_entry['statement_index']: statement_entry
            for statement_entry in statement_entries
        }
        selected_entries = []
        for statement_index in normalized_indexes:
            if statement_index not in statement_entries_by_index:
                raise DomainException(
                    'statement_indexes includes invalid index %s.'
                    % statement_index
                )
            selected_entries.append(
                statement_entries_by_index[statement_index]
            )
        return selected_entries

    def extracted_method_body_from_statement_entries(
        self,
        statement_entries,
    ):
        statement_sources = [
            statement_entry['source'].strip()
            for statement_entry in statement_entries
        ]
        return '    ' + '.\n    '.join(statement_sources)

    def sorted_unique_positive_indexes(self, input_indexes):
        if not isinstance(input_indexes, list) or not input_indexes:
            raise DomainException(
                'statement_indexes must be a non-empty list of integers.'
            )
        normalized_indexes = []
        for index_value in input_indexes:
            if not isinstance(index_value, int) or index_value <= 0:
                raise DomainException(
                    'statement_indexes must contain positive integers only.'
                )
            if index_value not in normalized_indexes:
                normalized_indexes.append(index_value)
        return sorted(normalized_indexes)

    def method_inline_expression_from_callee(
        self,
        inline_method_source,
        inline_selector,
        inline_method_ast=None,
    ):
        if inline_method_ast is None:
            inline_method_ast = self.source_method_ast(
                inline_method_source,
                inline_selector,
            )
        if inline_method_ast['temporaries']:
            raise DomainException(
                (
                    '%s declares temporaries and cannot be inlined '
                    'with this workflow.'
                )
                % inline_selector
            )
        has_single_line_fallback = inline_method_ast['statement_count'] == 0
        if has_single_line_fallback:
            inline_header, _ = self.method_header_and_body(
                inline_method_source
            )
            if inline_header.startswith(inline_selector):
                inline_expression = inline_header[
                    len(inline_selector):
                ].strip()
                if inline_expression.startswith('^'):
                    inline_expression = inline_expression[1:].strip()
                if inline_expression:
                    return inline_expression
        if inline_method_ast['statement_count'] != 1:
            raise DomainException(
                (
                    '%s must have exactly one statement for inline '
                    'with this workflow.'
                )
                % inline_selector
            )
        statement_entry = inline_method_ast['statements'][0]
        if statement_entry['statement_kind'] == 'assignment':
            raise DomainException(
                (
                    '%s has an assignment statement and cannot be inlined '
                    'with this workflow.'
                )
                % inline_selector
            )
        inline_expression = statement_entry['source'].strip()
        if inline_expression.startswith('^'):
            inline_expression = inline_expression[1:].strip()
        if not inline_expression:
            raise DomainException(
                '%s does not have an inlineable expression.'
                % inline_selector
            )
        return inline_expression

    def self_unary_send_replacement_plan_in_source(
        self,
        source,
        unary_selector,
        replacement_source,
    ):
        code_character_map = self.source_code_character_map(source)
        body_start_offset = self.body_start_offset_for_method_source(source)
        search_start_offset = (
            0
            if body_start_offset >= len(source)
            else body_start_offset
        )
        pattern = re.compile(
            r'\bself\s+%s\b' % re.escape(unary_selector)
        )
        replacement_plan = []
        for match in pattern.finditer(source, search_start_offset):
            match_start = match.start(0)
            match_end = match.end(0)
            has_keyword_suffix = (
                match_end < len(source)
                and source[match_end] == ':'
            )
            token_is_code = self.token_range_is_code(
                code_character_map,
                match_start,
                match_end,
            )
            if token_is_code and not has_keyword_suffix:
                replacement_plan.append(
                    (
                        match_start,
                        match_end,
                        replacement_source,
                    )
                )
        return replacement_plan

    def method_exists(self, class_name, method_selector, show_instance_side):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        selector_names = self.sorted_selectors(class_to_query)
        return method_selector in selector_names

    def selector_rename_preview(self, old_selector, new_selector):
        self.ensure_refactoring_uses_real_ast('selector rename preview')
        planned_changes = self.selector_rename_plan(
            old_selector,
            new_selector,
        )
        return {
            'old_selector': old_selector,
            'new_selector': new_selector,
            'implementor_count': len(
                [
                    planned_change
                    for planned_change in planned_changes
                    if planned_change['change_type'] == 'implementor'
                ]
            ),
            'sender_count': len(
                [
                    planned_change
                    for planned_change in planned_changes
                    if planned_change['change_type'] == 'sender'
                ]
            ),
            'total_changes': len(planned_changes),
            'changes': [
                {
                    'class_name': planned_change['class_name'],
                    'show_instance_side': planned_change['show_instance_side'],
                    'method_selector': planned_change['method_selector'],
                    'method_category': planned_change['method_category'],
                    'change_type': planned_change['change_type'],
                }
                for planned_change in planned_changes
            ],
        }

    def apply_selector_rename(self, old_selector, new_selector):
        self.ensure_refactoring_uses_real_ast('selector rename apply')
        planned_changes = self.selector_rename_plan(
            old_selector,
            new_selector,
        )
        for planned_change in planned_changes:
            self.compile_method(
                class_name=planned_change['class_name'],
                show_instance_side=planned_change['show_instance_side'],
                source=planned_change['updated_source'],
                method_category=planned_change['method_category'],
            )
        if old_selector != new_selector:
            deleted_implementors = set()
            for planned_change in planned_changes:
                is_implementor_change = (
                    planned_change['change_type'] == 'implementor'
                )
                implementor_key = (
                    planned_change['class_name'],
                    planned_change['show_instance_side'],
                )
                has_not_deleted_implementor = (
                    implementor_key not in deleted_implementors
                )
                if is_implementor_change and has_not_deleted_implementor:
                    self.delete_method(
                        class_name=planned_change['class_name'],
                        method_selector=old_selector,
                        show_instance_side=planned_change['show_instance_side'],
                    )
                    deleted_implementors.add(implementor_key)
        preview = self.selector_rename_preview(old_selector, new_selector)
        preview['applied_change_count'] = len(planned_changes)
        preview['old_selector_removed'] = old_selector != new_selector
        return preview

    def method_rename_preview(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        self.ensure_refactoring_uses_real_ast('method rename preview')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        planned_changes = self.method_rename_plan(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )
        return self.method_rename_summary(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
            planned_changes,
        )

    def apply_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        self.ensure_refactoring_uses_real_ast('method rename apply')
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        planned_changes = self.method_rename_plan(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )
        for planned_change in planned_changes:
            self.compile_method(
                class_name=planned_change['class_name'],
                show_instance_side=planned_change['show_instance_side'],
                source=planned_change['updated_source'],
                method_category=planned_change['method_category'],
            )
        has_implementor_change = any(
            planned_change['change_type'] == 'implementor'
            for planned_change in planned_changes
        )
        should_remove_old_selector = (
            old_selector != new_selector
            and has_implementor_change
        )
        if should_remove_old_selector:
            self.delete_method(
                class_name=class_name,
                method_selector=old_selector,
                show_instance_side=show_instance_side,
            )
        preview = self.method_rename_summary(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
            planned_changes,
        )
        preview['applied_change_count'] = len(planned_changes)
        preview['old_selector_removed'] = should_remove_old_selector
        return preview

    def method_rename_summary(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
        planned_changes,
    ):
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'old_selector': old_selector,
            'new_selector': new_selector,
            'sender_scope': 'same_class_side_only',
            'implementor_count': len(
                [
                    planned_change
                    for planned_change in planned_changes
                    if planned_change['change_type'] == 'implementor'
                ]
            ),
            'sender_count': len(
                [
                    planned_change
                    for planned_change in planned_changes
                    if planned_change['change_type'] == 'sender'
                ]
            ),
            'total_changes': len(planned_changes),
            'changes': [
                {
                    'class_name': planned_change['class_name'],
                    'show_instance_side': planned_change['show_instance_side'],
                    'method_selector': planned_change['method_selector'],
                    'method_category': planned_change['method_category'],
                    'change_type': planned_change['change_type'],
                }
                for planned_change in planned_changes
            ],
        }

    def method_rename_plan(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        class_to_query = self.class_to_query(
            class_name,
            show_instance_side,
        )
        implementor_method = class_to_query.compiledMethodAt(old_selector)
        selector_expression = self.selector_reference_expression(old_selector)
        senders = self.run_code(
            'ClassOrganizer new sendersOf: %s' % selector_expression
        )
        sender_methods = self.flatten_compiled_methods(senders)
        planned_changes = []
        planned_method_keys = set()
        implementor_change = self.planned_selector_rename_change(
            implementor_method,
            old_selector,
            new_selector,
            'implementor',
        )
        if implementor_change is not None:
            planned_changes.append(implementor_change)
            planned_method_keys.add(
                (
                    implementor_change['class_name'],
                    implementor_change['show_instance_side'],
                    implementor_change['method_selector'],
                )
            )
        for compiled_method in sender_methods:
            method_summary = self.method_summary(compiled_method)
            matches_target_class = (
                method_summary['class_name'] == class_name
                and method_summary['show_instance_side'] == show_instance_side
            )
            if matches_target_class:
                planned_change = self.planned_selector_rename_change(
                    compiled_method,
                    old_selector,
                    new_selector,
                    'sender',
                )
                planned_change_key = (
                    (
                        planned_change['class_name'],
                        planned_change['show_instance_side'],
                        planned_change['method_selector'],
                    )
                    if planned_change is not None
                    else None
                )
                has_not_seen_method = (
                    planned_change_key not in planned_method_keys
                    if planned_change is not None
                    else False
                )
                if planned_change is not None and has_not_seen_method:
                    planned_changes.append(planned_change)
                    planned_method_keys.add(planned_change_key)
        return sorted(
            planned_changes,
            key=lambda planned_change: (
                planned_change['class_name'],
                planned_change['show_instance_side'],
                planned_change['method_selector'],
            ),
        )

    def selector_rename_plan(self, old_selector, new_selector):
        selector_expression = self.selector_reference_expression(old_selector)
        implementors = self.run_code(
            'ClassOrganizer new implementorsOf: %s' % selector_expression
        )
        senders = self.run_code(
            'ClassOrganizer new sendersOf: %s' % selector_expression
        )
        implementor_methods = self.flatten_compiled_methods(implementors)
        sender_methods = self.flatten_compiled_methods(senders)
        planned_changes = []
        planned_method_keys = set()
        for compiled_method in implementor_methods:
            planned_change = self.planned_selector_rename_change(
                compiled_method,
                old_selector,
                new_selector,
                'implementor',
            )
            if planned_change is not None:
                planned_changes.append(planned_change)
                planned_method_keys.add(
                    (
                        planned_change['class_name'],
                        planned_change['show_instance_side'],
                        planned_change['method_selector'],
                    )
                )
        for compiled_method in sender_methods:
            planned_change = self.planned_selector_rename_change(
                compiled_method,
                old_selector,
                new_selector,
                'sender',
            )
            planned_change_key = (
                (
                    planned_change['class_name'],
                    planned_change['show_instance_side'],
                    planned_change['method_selector'],
                )
                if planned_change is not None
                else None
            )
            has_not_seen_method = (
                planned_change_key not in planned_method_keys
                if planned_change is not None
                else False
            )
            if planned_change is not None and has_not_seen_method:
                planned_changes.append(planned_change)
                planned_method_keys.add(planned_change_key)
        return sorted(
            planned_changes,
            key=lambda planned_change: (
                planned_change['class_name'],
                planned_change['show_instance_side'],
                planned_change['method_selector'],
            ),
        )

    def flatten_compiled_methods(self, candidate_value):
        flattened_methods = []
        candidate_class_name = candidate_value.gemstone_class().name().to_py
        if candidate_class_name == 'GsNMethod':
            flattened_methods.append(candidate_value)
        else:
            try:
                for nested_candidate in candidate_value:
                    flattened_methods += self.flatten_compiled_methods(
                        nested_candidate
                    )
            except (TypeError, GemstoneError, GemstoneApiError):
                flattened_methods = []
        return flattened_methods

    def planned_selector_rename_change(
        self,
        compiled_method,
        old_selector,
        new_selector,
        change_type,
    ):
        source = compiled_method.sourceString().to_py
        updated_source = self.renamed_selector_source(
            source,
            old_selector,
            new_selector,
        )
        if source == updated_source:
            return None
        selector = compiled_method.selector().to_py
        in_class = compiled_method.inClass()
        show_instance_side = not in_class.isMeta().to_py
        in_class_name = in_class.name().to_py
        class_name = (
            in_class_name[:-6]
            if not show_instance_side and in_class_name.endswith(' class')
            else in_class_name
        )
        method_category = self.get_method_category(
            class_name,
            selector,
            show_instance_side,
        )
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'method_selector': selector,
            'method_category': method_category,
            'change_type': change_type,
            'updated_source': updated_source,
        }

    def renamed_selector_source(self, source, old_selector, new_selector):
        old_tokens = (
            self.selector_keyword_tokens(old_selector)
            if ':' in old_selector
            else [old_selector]
        )
        new_tokens = (
            self.selector_keyword_tokens(new_selector)
            if ':' in new_selector
            else [new_selector]
        )
        if len(old_tokens) != len(new_tokens):
            return source
        selector_token_ranges = self.selector_token_ranges_in_source(
            source,
            old_tokens,
        )
        replacement_plan = self.replacement_plan_for_selector_tokens(
            selector_token_ranges,
            new_tokens,
        )
        return self.source_with_replaced_selector_tokens(
            source,
            replacement_plan,
        )

    def selector_token_ranges_in_source(self, source, selector_tokens):
        if not selector_tokens:
            return []
        code_character_map = self.source_code_character_map(source)
        selector_token_ranges = []
        search_start = 0
        found_more = True
        while found_more:
            first_token_range = self.next_selector_token_range(
                source,
                selector_tokens[0],
                search_start,
                code_character_map,
            )
            if first_token_range is None:
                found_more = False
            else:
                matched_token_ranges = [first_token_range]
                previous_token_range = first_token_range
                matched_all_tokens = True
                for selector_token in selector_tokens[1:]:
                    if matched_all_tokens:
                        next_token_range = (
                            self.next_selector_token_range_in_statement(
                                source,
                                selector_token,
                                previous_token_range[1],
                                code_character_map,
                            )
                        )
                        if next_token_range is None:
                            matched_all_tokens = False
                        else:
                            matched_token_ranges.append(next_token_range)
                            previous_token_range = next_token_range
                if matched_all_tokens:
                    selector_token_ranges.append(matched_token_ranges)
                    search_start = matched_token_ranges[-1][1]
                else:
                    search_start = first_token_range[1]
        return selector_token_ranges

    def next_selector_token_range(
        self,
        source,
        selector_token,
        search_start,
        code_character_map,
    ):
        maximum_start = len(source) - len(selector_token)
        index = search_start
        while index <= maximum_start:
            if source.startswith(selector_token, index):
                token_end = index + len(selector_token)
                has_boundaries = self.selector_token_in_source_has_boundaries(
                    source,
                    index,
                    token_end,
                )
                is_code = self.token_range_is_code(
                    code_character_map,
                    index,
                    token_end,
                )
                if has_boundaries and is_code:
                    return (index, token_end)
            index = index + 1
        return None

    def next_selector_token_range_in_statement(
        self,
        source,
        selector_token,
        search_start,
        code_character_map,
    ):
        maximum_start = len(source) - len(selector_token)
        index = search_start
        parenthesis_depth = 0
        bracket_depth = 0
        brace_depth = 0
        while index <= maximum_start:
            is_code_character = code_character_map[index]
            if is_code_character:
                character = source[index]
                if character == '(':
                    parenthesis_depth = parenthesis_depth + 1
                elif character == ')':
                    parenthesis_depth = (
                        parenthesis_depth - 1
                        if parenthesis_depth > 0
                        else 0
                    )
                elif character == '[':
                    bracket_depth = bracket_depth + 1
                elif character == ']':
                    bracket_depth = (
                        bracket_depth - 1
                        if bracket_depth > 0
                        else 0
                    )
                elif character == '{':
                    brace_depth = brace_depth + 1
                elif character == '}':
                    brace_depth = (
                        brace_depth - 1
                        if brace_depth > 0
                        else 0
                    )
                at_statement_level = (
                    parenthesis_depth == 0
                    and bracket_depth == 0
                    and brace_depth == 0
                )
                if character in '.;^' and at_statement_level:
                    return None
                if source.startswith(selector_token, index):
                    token_end = index + len(selector_token)
                    has_boundaries = (
                        self.selector_token_in_source_has_boundaries(
                            source,
                            index,
                            token_end,
                        )
                    )
                    is_code = self.token_range_is_code(
                        code_character_map,
                        index,
                        token_end,
                    )
                    if has_boundaries and is_code and at_statement_level:
                        return (index, token_end)
            index = index + 1
        return None

    def selector_token_in_source_has_boundaries(
        self,
        source,
        token_start,
        token_end,
    ):
        previous_character = (
            source[token_start - 1]
            if token_start > 0
            else ''
        )
        next_character = (
            source[token_end]
            if token_end < len(source)
            else ''
        )
        has_start_boundary = (
            not previous_character
            or not self.is_identifier_character(previous_character)
        )
        has_end_boundary = (
            not next_character
            or not self.is_identifier_character(next_character)
        )
        return has_start_boundary and has_end_boundary

    def is_identifier_character(self, character):
        return character.isalnum() or character == '_'

    def token_range_is_code(
        self,
        code_character_map,
        token_start,
        token_end,
    ):
        index = token_start
        is_code = True
        while index < token_end and is_code:
            is_code = code_character_map[index]
            index = index + 1
        return is_code

    def source_code_character_map(self, source):
        code_character_map = [True for _ in source]
        index = 0
        state = 'code'
        while index < len(source):
            character = source[index]
            if state == 'code':
                if character == "'":
                    code_character_map[index] = False
                    state = 'string'
                elif character == '"':
                    code_character_map[index] = False
                    state = 'comment'
            elif state == 'string':
                code_character_map[index] = False
                if character == "'":
                    has_escaped_quote = (
                        index + 1 < len(source)
                        and source[index + 1] == "'"
                    )
                    if has_escaped_quote:
                        code_character_map[index + 1] = False
                        index = index + 1
                    else:
                        state = 'code'
            elif state == 'comment':
                code_character_map[index] = False
                if character == '"':
                    state = 'code'
            index = index + 1
        return code_character_map

    def replacement_plan_for_selector_tokens(
        self,
        selector_token_ranges,
        replacement_tokens,
    ):
        replacement_plan = []
        for token_ranges in selector_token_ranges:
            for token_index in range(len(token_ranges)):
                token_range = token_ranges[token_index]
                replacement_plan.append(
                    (
                        token_range[0],
                        token_range[1],
                        replacement_tokens[token_index],
                    )
                )
        return sorted(
            replacement_plan,
            key=lambda replacement: replacement[0],
        )

    def source_with_replaced_selector_tokens(
        self,
        source,
        replacement_plan,
    ):
        if not replacement_plan:
            return source
        source_fragments = []
        cursor = 0
        for token_start, token_end, replacement in replacement_plan:
            source_fragments.append(source[cursor:token_start])
            source_fragments.append(replacement)
            cursor = token_end
        source_fragments.append(source[cursor:])
        return ''.join(source_fragments)

    def selector_replacement_pattern(self, selector):
        escaped_selector = re.escape(selector)
        identifier_selector_pattern = re.compile('^[A-Za-z][A-Za-z0-9_:]*$')
        if identifier_selector_pattern.match(selector):
            return re.compile(
                (
                    '(?<![A-Za-z0-9_])'
                    + escaped_selector
                    + '(?![A-Za-z0-9_])'
                )
            )
        return re.compile(escaped_selector)

    def selector_keyword_tokens(self, selector):
        if ':' not in selector:
            return []
        selector_parts = selector.split(':')
        if not selector_parts or selector_parts[-1] != '':
            return []
        return [
            keyword + ':'
            for keyword in selector_parts[:-1]
            if keyword
        ]

    def global_set(
        self,
        symbol_name,
        literal_value,
        in_dictionary='UserGlobals',
    ):
        literal_source = self.smalltalk_literal(literal_value)
        return self.run_code(
            '%s at: #%s put: %s' % (
                in_dictionary,
                symbol_name,
                literal_source,
            )
        )

    def global_remove(self, symbol_name, in_dictionary='UserGlobals'):
        return self.run_code(
            '%s removeKey: #%s ifAbsent: []' % (in_dictionary, symbol_name)
        )

    def global_exists(self, symbol_name, in_dictionary='UserGlobals'):
        return self.run_code(
            '%s includesKey: #%s' % (in_dictionary, symbol_name)
        ).to_py

    def find_classes(self, search_input):
        try:
            pattern = re.compile(search_input, re.IGNORECASE)
        except re.error as error:
            raise DomainException('Invalid search pattern: %s' % error)
        return [
            class_name
            for class_name in self.all_class_names()
            if pattern.search(class_name)
        ]

    def find_selectors(self, search_input):
        selector_matches = set()
        class_names = self.all_class_names()
        for class_name in class_names:
            matching_names = self.matching_selector_names_for_class(
                class_name,
                search_input,
            )
            selector_matches.update(matching_names)
        return sorted(selector_matches)

    def find_implementors(self, method_name):
        search_result = self.find_implementors_with_summary(method_name)
        return search_result['implementors']

    def find_implementors_with_summary(
        self,
        method_name,
        max_results=None,
        count_only=False,
    ):
        method_summaries = self.selector_occurrence_summaries(
            method_name,
            'implementors',
        )
        implementors = self.implementor_entries_from_method_summaries(
            method_summaries
        )
        total_count = len(implementors)
        limited_implementors = (
            []
            if count_only
            else self.limited_entries(
                implementors,
                max_results,
            )
        )
        return {
            'implementors': limited_implementors,
            'total_count': total_count,
            'returned_count': len(limited_implementors),
        }

    def find_senders(
        self,
        method_name,
        max_results=None,
        count_only=False,
    ):
        method_summaries = self.selector_occurrence_summaries(
            method_name,
            'senders',
        )
        total_count = len(method_summaries)
        limited_senders = (
            []
            if count_only
            else self.limited_entries(method_summaries, max_results)
        )
        return {
            'senders': limited_senders,
            'total_count': total_count,
            'returned_count': len(limited_senders),
        }

    def selector_occurrence_summaries(
        self,
        method_name,
        occurrence_type,
    ):
        selector_expression = self.selector_reference_expression(method_name)
        if occurrence_type == 'implementors':
            candidate_value = self.run_code(
                'ClassOrganizer new implementorsOf: %s'
                % selector_expression
            )
        elif occurrence_type == 'senders':
            candidate_value = self.run_code(
                'ClassOrganizer new sendersOf: %s'
                % selector_expression
            )
        else:
            raise DomainException(
                'occurrence_type must be implementors or senders.'
            )
        compiled_methods = self.flatten_compiled_methods(candidate_value)
        method_summaries = [
            self.method_summary(compiled_method)
            for compiled_method in compiled_methods
        ]
        return self.unique_sorted_method_summaries(method_summaries)

    def implementor_entries_from_method_summaries(self, method_summaries):
        implementors = []
        seen_implementor_keys = set()
        for method_summary in method_summaries:
            implementor_key = (
                method_summary['class_name'],
                method_summary['show_instance_side'],
            )
            has_seen_implementor = implementor_key in seen_implementor_keys
            if not has_seen_implementor:
                implementors.append(
                    {
                        'class_name': method_summary['class_name'],
                        'show_instance_side': method_summary[
                            'show_instance_side'
                        ],
                    }
                )
                seen_implementor_keys.add(implementor_key)
        return sorted(
            implementors,
            key=lambda implementor: (
                implementor['class_name'],
                implementor['show_instance_side'],
            ),
        )

    def unique_sorted_method_summaries(self, method_summaries):
        unique_summaries = []
        seen_keys = set()
        for method_summary in method_summaries:
            method_key = (
                method_summary['class_name'],
                method_summary['show_instance_side'],
                method_summary['method_selector'],
            )
            has_seen_summary = method_key in seen_keys
            if not has_seen_summary:
                unique_summaries.append(method_summary)
                seen_keys.add(method_key)
        return sorted(
            unique_summaries,
            key=lambda method_summary: (
                method_summary['class_name'],
                method_summary['show_instance_side'],
                method_summary['method_selector'],
            ),
        )

    def method_summary(self, compiled_method):
        selector = compiled_method.selector().to_py
        in_class = compiled_method.inClass()
        show_instance_side = not in_class.isMeta().to_py
        in_class_name = in_class.name().to_py
        class_name = (
            in_class_name[:-6]
            if not show_instance_side and in_class_name.endswith(' class')
            else in_class_name
        )
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'method_selector': selector,
        }

    def limited_entries(self, entries, max_results):
        if max_results is None:
            return entries
        return entries[:max_results]

    def validated_show_instance_side(self, show_instance_side):
        if isinstance(show_instance_side, bool):
            return show_instance_side
        if isinstance(show_instance_side, str):
            normalized_show_instance_side = show_instance_side.strip().lower()
            if normalized_show_instance_side == 'true':
                return True
            if normalized_show_instance_side == 'false':
                return False
        raise DomainException('show_instance_side must be a boolean.')

    def validated_boolean_flag(self, flag_value, argument_name):
        if isinstance(flag_value, bool):
            return flag_value
        if isinstance(flag_value, str):
            normalized_flag_value = flag_value.strip().lower()
            if normalized_flag_value == 'true':
                return True
            if normalized_flag_value == 'false':
                return False
        raise DomainException('%s must be a boolean.' % argument_name)

    def class_to_query(self, class_name, show_instance_side):
        show_instance_side = self.validated_show_instance_side(
            show_instance_side
        )
        gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        return gemstone_class if show_instance_side else gemstone_class.gemstone_class()

    def all_class_names(self):
        return [
            gemstone_name.value().to_py
            for gemstone_name in self.class_organizer.classNames()
        ]

    def matching_selector_names_for_class(
        self,
        class_name,
        search_input,
    ):
        selector_names = self.selectors_for_class_side(class_name, True)
        selector_names += self.selectors_for_class_side(class_name, False)
        return [
            selector_name
            for selector_name in selector_names
            if search_input.lower() in selector_name.lower()
        ]

    def selectors_for_class_side(
        self,
        class_name,
        show_instance_side,
    ):
        selector_names = []
        gemstone_class = self.resolved_class(class_name)
        if gemstone_class:
            class_to_query = (
                gemstone_class if show_instance_side else gemstone_class.gemstone_class()
            )
            selector_names = self.sorted_selectors(class_to_query)
        return selector_names

    def resolved_class(self, class_name):
        gemstone_class = None
        try:
            gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        except GemstoneError:
            gemstone_class = None
        except GemstoneApiError:
            gemstone_class = None
        return gemstone_class

    def sorted_selectors(self, class_to_query):
        selector_names = []
        try:
            selector_names = [
                gemstone_selector.to_py
                for gemstone_selector in class_to_query.selectors().asSortedCollection()
            ]
        except GemstoneError:
            selector_names = []
        except GemstoneApiError:
            selector_names = []
        return selector_names


def list_packages(gemstone_session):
    return GemstoneBrowserSession(gemstone_session).list_packages()


def list_classes(gemstone_session, package_name):
    return GemstoneBrowserSession(gemstone_session).list_classes(package_name)


def list_method_categories(gemstone_session, class_name, show_instance_side):
    return GemstoneBrowserSession(gemstone_session).list_method_categories(
        class_name,
        show_instance_side,
    )


def list_methods(
    gemstone_session,
    class_name,
    method_category,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).list_methods(
        class_name,
        method_category,
        show_instance_side,
    )


def get_method_source(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).get_method_source(
        class_name,
        method_selector,
        show_instance_side,
    )


def find_classes(gemstone_session, search_input):
    return GemstoneBrowserSession(gemstone_session).find_classes(search_input)


def find_selectors(gemstone_session, search_input):
    return GemstoneBrowserSession(gemstone_session).find_selectors(search_input)


def find_implementors(gemstone_session, method_name):
    return GemstoneBrowserSession(gemstone_session).find_implementors(method_name)


def find_senders(gemstone_session, method_name):
    return GemstoneBrowserSession(gemstone_session).find_senders(method_name)


def method_sends(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).method_sends(
        class_name,
        method_selector,
        show_instance_side,
    )


def method_structure_summary(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).method_structure_summary(
        class_name,
        method_selector,
        show_instance_side,
    )


def method_control_flow_summary(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).method_control_flow_summary(
        class_name,
        method_selector,
        show_instance_side,
    )


def query_methods_by_ast_pattern(
    gemstone_session,
    ast_pattern,
    package_name,
    class_name,
    show_instance_side,
    method_category,
    max_results,
    sort_by='scan_order',
    sort_descending=False,
):
    return GemstoneBrowserSession(gemstone_session).query_methods_by_ast_pattern(
        ast_pattern,
        package_name=package_name,
        class_name=class_name,
        show_instance_side=show_instance_side,
        method_category=method_category,
        max_results=max_results,
        sort_by=sort_by,
        sort_descending=sort_descending,
    )


def method_ast(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    return GemstoneBrowserSession(gemstone_session).method_ast(
        class_name,
        method_selector,
        show_instance_side,
    )
