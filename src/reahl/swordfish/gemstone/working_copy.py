'''AI: The in-image code tracked against an on-disk Monticello FileTree repository.

A MonticelloWorkingCopy decides, for each edit made in the GemStone image, which on-disk
file (if any) should reflect it, and writes it through a MonticelloRepository. Its
configuration - which repository it mirrors to, and whether mirroring is on - is shared
between the swordfish IDE and the MCP server through a small JSON file, so a change made in
either surface is honoured by the other.'''

import json
import os

from reahl.swordfish.gemstone.filetree_sync import MonticelloRepository

DEFAULT_CONFIG_RELATIVE_PATH = os.path.join('.config', 'swordfish', 'filetree_sync.json')


def sync_config_path():
    '''AI: Where the shared sync configuration lives. Overridable via environment variable so
    that the IDE, the MCP server, and tests can agree on (or isolate) the location.'''
    override = os.environ.get('SWORDFISH_FILETREE_SYNC_CONFIG')
    if override:
        return override
    return os.path.join(os.path.expanduser('~'), DEFAULT_CONFIG_RELATIVE_PATH)


class MethodTarget:
    '''AI: The on-disk destination of a method: which package, whether it is an extension,
    and the protocol/category line that belongs on the first line of the file.'''

    def __init__(self, package_name, is_extension, category_line):
        self.package_name = package_name
        self.is_extension = is_extension
        self.category_line = category_line


class SyncOutcome:
    '''AI: What mirroring a single edit did, so the caller can report it to the user.'''

    def __init__(self, action, path=None, drift=None):
        self.action = action
        self.path = path
        self.drift = drift

    def report(self):
        if self.action in ('disabled', 'skipped') and not self.drift:
            return None
        pieces = []
        if self.action == 'wrote':
            pieces.append('Mirrored to %s' % self.path)
        if self.action == 'removed':
            pieces.append('Removed mirrored file')
        if self.drift:
            pieces.append(self.drift)
        return ' '.join(pieces) if pieces else None


