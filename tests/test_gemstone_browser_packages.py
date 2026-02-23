from reahl.tofu import Fixture
from reahl.tofu import with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class NameProxy:
    def __init__(self, value):
        self.to_py = value


class SymbolDictionaryStub:
    def __init__(self, package_name):
        self.package_name = package_name

    def name(self):
        return NameProxy(self.package_name)


class GemstoneClassStub:
    def __init__(self, class_name):
        self.class_name = class_name

    def name(self):
        return NameProxy(self.class_name)


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


class StubbedClassOrganizerBrowserSession(GemstoneBrowserSession):
    def __init__(self, classes_by_package, package_library_names):
        super().__init__(None)
        self.organizer = ClassOrganizerStub(classes_by_package)
        self.library_entries = [
            SymbolDictionaryStub(package_name)
            for package_name in package_library_names
        ]

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
        )


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_returns_empty_for_missing_package(browser_packages_fixture):
    """AI: Listing classes for a package without a class organizer entry should return an empty list."""
    assert browser_packages_fixture.browser_session.list_classes('Wonka-thing') == []


@with_fixtures(BrowserPackagesFixture)
def test_list_classes_returns_class_names_for_known_package(browser_packages_fixture):
    """AI: Listing classes for a known package should still return that package's class names."""
    assert browser_packages_fixture.browser_session.list_classes('Kernel') == [
        'Object',
        'Behavior',
    ]


@with_fixtures(BrowserPackagesFixture)
def test_list_packages_includes_empty_installed_package(browser_packages_fixture):
    """AI: Package listing should include installed package names even before any class is created in that package."""
    assert 'Wonka-thing' in browser_packages_fixture.browser_session.list_packages()
