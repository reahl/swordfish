from reahl.ptongue import GemstoneError
from reahl.stubble import stubclass
from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession


class ResolvedBoolean:
    """AI: parseltongue answers Smalltalk sends with GemObjects whose .to_py yields the
    Python value; existing_class_named reads .to_py off the isBehavior answer."""

    def __init__(self, value):
        self.to_py = value


class ResolvedClassObject:
    """AI: Stands in for a resolved GemStone object. isBehavior reports whether it is a
    class/Behavior - exactly the send existing_class_named uses to tell a real class
    from a defined-but-non-class global."""

    def __init__(self, is_behavior):
        self.is_behavior = is_behavior

    def perform(self, selector):
        assert selector == 'isBehavior'
        return ResolvedBoolean(self.is_behavior)


class PhantomObject:
    """AI: Stands in for resolve_symbol's answer to an undefined name - a phantom on the
    illegal OOP. It resolves truthily but every send to it fails, which is the real
    cause of the 'object with object ID 1 does not exist' error on opening the result."""

    def perform(self, selector):
        raise GemstoneError(None, None)


@stubclass(GemstoneBrowserSession)
class ResolvingClassSession(GemstoneBrowserSession):
    """AI: Stubs the two GemStone-side leaves an exact lookup could reach - the symbol
    resolve and the full class-name scan - so a test can prove the exact path answers
    from resolving and confirming the class, and never falls back to scanning."""

    resolved_objects = {}
    scan_was_called = False

    def resolved_class(self, class_name):
        return self.resolved_objects.get(class_name)

    def all_class_names(self):
        self.scan_was_called = True
        return list(self.resolved_objects.keys())


class ExactClassFixture(Fixture):
    def browser_session_resolving(self, resolved_objects):
        session = ResolvingClassSession(None)
        session.resolved_objects = resolved_objects
        return session


class ExactClassScenarios(Fixture):
    @scenario
    def name_is_a_real_class(self):
        """AI: A name that resolves to a Behavior is a genuine class - the one case that
        yields a match."""
        self.resolved_objects = {'Account': ResolvedClassObject(is_behavior=True)}
        self.query = 'Account'
        self.expected_matches = ['Account']

    @scenario
    def name_is_undefined(self):
        """AI: An undefined name resolves to a phantom whose sends fail; it must not be
        reported as a match (the Broker bug)."""
        self.resolved_objects = {'Broker': PhantomObject()}
        self.query = 'Broker'
        self.expected_matches = []

    @scenario
    def name_is_a_non_class_global(self):
        """AI: A defined global that is not a Behavior (e.g. a SymbolDictionary) is not a
        class and must not be reported as a match."""
        self.resolved_objects = {'Globals': ResolvedClassObject(is_behavior=False)}
        self.query = 'Globals'
        self.expected_matches = []

    @scenario
    def name_does_not_resolve(self):
        """AI: When resolution itself yields nothing, there is no match."""
        self.resolved_objects = {}
        self.query = 'Nope'
        self.expected_matches = []


@with_fixtures(ExactClassFixture, ExactClassScenarios)
def test_exact_class_lookup_matches_only_real_classes_without_scanning(fixture, scenario):
    """AI: An exact class search only needs an O(1) symbol resolve plus a class-ness
    check - the same primitive Browse Class uses - so it matches only names that resolve
    to a real class, never reports phantom or non-class globals, and never falls back to
    scanning every class name in the image."""
    session = fixture.browser_session_resolving(scenario.resolved_objects)

    matches = session.existing_class_named(scenario.query)

    assert matches == scenario.expected_matches
    assert session.scan_was_called is False
