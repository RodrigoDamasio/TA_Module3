# Sales report generator (Python 2).
import urllib2
import ConfigParser

from utils import format_money


def load_sales(url):
    response = urllib2.urlopen(url)
    return eval(response.read())


def summarize(sales):
    totals = {}
    for region, amount in sales:
        if totals.has_key(region):
            totals[region] += amount
        else:
            totals[region] = amount
    for region, total in totals.iteritems():
        print "%s: %s" % (region, format_money(total))
    return totals


def main():
    config = ConfigParser.ConfigParser()
    config.read("report.ini")
    try:
        sales = load_sales(config.get("source", "url"))
    except urllib2.URLError, e:
        print "Could not load sales:", e
        return
    summarize(sales)


if __name__ == "__main__":
    main()
