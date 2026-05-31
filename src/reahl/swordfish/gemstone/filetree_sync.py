'''AI: On-disk Monticello FileTree (Cypress variant) representation of GemStone code.

This module knows the byte-exact layout of a FileTree repository on disk and the rules
by which a class or method maps into one of its packages. It deliberately imports nothing
from GemStone: it works on plain values (class names, selectors, source strings, class
definition dictionaries) so it can be exercised without a live image.

The serialization mirrors MCFileTreeStCypressWriter (the writer Pharo uses), so that files
this module writes are byte-identical to what Pharo would have written. Only files for code
that actually changed are ever written - untouched code keeps Pharo's exact formatting.
'''

import json
import os


# AI: Character -> word table from MCFileTreeStCypressWriter>>initializeSpecials. Used to
# encode binary selectors into filenames that are legal on every filesystem.
CYPRESS_SPECIAL_CHARACTERS = {
    '+': 'plus',
    '-': 'minus',
    '=': 'equals',
    '<': 'less',
    '>': 'more',
    '%': 'percent',
    '&': 'and',
    '|': 'pipe',
    '*': 'star',
    '/': 'slash',
    '\\': 'backslash',
    '~': 'tilde',
    '?': 'wat',
    ',': 'comma',
    '@': 'at',
}


# AI: The .filetree config written for a newly created package - the Cypress, no-method-
# metadata shape every Wonka package on disk uses.
CYPRESS_FILETREE_CONFIG = (
    '{\n'
    '\t"separateMethodMetaAndSource" : false,\n'
    '\t"noMethodMetaData" : true,\n'
    '\t"useCypressPropertiesFile" : true\n'
    '}'
)


# AI: Cypress writes class properties.json keys in this fixed order. Reproducing the order
# exactly is what lets us rewrite a class definition without spuriously reordering keys.
CLASS_PROPERTY_ORDER = [
    'commentStamp',
    'super',
    'category',
    'classinstvars',
    'pools',
    'classvars',
    'instvars',
    'name',
    'type',
]


def mangle_selector(selector):
    '''AI: Map a Smalltalk selector to its Cypress FileTree base filename (without the .st
    extension), following MCFileTreeStCypressWriter class>>fileNameForSelector:.

    Keyword selectors replace every ':' with '.'; unary selectors are used verbatim; binary
    selectors become '^' followed by each character mapped through the specials table and
    joined with '.'.'''
    if ':' in selector:
        return selector.replace(':', '.')
    if selector[0] not in CYPRESS_SPECIAL_CHARACTERS:
        return selector
    encoded = [
        CYPRESS_SPECIAL_CHARACTERS.get(character, character) for character in selector
    ]
    return '^' + '.'.join(encoded)


