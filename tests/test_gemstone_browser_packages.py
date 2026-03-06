from reahl.tofu import Fixture, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class NameProxy:
    def __init__(self, value):
        self.to_py = value


class BooleanProxy:
    def __init__(self, value):
        self.to_py = value


class SymbolDictionaryStub:
    def __init__(self, dictionary_name):
        self.dictionary_name = dictionary_name

    def name(self):
        return NameProxy(self.dictionary_name)

    def isBehavior(self):
        return BooleanProxy(False)


class GemstoneClassStub:
    def __init__(self, class_name):
        self.class_name = class_name

    def name(self):
        return NameProxy(self.class_name)

    def isBehavior(self):
        return BooleanProxy(True)


class NonClassEntryStub:
    def __init__(self, name):
        self.name_value = name

    def name(self):
        return NameProxy(self.name_value)

    def isBehavior(self):
        return BooleanProxy(False)


class CategoriesStub:
    def __init__(self, classes_by_category):
        self.classes_by_category = classes_by_category

    def keys(self):
        return [NameProxy(category_name) for category_name in self.classes_by_category]

    def at(self, category_name):
        return self.classes_by_category[category_name]


class ClassOrganizerStub:
    def __init__(self, classes_by_category):
        self.classes_by_category = classes_by_category

    def categories(self):
        return CategoriesStub(self.classes_by_category)


class PackageLibraryStub:
    def __init__(self, package_entries, classes_by_package):
        self.package_entries = [
            SymbolDictionaryStub(package_name) for package_name in package_entries
        ]
        self.classes_by_package = classes_by_package

    def __iter__(self):
        return iter(self.package_entries)

    def objectNamed(self, package_name):
        return self.classes_by_package[package_name]


class StubbedClassOrganizerBrowserSession(GemstoneBrowserSession):
    def __init__(
        self,
        classes_by_package,
        package_library_names,
        package_dictionary_entries_by_package,
    ):
        super().__init__(None)
        self.organizer = ClassOrganizerStub(classes_by_package)
        self.library_entries = PackageLibraryStub(
            package_library_names,
            package_dictionary_entries_by_package,
        )

    @property
    def class_organizer(self):
        return self.organizer

    @property
    def package_library(self):
        return self.library_entries


class StubbedDictionaryBrowserSession(GemstoneBrowserSession):
    def __init__(self, dictionary_names, class_names_by_dictionary):
        super().__init__(None)
        self.dictionary_names = dictionary_names
        self.class_names_by_dictionary = class_names_by_dictionary
        self.executed_sources = []

    def smalltalk_string_value(self, smalltalk_literal):
        return smalltalk_literal[1:-1].replace("''", "'")

    def run_code(self, source):
        self.executed_sources.append(source)
        if "System myUserProfile symbolList do:" in source:
            return [NameProxy(name) for name in self.dictionary_names]
        dictionary_literal = source.split("dictionaryName := ")[1].split(".\n", 1)[0]
        dictionary_name = self.smalltalk_string_value(dictionary_literal)
        class_names = self.class_names_by_dictionary.get(dictionary_name, [])
        return [NameProxy(class_name) for class_name in class_names]


class SourceCapturingBrowserSession(GemstoneBrowserSession):
    def __init__(self):
        super().__init__(None)
        self.last_source = None

    def run_code(self, source):
        self.last_source = source
        return source


class BrowserPackagesFixture(Fixture):
    def new_browser_session(self):
        return StubbedClassOrganizerBrowserSession(
            {
                "Kernel": [
                    GemstoneClassStub("Object"),
                    GemstoneClassStub("Behavior"),
                ]
            },
            [
                "Stuff",
                "Wonka-thing",
            ],
            {
                "Stuff": [NonClassEntryStub("Stuff")],
                "Wonka-thing": [
                    GemstoneClassStub("WonkaThingTest"),
                    NonClassEntryStub("Wonka-thing"),
                ],
            },
        )


