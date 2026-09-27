def format_money(value):
    if isinstance(value, int):
        value = float(value)
    return "$%.2f" % value


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
