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

    def compile_method(self, class_name, show_instance_side, source):
        class_to_query = self.class_to_query(class_name, show_instance_side)
        symbol_list = self.gemstone_session.execute('System myUserProfile symbolList')
        return class_to_query.compileMethod_dictionaries_category_environmentId(
            source,
            symbol_list,
            'as yet unclassified',
            0,
        )

    def run_code(self, source):
        return self.gemstone_session.execute(source)

    def evaluate_source(self, source):
        result = self.run_code(source)
        return {
            'result': render_result(result),
        }

    def run_gemstone_tests(self, test_case_class_name):
        test_case_class = self.gemstone_session.resolve_symbol(test_case_class_name)
        test_suite = test_case_class.suite()
        test_result = test_suite.run()
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
        implementors = []
        class_names = self.all_class_names()
        for class_name in class_names:
            instance_side_selectors = self.selectors_for_class_side(
                class_name,
                True,
            )
            if method_name in instance_side_selectors:
                implementors.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': True,
                    }
                )
            class_side_selectors = self.selectors_for_class_side(
                class_name,
                False,
            )
            if method_name in class_side_selectors:
                implementors.append(
                    {
                        'class_name': class_name,
                        'show_instance_side': False,
                    }
                )
        return sorted(
            implementors,
            key=lambda implementor: (
                implementor['class_name'],
                implementor['show_instance_side'],
            ),
        )

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
