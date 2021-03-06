
import os
import re
import six
import sys
import uuid

import prettytable

from hsmclient import exceptions
from hsmclient.openstack.common import strutils


def arg(*args, **kwargs):
    """Decorator for CLI args."""
    def _decorator(func):
        add_arg(func, *args, **kwargs)
        return func
    return _decorator


def env(*vars, **kwargs):
    """
    returns the first environment variable set
    if none are non-empty, defaults to '' or keyword arg default
    """
    for v in vars:
        value = os.environ.get(v, None)
        if value:
            return value
    return kwargs.get('default', '')


def add_arg(f, *args, **kwargs):
    """Bind CLI arguments to a shell.py `do_foo` function."""

    if not hasattr(f, 'arguments'):
        f.arguments = []

    # NOTE(sirp): avoid dups that can occur when the module is shared across
    # tests.
    if (args, kwargs) not in f.arguments:
        # Because of the sematics of decorator composition if we just append
        # to the options list positional options will appear to be backwards.
        f.arguments.insert(0, (args, kwargs))


def add_resource_manager_extra_kwargs_hook(f, hook):
    """Adds hook to bind CLI arguments to ResourceManager calls.

    The `do_foo` calls in shell.py will receive CLI args and then in turn pass
    them through to the ResourceManager. Before passing through the args, the
    hooks registered here will be called, giving us a chance to add extra
    kwargs (taken from the command-line) to what's passed to the
    ResourceManager.
    """
    if not hasattr(f, 'resource_manager_kwargs_hooks'):
        f.resource_manager_kwargs_hooks = []

    names = [h.__name__ for h in f.resource_manager_kwargs_hooks]
    if hook.__name__ not in names:
        f.resource_manager_kwargs_hooks.append(hook)


def get_resource_manager_extra_kwargs(f, args, allow_conflicts=False):
    """Return extra_kwargs by calling resource manager kwargs hooks."""
    hooks = getattr(f, "resource_manager_kwargs_hooks", [])
    extra_kwargs = {}
    for hook in hooks:
        hook_name = hook.__name__
        hook_kwargs = hook(args)

        conflicting_keys = set(hook_kwargs.keys()) & set(extra_kwargs.keys())
        if conflicting_keys and not allow_conflicts:
            raise Exception("Hook '%(hook_name)s' is attempting to redefine"
                            " attributes '%(conflicting_keys)s'" %
                            {'hook_name': hook_name,
                             'conflicting_keys': conflicting_keys})

        extra_kwargs.update(hook_kwargs)

    return extra_kwargs


def unauthenticated(f):
    """
    Adds 'unauthenticated' attribute to decorated function.
    Usage:
        @unauthenticated
        def mymethod(f):
            ...
    """
    f.unauthenticated = True
    return f


def isunauthenticated(f):
    """
    Checks to see if the function is marked as not requiring authentication
    with the @unauthenticated decorator. Returns True if decorator is
    set to True, False otherwise.
    """
    return getattr(f, 'unauthenticated', False)


def service_type(stype):
    """
    Adds 'service_type' attribute to decorated function.
    Usage:
        @service_type('hsm')
        def mymethod(f):
            ...
    """
    def inner(f):
        f.service_type = stype
        return f
    return inner


def get_service_type(f):
    """
    Retrieves service type from function
    """
    return getattr(f, 'service_type', None)


def pretty_choice_list(l):
    return ', '.join("'%s'" % i for i in l)


def _print(pt, order):
    if sys.version_info >= (3, 0):
        print(pt.get_string(sortby=order))
    else:
        print(strutils.safe_encode(pt.get_string(sortby=order)))


