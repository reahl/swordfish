import re

from reahl.ptongue import GemstoneApiError
from reahl.ptongue import GemstoneError

from reahl.swordfish.gemstone.session import DomainException
from reahl.swordfish.gemstone.session import render_result


class GemstoneBrowserSession:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session

    @property
    def class_organizer(self):
        return self.gemstone_session.ClassOrganizer.new()

    def list_packages(self):
        return [
            gemstone_package.to_py
            for gemstone_package in self.class_organizer.categories().keys().asSortedCollection()
        ]

    def list_classes(self, package_name):
        if not package_name:
            return []
        gemstone_classes = self.class_organizer.categories().at(package_name)
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
            in_dictionary,
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

    def selector_rename_preview(self, old_selector, new_selector):
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
        return [
            keyword + ':'
            for keyword in selector.split(':')
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

    def class_to_query(self, class_name, show_instance_side):
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
