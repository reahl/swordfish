from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class NameProxy:
    def __init__(self, value):
        self.to_py = value


class RecordingListingBrowserSession(GemstoneBrowserSession):
    """AI: Stubs run_code at the GCI boundary with a canned lf-joined reply (the shape the
    server-side join produces) and records every executed source, so tests can assert both
    the parsed result and that a listing costs exactly one server round trip."""

    def __init__(self, joined_reply=""):
        super().__init__(None)
        self.joined_reply = joined_reply
        self.executed_sources = []

    def run_code(self, source):
        self.executed_sources.append(source)
        return NameProxy(self.joined_reply)


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
            return NameProxy("\n".join(self.dictionary_names))
        dictionary_literal = source.split("dictionaryName := ")[1].split(".\n", 1)[0]
        dictionary_name = self.smalltalk_string_value(dictionary_literal)
        class_names = self.class_names_by_dictionary.get(dictionary_name, [])
        return NameProxy("\n".join(class_names))


class SourceCapturingBrowserSession(GemstoneBrowserSession):
    def __init__(self):
        super().__init__(None)
        self.last_source = None

    def run_code(self, source):
        self.last_source = source
        return source


class BrowserListingFixture(Fixture):
    def new_browser_session(self):
        return RecordingListingBrowserSession()


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


@with_fixtures(BrowserListingFixture)
def test_list_classes_in_category_returns_empty_for_unknown_category(
    browser_listing_fixture,
):
    """AI: Listing classes for a missing category should return an empty list: the server
    program answers an empty string via at:ifAbsent: rather than raising."""
    browser_session = browser_listing_fixture.browser_session
    assert browser_session.list_classes_in_category("Nope") == []
    assert "ifAbsent:" in browser_session.executed_sources[0]


@with_fixtures(BrowserListingFixture)
def test_list_classes_in_category_returns_sorted_class_names_for_known_category(
    browser_listing_fixture,
):
    """AI: Listing classes for a known category should return that category's class names,
    sorted, regardless of the order the server emits them in."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.joined_reply = "Object\nBehavior"
    assert browser_session.list_classes_in_category("Kernel") == [
        "Behavior",
        "Object",
    ]


@with_fixtures(BrowserListingFixture)
def test_class_listings_consult_class_organizer_not_package_library(
    browser_listing_fixture,
):
    """AI: Category class listing must come from ClassOrganizer's categories only; classes
    discovered via package dictionaries (GsPackageLibrary) do not belong in it."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.list_classes_in_category("Acme-thing")
    executed_source = browser_session.executed_sources[0]
    assert "ClassOrganizer new categories" in executed_source
    assert "GsPackageLibrary" not in executed_source


@with_fixtures(BrowserListingFixture)
def test_list_categories_only_returns_class_organizer_categories(
    browser_listing_fixture,
):
    """AI: Category listing should only return categories from ClassOrganizer."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.joined_reply = "Kernel"
    assert browser_session.list_categories() == ["Kernel"]
    executed_source = browser_session.executed_sources[0]
    assert "ClassOrganizer new categories" in executed_source
    assert "GsPackageLibrary" not in executed_source


@with_fixtures(BrowserListingFixture)
def test_list_method_categories_prepends_the_all_pseudo_category(
    browser_listing_fixture,
):
    """AI: The 'all' pseudo-category is an IDE concept, prepended client-side; the server
    only reports the class's real protocol names."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.joined_reply = "accessing\ntesting"
    assert browser_session.list_method_categories("Order", True) == [
        "all",
        "accessing",
        "testing",
    ]


@with_fixtures(BrowserListingFixture)
def test_method_listings_address_the_class_side_when_asked(browser_listing_fixture):
    """AI: Listing for the class side must query the metaclass: the server expression
    addresses '<class> class', not the class itself."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.list_method_categories("Order", False)
    assert " class " in browser_session.executed_sources[0]
    browser_session.list_methods("Order", "all", False)
    assert " class " in browser_session.executed_sources[1]


@with_fixtures(BrowserListingFixture)
def test_list_methods_for_all_lists_every_selector(browser_listing_fixture):
    """AI: The 'all' pseudo-category lists the selectors of every protocol of the class."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.joined_reply = "total\ndescription"
    assert browser_session.list_methods("Order", "all", True) == [
        "total",
        "description",
    ]
    assert "selectors" in browser_session.executed_sources[0]
    assert "selectorsIn:" not in browser_session.executed_sources[0]


@with_fixtures(BrowserListingFixture)
def test_list_methods_for_a_real_category_queries_that_category(
    browser_listing_fixture,
):
    """AI: A real protocol name restricts the listing to that protocol's selectors."""
    browser_session = browser_listing_fixture.browser_session
    browser_session.joined_reply = "total"
    assert browser_session.list_methods("Order", "accessing", True) == ["total"]
    executed_source = browser_session.executed_sources[0]
    assert "selectorsIn:" in executed_source
    assert "'accessing'" in executed_source


class ListingCallScenarios(Fixture):
    @scenario
    def categories(self):
        """AI: Listing all class categories of the image."""
        self.make_listing_call = lambda browser_session: browser_session.list_categories()

    @scenario
    def classes_in_category(self):
        """AI: Listing the classes of one category."""
        self.make_listing_call = lambda browser_session: (
            browser_session.list_classes_in_category("Kernel")
        )

    @scenario
    def dictionaries(self):
        """AI: Listing the symbol dictionaries of the user."""
        self.make_listing_call = lambda browser_session: (
            browser_session.list_dictionaries()
        )

    @scenario
    def classes_in_dictionary(self):
        """AI: Listing the classes of one symbol dictionary."""
        self.make_listing_call = lambda browser_session: (
            browser_session.list_classes_in_dictionary("UserGlobals")
        )

    @scenario
    def method_categories(self):
        """AI: Listing the protocols of a class."""
        self.make_listing_call = lambda browser_session: (
            browser_session.list_method_categories("Order", True)
        )

    @scenario
    def methods(self):
        """AI: Listing the selectors of a protocol."""
        self.make_listing_call = lambda browser_session: (
            browser_session.list_methods("Order", "all", True)
        )


@with_fixtures(BrowserListingFixture, ListingCallScenarios)
def test_browsing_listings_cost_one_round_trip(browser_listing_fixture, scenario):
    """AI: Every browsing listing must transfer its names as one lf-joined string in a
    single server round trip. Per-element proxy fetches make UI latency scale with the
    size of the package or class being browsed (hundreds of round trips for Kernel)."""
    browser_session = browser_listing_fixture.browser_session
    scenario.make_listing_call(browser_session)
    assert len(browser_session.executed_sources) == 1
    assert "(String with: Character lf) join:" in browser_session.executed_sources[0]


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