def print_list(objs, fields, exclude_unavailable=False, formatters=None,
               sortby_index=0):
    '''Prints a list of objects.

    @param objs: Objects to print
    @param fields: Fields on each object to be printed
    @param exclude_unavailable: Boolean to decide if unavailable fields are
                                removed
    @param formatters: Custom field formatters
    @param sortby_index: Results sorted against the key in the fields list at
                         this index; if None then the object order is not
                         altered
    '''
    formatters = formatters or {}
    mixed_case_fields = ['serverId']
    removed_fields = []
    rows = []

    for o in objs:
        row = []
        for field in fields:
            if field in removed_fields:
                continue
            if field in formatters:
                row.append(formatters[field](o))
            else:
                if field in mixed_case_fields:
                    field_name = field.replace(' ', '_')
                else:
                    field_name = field.lower().replace(' ', '_')
                if isinstance(o, dict) and field in o:
                    data = o[field]
                else:
                    if not hasattr(o, field_name) and exclude_unavailable:
                        removed_fields.append(field)
                        continue
                    else:
                        data = getattr(o, field_name, '')
                if data is None:
                    data = '-'
                if isinstance(data, six.string_types) and "\r" in data:
                    data = data.replace("\r", " ")
                row.append(data)
        rows.append(row)

    for f in removed_fields:
        fields.remove(f)

    pt = prettytable.PrettyTable((f for f in fields), caching=False)
    pt.aligns = ['l' for f in fields]
    for row in rows:
        count = 0
        # Converts unicode values in dictionary to string
        for part in row:
            count = count + 1
            if isinstance(part, dict):
                part = unicode_key_value_to_string(part)
                row[count - 1] = part
        pt.add_row(row)

    if sortby_index is None:
        order_by = None
    else:
        order_by = fields[sortby_index]
    _print(pt, order_by)


def unicode_key_value_to_string(dictionary):
    """Recursively converts dictionary keys to strings."""
    if not isinstance(dictionary, dict):
        return dictionary
    return dict((str(k), str(unicode_key_value_to_string(v)))
                for k, v in dictionary.items())


def print_dict(d, property="Property"):
    pt = prettytable.PrettyTable([property, 'Value'], caching=False)
    pt.aligns = ['l', 'l']
    [pt.add_row(list(r)) for r in six.iteritems(d)]
    _print(pt, property)


def find_resource(manager, name_or_id):
    """Helper for the _find_* methods."""
    # first try to get entity as integer id
    try:
        if isinstance(name_or_id, int) or name_or_id.isdigit():
            return manager.get(int(name_or_id))
    except exceptions.NotFound:
        pass

    # now try to get entity as uuid
    try:
        uuid.UUID(strutils.safe_decode(name_or_id))
        return manager.get(name_or_id)
    except (ValueError, exceptions.NotFound):
        pass

    try:
        try:
            return manager.find(human_id=name_or_id)
        except exceptions.NotFound:
            pass

        # finally try to find entity by name
        try:
            return manager.find(name=name_or_id)
        except exceptions.NotFound:
            try:
                return manager.find(display_name=name_or_id)
            except (UnicodeDecodeError, exceptions.NotFound):
                try:
                    # Volumes does not have name, but display_name
                    return manager.find(display_name=name_or_id)
                except exceptions.NotFound:
                    msg = "No %s with a name or ID of '%s' exists." % \
                        (manager.resource_class.__name__.lower(), name_or_id)
                    raise exceptions.CommandError(msg)
    except exceptions.NoUniqueMatch:
        msg = ("Multiple %s matches found for '%s', use an ID to be more"
               " specific." % (manager.resource_class.__name__.lower(),
                               name_or_id))
        raise exceptions.CommandError(msg)


class HookableMixin(object):
    """Mixin so classes can register and run hooks."""
    _hooks_map = {}

    @classmethod
    def add_hook(cls, hook_type, hook_func):
        if hook_type not in cls._hooks_map:
            cls._hooks_map[hook_type] = []

        cls._hooks_map[hook_type].append(hook_func)

    @classmethod
    def run_hooks(cls, hook_type, *args, **kwargs):
        hook_funcs = cls._hooks_map.get(hook_type) or []
        for hook_func in hook_funcs:
            hook_func(*args, **kwargs)


def safe_issubclass(*args):
    """Like issubclass, but will just return False if not a class."""

    try:
        if issubclass(*args):
            return True
    except TypeError:
        pass

    return False


def import_class(import_str):
    """Returns a class from a string including module and class."""
    mod_str, _sep, class_str = import_str.rpartition('.')
    __import__(mod_str)
    return getattr(sys.modules[mod_str], class_str)

_slugify_strip_re = re.compile(r'[^\w\s-]')
_slugify_hyphenate_re = re.compile(r'[-\s]+')


# http://code.activestate.com/recipes/
#   577257-slugify-make-a-string-usable-in-a-url-or-filename/
def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.

    From Django's "django/template/defaultfilters.py".
    """
    import unicodedata
    if not isinstance(value, unicode):
        value = unicode(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(_slugify_strip_re.sub('', value).strip().lower())
    return _slugify_hyphenate_re.sub('-', value)
