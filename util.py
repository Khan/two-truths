import functools


_not_found = object()


def memo(f):
    d = {}
    @functools.wraps(f)
    def wrapped(*args):
        retval = d.get(args, _not_found)
        if retval is _not_found:
            retval = d[args] = f(*args)
        return retval
    return wrapped
