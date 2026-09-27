# Formatting helpers (Python 2).


def format_money(value):
    if isinstance(value, (int, long)):
        value = float(value)
    return unicode("$%.2f") % value


def chunks(items, size):
    for i in xrange(0, len(items), size):
        yield items[i:i + size]
