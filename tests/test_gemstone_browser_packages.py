from reahl.tofu import Fixture
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class NameProxy:
    def __init__(self, value):
        self.to_py = value


class BooleanProxy:
    def __init__(self, value):
        self.to_py = value


class SymbolDictionaryStub:
    def __init__(self, package_name):
        self.package_name = package_name

    def name(self):
        return NameProxy(self.package_name)

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
    def __init__(self, classes_by_package):
        self.classes_by_package = classes_by_package

    def keys(self):
        return [NameProxy(package_name) for package_name in self.classes_by_package]

    def at(self, package_name):
        return self.classes_by_package[package_name]


class ClassOrganizerStub:
    def __init__(self, classes_by_package):
        self.classes_by_package = classes_by_package

    def categories(self):
        return CategoriesStub(self.classes_by_package)


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


class BrowserPackagesFixture(Fixture):
    def new_browser_session(self):
        return StubbedClassOrganizerBrowserSession(
            {
                'Kernel': [
                    GemstoneClassStub('Object'),
                    GemstoneClassStub('Behavior'),
                ]
            },
            [
                'Stuff',
                'Wonka-thing',
            ],
            {
                'Stuff': [NonClassEntryStub('Stuff')],
                'Wonka-thing': [
                    GemstoneClassStub('WonkaThingTest'),
                    NonClassEntryStub('Wonka-thing'),
                ],
            },
        )


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_returns_empty_for_unknown_package(browser_packages_fixture):
    """AI: Listing classes for a package without a class organizer entry should return an empty list."""
    assert browser_packages_fixture.browser_session.list_classes('Nope') == []


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_returns_class_names_for_known_package(browser_packages_fixture):
    """AI: Listing classes for a known package should still return that package's class names."""
    assert browser_packages_fixture.browser_session.list_classes('Kernel') == [
        'Behavior',
        'Object',
    ]


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_includes_classes_from_package_dictionary(browser_packages_fixture):
    """AI: Listing classes should include classes present in the package dictionary even when class categories have no key for that package."""
    assert browser_packages_fixture.browser_session.list_classes('Wonka-thing') == [
        'WonkaThingTest',
    ]


@with_fixtures(BrowserPackagesFixture)
def test_list_packages_includes_empty_installed_package(browser_packages_fixture):
    """AI: Package listing should include installed package names even before any class is created in that package."""
    assert 'Wonka-thing' in browser_packages_fixture.browser_session.list_packages()
