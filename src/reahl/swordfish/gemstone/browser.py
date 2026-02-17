import re

from reahl.ptongue import GemstoneApiError
from reahl.ptongue import GemstoneError

from reahl.swordfish.gemstone.session import DomainException


def list_packages(gemstone_session):
    class_organizer = gemstone_session.ClassOrganizer.new()
    return [
        gemstone_package.to_py
        for gemstone_package in class_organizer.categories().keys().asSortedCollection()
    ]


def list_classes(gemstone_session, package_name):
    if not package_name:
        return []
    class_organizer = gemstone_session.ClassOrganizer.new()
    gemstone_classes = class_organizer.categories().at(package_name)
    return [gemstone_class.name().to_py for gemstone_class in gemstone_classes]


def list_method_categories(gemstone_session, class_name, show_instance_side):
    if not class_name:
        return []
    class_to_query = get_class_to_query(
        gemstone_session,
        class_name,
        show_instance_side,
    )
    categories = [
        gemstone_category.to_py
        for gemstone_category in class_to_query.categoryNames().asSortedCollection()
    ]
    return ['all'] + categories


def list_methods(
    gemstone_session,
    class_name,
    method_category,
    show_instance_side,
):
    if not class_name or not method_category:
        return []
    class_to_query = get_class_to_query(
        gemstone_session,
        class_name,
        show_instance_side,
    )
    if method_category == 'all':
        selectors = class_to_query.selectors().asSortedCollection()
    else:
        selectors = class_to_query.selectorsIn(method_category).asSortedCollection()
    return [gemstone_selector.to_py for gemstone_selector in selectors]


def get_method_source(
    gemstone_session,
    class_name,
    method_selector,
    show_instance_side,
):
    class_to_query = get_class_to_query(
        gemstone_session,
        class_name,
        show_instance_side,
    )
    compiled_method = class_to_query.compiledMethodAt(method_selector)
    return compiled_method.sourceString().to_py


def find_classes(gemstone_session, search_input):
    class_organizer = gemstone_session.ClassOrganizer.new()
    try:
        pattern = re.compile(search_input, re.IGNORECASE)
    except re.error as error:
        raise DomainException('Invalid search pattern: %s' % error)
    return [
        class_name
        for class_name in [gemstone_name.value().to_py for gemstone_name in class_organizer.classNames()]
        if pattern.search(class_name)
    ]


def find_selectors(gemstone_session, search_input):
    selector_matches = set()
    class_names = get_all_class_names(gemstone_session)
    for class_name in class_names:
        matching_names = get_matching_selector_names_for_class(
            gemstone_session,
            class_name,
            search_input,
        )
        selector_matches.update(matching_names)
    return sorted(selector_matches)


def find_implementors(gemstone_session, method_name):
    implementors = []
    class_names = get_all_class_names(gemstone_session)
    for class_name in class_names:
        instance_side_selectors = get_selectors_for_class_side(
            gemstone_session,
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
        class_side_selectors = get_selectors_for_class_side(
            gemstone_session,
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


def get_class_to_query(gemstone_session, class_name, show_instance_side):
    gemstone_class = gemstone_session.resolve_symbol(class_name)
    return gemstone_class if show_instance_side else gemstone_class.gemstone_class()


def get_all_class_names(gemstone_session):
    class_organizer = gemstone_session.ClassOrganizer.new()
    return [
        gemstone_name.value().to_py
        for gemstone_name in class_organizer.classNames()
    ]


def get_matching_selector_names_for_class(
    gemstone_session,
    class_name,
    search_input,
):
    selector_names = get_selectors_for_class_side(
        gemstone_session,
        class_name,
        True,
    )
    selector_names += get_selectors_for_class_side(
        gemstone_session,
        class_name,
        False,
    )
    return [
        selector_name
        for selector_name in selector_names
        if search_input.lower() in selector_name.lower()
    ]


def get_selectors_for_class_side(
    gemstone_session,
    class_name,
    show_instance_side,
):
    selector_names = []
    gemstone_class = get_resolved_class(gemstone_session, class_name)
    if gemstone_class:
        class_to_query = (
            gemstone_class if show_instance_side else gemstone_class.gemstone_class()
        )
        selector_names = get_sorted_selectors(class_to_query)
    return selector_names


def get_resolved_class(gemstone_session, class_name):
    gemstone_class = None
    try:
        gemstone_class = gemstone_session.resolve_symbol(class_name)
    except GemstoneError:
        gemstone_class = None
    except GemstoneApiError:
        gemstone_class = None
    return gemstone_class


def get_sorted_selectors(class_to_query):
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