class MonticelloRepository:
    '''AI: A FileTree repository root: a directory containing one <Name>.package per package.

    The set of packages present on disk is the tracked subset - a class or method that maps
    to a package with no .package directory here is simply not mirrored.'''

    def __init__(self, root_path):
        self.root_path = root_path

    def tracked_package_names(self):
        entries = sorted(os.listdir(self.root_path))
        return [
            entry[: -len('.package')]
            for entry in entries
            if entry.endswith('.package')
            and os.path.isdir(os.path.join(self.root_path, entry))
        ]

    def package_owning_category(self, class_category):
        '''AI: The tracked package that owns a class with the given class-category, matching
        Monticello: an exact category/package-name match, else the longest tracked package
        name of which the category is a hyphen-delimited sub-category. None when untracked.'''
        tracked = self.tracked_package_names()
        if class_category in tracked:
            return class_category
        candidates = [
            name for name in tracked if class_category.startswith(name + '-')
        ]
        return max(candidates, key=len) if candidates else None

    def package_for_extension_protocol(self, protocol):
        '''AI: The tracked package an extension method belongs to, derived from a '*Package'
        method protocol (case-insensitively, as image protocols are not case-canonical).
        None when the protocol is not an extension or names no tracked package.'''
        if not protocol.startswith('*'):
            return None
        wanted = protocol[1:].lower()
        tracked = self.tracked_package_names()
        exact = [name for name in tracked if name.lower() == wanted]
        if exact:
            return exact[0]
        prefix = [name for name in tracked if wanted.startswith(name.lower() + '-')]
        return max(prefix, key=len) if prefix else None

    def package_directory(self, package_name):
        return os.path.join(self.root_path, package_name + '.package')

    def package_exists_on_disk(self, package_name):
        return os.path.isdir(self.package_directory(package_name))

    def ensure_package(self, package_name):
        '''AI: Create a <Package>.package directory (Cypress-configured, with the minimal
        Monticello metadata Pharo expects) when it is not yet on disk, so an explicit file-out
        can introduce a new package. An existing package is left exactly as it is.'''
        package_directory = self.package_directory(package_name)
        if os.path.isdir(package_directory):
            return package_directory
        os.makedirs(package_directory)
        self.write_file(os.path.join(package_directory, '.filetree'), CYPRESS_FILETREE_CONFIG)
        self.write_file(os.path.join(package_directory, 'properties.json'), '{ }')
        meta_directory = os.path.join(package_directory, 'monticello.meta')
        os.makedirs(meta_directory)
        self.write_file(
            os.path.join(meta_directory, 'package'), "(name '%s')" % package_name
        )
        self.write_file(
            os.path.join(meta_directory, 'categories.st'),
            "SystemOrganization addCategory: #'%s'!\n" % package_name,
        )
        return package_directory

    def write_file(self, path, contents):
        with open(path, 'w', encoding='utf-8', newline='\n') as plain_file:
            plain_file.write(contents)

    def defined_class_names(self, package_name):
        '''AI: Names of classes whose definition lives in this package (its .class dirs).'''
        return self.subject_names(package_name, '.class')

    def extension_class_names(self, package_name):
        '''AI: Names of foreign classes this package extends (its .extension dirs).'''
        return self.subject_names(package_name, '.extension')

    def subject_names(self, package_name, suffix):
        package_directory = self.package_directory(package_name)
        if not os.path.isdir(package_directory):
            return []
        entries = sorted(os.listdir(package_directory))
        return [
            entry[: -len(suffix)]
            for entry in entries
            if entry.endswith(suffix)
            and os.path.isdir(os.path.join(package_directory, entry))
        ]

    def read_class_definition(self, package_name, class_name):
        '''AI: The class definition stored on disk, as the same dict shape the writer accepts.'''
        properties_path = os.path.join(
            self.package_directory(package_name), class_name + '.class', 'properties.json'
        )
        if not os.path.exists(properties_path):
            return None
        with open(properties_path, 'r', encoding='utf-8') as properties_file:
            return json.load(properties_file)

    def stored_methods(self, package_name, class_name, is_extension, on_class_side):
        '''AI: Each method stored for a class on a given side: its category line and source,
        read straight from the .st files. The selector is recovered from the source by the
        caller (the method pattern is in the source), so filenames never need demangling.'''
        class_directory_suffix = '.extension' if is_extension else '.class'
        side_directory = 'class' if on_class_side else 'instance'
        methods_directory = os.path.join(
            self.package_directory(package_name),
            class_name + class_directory_suffix,
            side_directory,
        )
        if not os.path.isdir(methods_directory):
            return []
        method_file_names = sorted(
            name for name in os.listdir(methods_directory) if name.endswith('.st')
        )
        return [
            self.split_method_file(os.path.join(methods_directory, name))
            for name in method_file_names
        ]

    def split_method_file(self, path):
        with open(path, 'r', encoding='utf-8', newline='') as method_file:
            content = method_file.read()
        newline_index = content.find('\n')
        category_line = content[:newline_index] if newline_index >= 0 else content
        source = content[newline_index + 1 :] if newline_index >= 0 else ''
        return {'category': category_line, 'source': source}

    def package_uses_cypress_properties(self, package_name):
        '''AI: Whether a package's .filetree config selects the Cypress properties.json writer
        (the format this module reproduces). We only ever rewrite a properties.json for a
        package whose configured format we model, to avoid emitting a format we would get wrong.'''
        config_path = os.path.join(self.package_directory(package_name), '.filetree')
        if not os.path.exists(config_path):
            return False
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
        return config.get('useCypressPropertiesFile', False) is True

    def method_path(
        self, package_name, class_name, on_class_side, is_extension, selector
    ):
        class_directory_suffix = '.extension' if is_extension else '.class'
        side_directory = 'class' if on_class_side else 'instance'
        return os.path.join(
            self.package_directory(package_name),
            class_name + class_directory_suffix,
            side_directory,
            mangle_selector(selector) + '.st',
        )

    def method_file_contents(self, category_line, source):
        '''AI: A method file is the protocol/category on line one, then the method source
        verbatim. No trailing newline, matching how Pharo writes these files.'''
        return category_line + '\n' + source.rstrip('\n')

    def write_method(
        self,
        package_name,
        class_name,
        on_class_side,
        is_extension,
        selector,
        category_line,
        source,
    ):
        path = self.method_path(
            package_name, class_name, on_class_side, is_extension, selector
        )
        new_content = self.method_file_contents(category_line, source)
        if self.method_file_already_current(path, new_content):
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as method_file:
            method_file.write(new_content)
        return path

    def method_file_already_current(self, path, new_content):
        '''AI: True when the file on disk already holds this category line and source, apart from
        a trailing newline (which Pharo keeps and our canonical form drops). Lets an unchanged
        method file be left exactly as Pharo wrote it, so re-filing it produces no whitespace
        diff; any real change to the category or source still differs and is written.'''
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8', newline='') as method_file:
            existing = method_file.read()
        return existing.rstrip('\n') == new_content.rstrip('\n')

    def disk_method_source(
        self, package_name, class_name, on_class_side, is_extension, selector
    ):
        '''AI: The source currently stored on disk for a method (the file content after the
        category line), or None when there is no such file. Used for lazy drift detection.'''
        path = self.method_path(
            package_name, class_name, on_class_side, is_extension, selector
        )
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as method_file:
            content = method_file.read()
        newline_index = content.find('\n')
        return content[newline_index + 1 :] if newline_index >= 0 else ''

    def remove_method(
        self, package_name, class_name, on_class_side, is_extension, selector
    ):
        path = self.method_path(
            package_name, class_name, on_class_side, is_extension, selector
        )
        removed = os.path.exists(path)
        if removed:
            os.remove(path)
        return removed

    def class_properties_json(self, class_definition):
        '''AI: Serialize a class definition into the exact Cypress properties.json bytes:
        tab indentation, ' : ' separators, '[ ]' for empty lists, fixed key order, and no
        trailing newline.'''
        rendered = [
            '\t' + json.dumps(key) + ' : ' + self.render_property_value(class_definition[key])
            for key in CLASS_PROPERTY_ORDER
        ]
        return '{\n' + ',\n'.join(rendered) + '\n}'

    def render_property_value(self, value):
        if isinstance(value, list):
            if not value:
                return '[ ]'
            items = ',\n\t\t'.join(json.dumps(item) for item in value)
            return '[\n\t\t' + items + '\n\t]'
        return json.dumps(value)

    def write_class_definition(self, package_name, class_definition):
        '''AI: Write (or rewrite) a class's properties.json. No empty instance/ or class/ side
        directory is created - those appear lazily when a method is written - matching Pharo,
        which leaves no empty side directory. When the file already exists, the previously stored
        commentStamp is preserved so an instvar/superclass change does not disturb it; and when
        the definition is unchanged the file is left untouched (see class_definition_already_current).'''
        class_directory = os.path.join(
            self.package_directory(package_name), class_definition['name'] + '.class'
        )
        properties_path = os.path.join(class_directory, 'properties.json')
        merged = self.definition_preserving_existing_metadata(
            properties_path, class_definition
        )
        if self.class_definition_already_current(properties_path, merged):
            return properties_path
        # AI: Create only the class directory itself, not empty instance/ and class/ side
        # directories. Pharo creates a side directory only when it holds a method, so an empty
        # one would be a spurious artifact; write_method creates the side it needs lazily.
        os.makedirs(class_directory, exist_ok=True)
        with open(properties_path, 'w', encoding='utf-8', newline='\n') as properties_file:
            properties_file.write(self.class_properties_json(merged))
        return properties_path

    def class_definition_already_current(self, properties_path, merged):
        '''AI: True when the properties.json on disk already records exactly this class
        definition. The comparison is on the parsed JSON, so a difference in indentation
        (Pharo's four-space vs our canonical tabs) or key order does not count as a change -
        only a real change to the definition does. Lets an unchanged, differently-formatted
        file be left untouched rather than reformatted into a spurious diff.'''
        if not os.path.exists(properties_path):
            return False
        with open(properties_path, 'r', encoding='utf-8') as properties_file:
            existing = json.load(properties_file)
        return existing == merged

    def definition_preserving_existing_metadata(self, properties_path, class_definition):
        '''AI: Keep the commentStamp the existing file recorded (the comment did not change),
        and keep its class type unless the caller supplied one - the image gateway cannot
        report the class kind, so an existing 'bytes'/'variable' must not be clobbered to
        'normal'.'''
        merged = dict(class_definition)
        merged.setdefault('commentStamp', '')
        if os.path.exists(properties_path):
            with open(properties_path, 'r', encoding='utf-8') as properties_file:
                existing = json.load(properties_file)
            merged['commentStamp'] = existing.get('commentStamp', merged['commentStamp'])
            if existing.get('type') and merged.get('type', 'normal') == 'normal':
                merged['type'] = existing['type']
        return merged

    def remove_class(self, package_name, class_name):
        class_directory = os.path.join(
            self.package_directory(package_name), class_name + '.class'
        )
        removed = os.path.isdir(class_directory)
        if removed:
            self.remove_directory_tree(class_directory)
        return removed

    def remove_directory_tree(self, directory):
        for entry in os.listdir(directory):
            path = os.path.join(directory, entry)
            self.remove_directory_tree(path) if os.path.isdir(path) else os.remove(path)
        os.rmdir(directory)