class BrowserDictionariesFixture(Fixture):
    def new_browser_session(self):
        return StubbedDictionaryBrowserSession(
            ["SessionGlobals", "UserGlobals"],
            {
                "UserGlobals": [
                    "Behavior",
                    "Object",
                ],
                "SessionGlobals": [
                    "SessionThing",
                ],
            },
        )


class BrowserSourceCaptureFixture(Fixture):
    def new_browser_session(self):
        return SourceCapturingBrowserSession()


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_in_category_returns_empty_for_unknown_category(
    browser_packages_fixture,
):
    """AI: Listing classes for a missing category should return an empty list."""
    assert (
        browser_packages_fixture.browser_session.list_classes_in_category("Nope") == []
    )


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_in_category_returns_class_names_for_known_category(
    browser_packages_fixture,
):
    """AI: Listing classes for a known category should return that category's class names."""
    assert browser_packages_fixture.browser_session.list_classes_in_category(
        "Kernel"
    ) == [
        "Behavior",
        "Object",
    ]


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_in_category_ignores_package_library_entries(
    browser_packages_fixture,
):
    """AI: Category class listing should not include classes discovered only from package dictionaries."""
    assert (
        browser_packages_fixture.browser_session.list_classes_in_category("Wonka-thing")
        == []
    )


@with_fixtures(BrowserPackagesFixture)
def test_list_categories_only_returns_class_organizer_categories(
    browser_packages_fixture,
):
    """AI: Category listing should only return categories from ClassOrganizer."""
    assert browser_packages_fixture.browser_session.list_categories() == ["Kernel"]


@with_fixtures(BrowserDictionariesFixture)
def test_list_dictionaries_returns_names_from_symbol_list(browser_dictionaries_fixture):
    """AI: Dictionary listing should come from the user's symbolList names."""
    assert browser_dictionaries_fixture.browser_session.list_dictionaries() == [
        "SessionGlobals",
        "UserGlobals",
    ]


@with_fixtures(BrowserDictionariesFixture)
def test_list_classes_in_dictionary_returns_dictionary_class_names(
    browser_dictionaries_fixture,
):
    """AI: Dictionary class listing should include only classes from the selected dictionary."""
    assert browser_dictionaries_fixture.browser_session.list_classes_in_dictionary(
        "UserGlobals"
    ) == ["Behavior", "Object"]


@with_fixtures(BrowserSourceCaptureFixture)
def test_dictionary_reference_expression_uses_symbol_list_lookup_for_non_identifier(
    browser_source_capture_fixture,
):
    """AI: Non-identifier dictionary names should be resolved from symbolList, not packageLibrary."""
    expression = (
        browser_source_capture_fixture.browser_session.dictionary_reference_expression(
            "My Dict",
        )
    )
    assert "System myUserProfile symbolList objectNamed:" in expression
    assert "GsPackageLibrary packageLibrary objectNamed:" not in expression


@with_fixtures(BrowserSourceCaptureFixture)
def test_create_dictionary_uses_symbol_list_and_symbol_dictionary(
    browser_source_capture_fixture,
):
    """AI: Creating a dictionary should allocate a SymbolDictionary and add it to the symbolList."""
    browser_source_capture_fixture.browser_session.create_dictionary("BuildSpace")
    source = browser_source_capture_fixture.browser_session.last_source
    assert "System myUserProfile symbolList" in source
    assert "SymbolDictionary new" in source
    assert "name: " in source


@with_fixtures(BrowserSourceCaptureFixture)
def test_assign_class_to_package_classifies_class_under_package(
    browser_source_capture_fixture,
):
    """AI: Assigning a class to package should classify the class under that package name."""
    browser_source_capture_fixture.browser_session.assign_class_to_package(
        "OrderLine",
        "Kernel",
    )
    source = browser_source_capture_fixture.browser_session.last_source
    assert "ClassOrganizer new classify:" in source
    assert "under: packageName" in source