class MonticelloWorkingCopy:
    def __init__(self, repository=None, enabled=False):
        self.repository = repository
        self.enabled = enabled

    @property
    def active(self):
        return self.enabled and self.repository is not None

    def target_for_method(self, protocol, class_category):
        '''AI: Resolve where a method belongs. An extension protocol ('*Package') routes the
        method into that package's .extension directory with a canonical '*Package' category
        line - unless the named package is the class's own defining package, in which case the
        star protocol is not an extension and the method stays in the class directory carrying
        that star category line. Otherwise the method lives with the package owning its class.'''
        if protocol.startswith('*'):
            package_name = self.repository.package_for_extension_protocol(protocol)
            if package_name is None:
                return None
            if self.names_own_package(package_name, class_category):
                return MethodTarget(package_name, False, protocol)
            return MethodTarget(package_name, True, '*' + package_name)
        package_name = self.repository.package_owning_category(class_category)
        if package_name is None:
            return None
        return MethodTarget(package_name, False, protocol)

    def names_own_package(self, package_name, class_category):
        '''AI: True when a '*Package' protocol names the very package that already owns the
        class by category. Such a method is not a cross-package extension - Pharo keeps it in
        the class's own directory - so it must not be diverted to a .extension directory.'''
        owning_package = self.repository.package_owning_category(class_category)
        return owning_package is not None and owning_package == package_name

    def update_for_compiled_method(
        self,
        class_name,
        selector,
        on_class_side,
        protocol,
        class_category,
        previous_source,
        new_source,
    ):
        if not self.active:
            return SyncOutcome('disabled')
        target = self.target_for_method(protocol, class_category)
        if target is None:
            return SyncOutcome('skipped')
        drift = self.drift_notice(
            target, class_name, on_class_side, selector, previous_source
        )
        path = self.repository.write_method(
            target.package_name,
            class_name,
            on_class_side,
            target.is_extension,
            selector,
            target.category_line,
            new_source,
        )
        return SyncOutcome('wrote', path=path, drift=drift)

    def drift_notice(self, target, class_name, on_class_side, selector, previous_source):
        '''AI: Report when the file we are about to overwrite no longer matched the image's
        pre-edit source - evidence that disk and image had diverged (e.g. a Pharo-side edit).'''
        if previous_source is None:
            return None
        disk_source = self.repository.disk_method_source(
            target.package_name, class_name, on_class_side, target.is_extension, selector
        )
        if disk_source is None:
            return None
        if disk_source.rstrip('\n') == previous_source.rstrip('\n'):
            return None
        return (
            'Warning: on-disk source for %s>>%s had diverged from the image; overwriting it.'
            % (class_name, selector)
        )

    def update_for_removed_method(
        self, class_name, selector, on_class_side, protocol, class_category
    ):
        if not self.active:
            return SyncOutcome('disabled')
        target = self.target_for_method(protocol, class_category)
        if target is None:
            return SyncOutcome('skipped')
        removed = self.repository.remove_method(
            target.package_name, class_name, on_class_side, target.is_extension, selector
        )
        return SyncOutcome('removed' if removed else 'skipped')

    def remove_stale_after_recategorise(
        self, class_name, selector, on_class_side, old_protocol, new_protocol, class_category
    ):
        '''AI: Recategorising can move a method between a class's own directory and a package
        extension directory. The recompile already wrote the file at the new location, so all
        that remains is to delete the file the method used to occupy when the location changed.'''
        if not self.active:
            return SyncOutcome('disabled')
        old_target = self.target_for_method(old_protocol, class_category)
        if old_target is None:
            return SyncOutcome('skipped')
        old_path = self.repository.method_path(
            old_target.package_name, class_name, on_class_side, old_target.is_extension, selector
        )
        new_path = self.new_method_path(
            new_protocol, class_category, class_name, on_class_side, selector
        )
        if old_path == new_path:
            return SyncOutcome('skipped')
        self.repository.remove_method(
            old_target.package_name, class_name, on_class_side, old_target.is_extension, selector
        )
        return SyncOutcome('removed', path=old_path)

    def new_method_path(self, protocol, class_category, class_name, on_class_side, selector):
        target = self.target_for_method(protocol, class_category)
        if target is None:
            return None
        return self.repository.method_path(
            target.package_name, class_name, on_class_side, target.is_extension, selector
        )

    def update_for_created_class(self, class_definition):
        if not self.active:
            return SyncOutcome('disabled')
        package_name = self.repository.package_owning_category(
            class_definition['category']
        )
        if package_name is None:
            return SyncOutcome('skipped')
        if not self.repository.package_uses_cypress_properties(package_name):
            return SyncOutcome(
                'skipped',
                drift='Package %s does not use the Cypress properties format; '
                'its class definition was not mirrored.' % package_name,
            )
        path = self.repository.write_class_definition(package_name, class_definition)
        return SyncOutcome('wrote', path=path)

    def update_for_removed_class(self, class_name, class_category):
        if not self.active:
            return SyncOutcome('disabled')
        package_name = self.repository.package_owning_category(class_category)
        if package_name is None:
            return SyncOutcome('skipped')
        removed = self.repository.remove_class(package_name, class_name)
        return SyncOutcome('removed' if removed else 'skipped')

    # AI: --- Explicit filing out (image -> disk) -------------------------------------------
    # File-out is an explicit user action, so it works whenever a repository is configured
    # (regardless of the enabled flag) and creates missing packages on disk.

    @property
    def has_repository(self):
        return self.repository is not None

    def engine_class_definition(self, browser_definition):
        '''AI: Translate a GemstoneBrowserSession class definition into the dict the writer
        expects. The class kind is left 'normal'; the writer keeps any real kind already on
        disk.'''
        return {
            'super': browser_definition['superclass_name'],
            'category': browser_definition['package_name'],
            'classinstvars': browser_definition['class_inst_var_names'],
            'pools': browser_definition['pool_dictionary_names'],
            'classvars': browser_definition['class_var_names'],
            'instvars': browser_definition['inst_var_names'],
            'name': browser_definition['class_name'],
            'type': 'normal',
        }

    def ensured_target_for_method(self, protocol, class_category):
        '''AI: Like target_for_method, but for file-out: the destination package is created on
        disk when it does not exist yet, so filing out can introduce new packages. A '*Package'
        protocol that names the class's own defining package is kept in the class directory (not
        an extension), matching how Pharo files it out.'''
        if protocol.startswith('*'):
            existing = self.repository.package_for_extension_protocol(protocol)
            package_name = existing if existing else protocol[1:]
        else:
            existing = self.repository.package_owning_category(class_category)
            package_name = existing if existing else class_category
        if not package_name:
            return None
        self.repository.ensure_package(package_name)
        is_extension = protocol.startswith('*') and not self.names_own_package(
            package_name, class_category
        )
        category_line = ('*' + package_name) if is_extension else protocol
        return MethodTarget(package_name, is_extension, category_line)

    def write_method_for_protocol(
        self, class_name, selector, on_class_side, protocol, class_category, source
    ):
        target = self.ensured_target_for_method(protocol, class_category)
        if target is None:
            return SyncOutcome('skipped')
        path = self.repository.write_method(
            target.package_name,
            class_name,
            on_class_side,
            target.is_extension,
            selector,
            target.category_line,
            source,
        )
        return SyncOutcome('wrote', path=path)

    def file_out_method(self, browser_session, class_name, selector, on_class_side):
        if not self.has_repository:
            return SyncOutcome('skipped')
        show_instance_side = not on_class_side
        protocol = browser_session.get_method_category(
            class_name, selector, show_instance_side
        )
        source = browser_session.get_method_source(
            class_name, selector, show_instance_side
        )
        class_category = browser_session.get_class_definition(class_name)['package_name']
        return self.write_method_for_protocol(
            class_name, selector, on_class_side, protocol, class_category, source
        )

    def file_out_method_category(
        self, browser_session, class_name, method_category, on_class_side
    ):
        if not self.has_repository:
            return SyncOutcome('skipped')
        show_instance_side = not on_class_side
        class_category = browser_session.get_class_definition(class_name)['package_name']
        for selector in browser_session.list_methods(
            class_name, method_category, show_instance_side
        ):
            self.write_one_image_method(
                browser_session, class_name, selector, on_class_side, class_category
            )
        return SyncOutcome('wrote')

    def write_one_image_method(
        self, browser_session, class_name, selector, on_class_side, class_category
    ):
        show_instance_side = not on_class_side
        protocol = browser_session.get_method_category(
            class_name, selector, show_instance_side
        )
        source = browser_session.get_method_source(
            class_name, selector, show_instance_side
        )
        self.write_method_for_protocol(
            class_name, selector, on_class_side, protocol, class_category, source
        )

    def file_out_class(self, browser_session, class_name):
        if not self.has_repository:
            return SyncOutcome('skipped')
        definition = browser_session.get_class_definition(class_name)
        class_category = definition['package_name']
        package_name = (
            self.repository.package_owning_category(class_category) or class_category
        )
        self.repository.ensure_package(package_name)
        self.repository.write_class_definition(
            package_name, self.engine_class_definition(definition)
        )
        for on_class_side in (False, True):
            show_instance_side = not on_class_side
            for selector in browser_session.list_methods(
                class_name, 'all', show_instance_side
            ):
                self.write_one_image_method(
                    browser_session, class_name, selector, on_class_side, class_category
                )
        return SyncOutcome('wrote', path=self.repository.package_directory(package_name))

    def file_out_class_category(self, browser_session, class_category):
        if not self.has_repository:
            return SyncOutcome('skipped')
        for class_name in browser_session.list_classes_in_category(class_category):
            self.file_out_class(browser_session, class_name)
        return SyncOutcome('wrote', path=self.repository.root_path)

    # AI: --- Explicit filing in (disk -> image, full replace) ------------------------------
    # File-in makes the image match disk within the chosen scope: it (re)compiles every method
    # found on disk and DELETES image methods/classes in that scope that are absent from disk.
    # It is destructive, so callers run it inside a transaction the user can abort. The target
    # GemStone symbol dictionary is not recorded in the Pharo FileTree, so it defaults here.

    def file_in_everything(self, browser_session, in_dictionary='UserGlobals'):
        if not self.has_repository:
            return SyncOutcome('skipped')
        for package_name in self.repository.tracked_package_names():
            self.file_in_package(browser_session, package_name, in_dictionary)
        return SyncOutcome('loaded')

    def file_in_class_category(
        self, browser_session, class_category, in_dictionary='UserGlobals'
    ):
        if not self.has_repository:
            return SyncOutcome('skipped')
        package_name = (
            self.repository.package_owning_category(class_category) or class_category
        )
        return self.file_in_package(browser_session, package_name, in_dictionary)

    def file_in_package(self, browser_session, package_name, in_dictionary='UserGlobals'):
        if not self.has_repository:
            return SyncOutcome('skipped')
        disk_class_names = self.repository.defined_class_names(package_name)
        for class_name in disk_class_names:
            self.load_class(browser_session, package_name, class_name, in_dictionary)
        for class_name in self.repository.extension_class_names(package_name):
            for on_class_side in (False, True):
                self.load_methods(
                    browser_session, package_name, class_name, on_class_side, True
                )
        self.delete_image_only_classes(browser_session, package_name, disk_class_names)
        return SyncOutcome('loaded')

    def file_in_named_class(
        self, browser_session, class_name, in_dictionary='UserGlobals'
    ):
        if not self.has_repository:
            return SyncOutcome('skipped')
        package_name = self.package_for_class(browser_session, class_name)
        return self.load_class(browser_session, package_name, class_name, in_dictionary)

    def file_in_method(
        self, browser_session, class_name, selector, on_class_side, in_dictionary='UserGlobals'
    ):
        if not self.has_repository:
            return SyncOutcome('skipped')
        package_name = self.package_for_class(browser_session, class_name)
        stored = self.repository.stored_methods(
            package_name, class_name, False, on_class_side
        )
        match = self.stored_method_for_selector(browser_session, stored, selector)
        if match is None:
            browser_session.delete_method(class_name, selector, not on_class_side)
            return SyncOutcome('removed')
        browser_session.compile_method(
            class_name, not on_class_side, match['source'], match['category']
        )
        return SyncOutcome('loaded')

    def file_in_method_category(
        self,
        browser_session,
        class_name,
        method_category,
        on_class_side,
        in_dictionary='UserGlobals',
    ):
        if not self.has_repository:
            return SyncOutcome('skipped')
        package_name = self.package_for_class(browser_session, class_name)
        is_extension = method_category.startswith('*')
        stored_package, is_extension_dir = self.stored_location_for_protocol(
            method_category, package_name
        )
        stored = self.repository.stored_methods(
            stored_package, class_name, is_extension_dir, on_class_side
        )
        disk_selectors = self.compile_stored_in_protocol(
            browser_session, class_name, on_class_side, method_category, stored
        )
        self.delete_image_methods_outside(
            browser_session, class_name, on_class_side, method_category, disk_selectors
        )
        return SyncOutcome('loaded')

    def load_class(self, browser_session, package_name, class_name, in_dictionary):
        definition = self.repository.read_class_definition(package_name, class_name)
        if definition is None:
            return SyncOutcome('skipped')
        browser_session.create_class(
            class_name=definition['name'],
            superclass_name=definition.get('super') or 'Object',
            inst_var_names=definition.get('instvars', []),
            class_var_names=definition.get('classvars', []),
            class_inst_var_names=definition.get('classinstvars', []),
            pool_dictionary_names=definition.get('pools', []),
            in_dictionary=in_dictionary,
        )
        for on_class_side in (False, True):
            self.load_methods(
                browser_session, package_name, class_name, on_class_side, False
            )
        return SyncOutcome('loaded')

    def load_methods(
        self, browser_session, package_name, class_name, on_class_side, is_extension
    ):
        '''AI: Compile every method stored for a class on a side, then delete the image methods
        in that same scope that are not on disk - making the image match disk.'''
        stored = self.repository.stored_methods(
            package_name, class_name, is_extension, on_class_side
        )
        disk_selectors = set()
        for method in stored:
            selector = browser_session.mirrored_selector(method['source'])
            if selector is not None:
                browser_session.compile_method(
                    class_name, not on_class_side, method['source'], method['category']
                )
                disk_selectors.add(selector)
        self.delete_image_only_methods(
            browser_session, class_name, on_class_side, is_extension, package_name, disk_selectors
        )

    def delete_image_only_methods(
        self, browser_session, class_name, on_class_side, is_extension, package_name, disk_selectors
    ):
        show_instance_side = not on_class_side
        for selector in browser_session.list_methods(class_name, 'all', show_instance_side):
            if selector not in disk_selectors:
                protocol = browser_session.get_method_category(
                    class_name, selector, show_instance_side
                )
                if self.protocol_in_load_scope(protocol, is_extension, package_name):
                    browser_session.delete_method(class_name, selector, show_instance_side)

    def protocol_in_load_scope(self, protocol, is_extension, package_name):
        '''AI: When loading a class's own methods we own the non-extension protocols; when
        loading a package's extensions we own only the '*ThisPackage' protocol. This keeps a
        full-replace from deleting methods that belong to a different package.'''
        if is_extension:
            return protocol.lower() == ('*' + package_name).lower()
        return not protocol.startswith('*')

    def delete_image_only_classes(self, browser_session, package_name, disk_class_names):
        on_disk = set(disk_class_names)
        for class_name in browser_session.list_classes_in_category(package_name):
            if class_name not in on_disk:
                browser_session.delete_class(class_name)

    def package_for_class(self, browser_session, class_name):
        class_category = browser_session.get_class_definition(class_name)['package_name']
        return self.repository.package_owning_category(class_category) or class_category

    def stored_method_for_selector(self, browser_session, stored, selector):
        matches = [
            method
            for method in stored
            if browser_session.mirrored_selector(method['source']) == selector
        ]
        return matches[0] if matches else None

    def stored_location_for_protocol(self, method_category, package_name):
        if method_category.startswith('*'):
            extension_package = (
                self.repository.package_for_extension_protocol(method_category)
                or method_category[1:]
            )
            return extension_package, True
        return package_name, False

    def compile_stored_in_protocol(
        self, browser_session, class_name, on_class_side, method_category, stored
    ):
        disk_selectors = set()
        for method in stored:
            if method['category'] == method_category:
                selector = browser_session.mirrored_selector(method['source'])
                if selector is not None:
                    browser_session.compile_method(
                        class_name, not on_class_side, method['source'], method['category']
                    )
                    disk_selectors.add(selector)
        return disk_selectors

    def delete_image_methods_outside(
        self, browser_session, class_name, on_class_side, method_category, disk_selectors
    ):
        show_instance_side = not on_class_side
        for selector in browser_session.list_methods(
            class_name, method_category, show_instance_side
        ):
            if selector not in disk_selectors:
                browser_session.delete_method(class_name, selector, show_instance_side)


def load_working_copy():
    '''AI: Build the working copy from the shared config file (read fresh so the IDE and MCP
    server always honour the latest setting, even across processes).'''
    path = sync_config_path()
    if not os.path.exists(path):
        return MonticelloWorkingCopy()
    with open(path, 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)
    root_path = config.get('root_path')
    enabled = config.get('enabled', False)
    repository = MonticelloRepository(root_path) if root_path else None
    return MonticelloWorkingCopy(repository=repository, enabled=enabled)


def save_working_copy(working_copy):
    path = sync_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = {
        'root_path': working_copy.repository.root_path
        if working_copy.repository
        else None,
        'enabled': working_copy.enabled,
    }
    with open(path, 'w', encoding='utf-8') as config_file:
        json.dump(config, config_file)


def current_working_copy():
    return load_working_copy()


def point_working_copy_at(root_path):
    working_copy = MonticelloWorkingCopy(
        repository=MonticelloRepository(root_path), enabled=True
    )
    save_working_copy(working_copy)
    return working_copy


def disable_working_copy():
    working_copy = load_working_copy()
    working_copy.enabled = False
    save_working_copy(working_copy)
    return working_copy
