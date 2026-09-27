import ast
import configparser
import urllib.error
import urllib.request

from utils import format_money


def load_sales(url):
    with urllib.request.urlopen(url) as response:
        return ast.literal_eval(response.read().decode())


def summarize(sales):
    totals = {}
    for region, amount in sales:
        totals[region] = totals.get(region, 0) + amount
    for region, total in totals.items():
        print(f"{region}: {format_money(total)}")
    return totals


def main():
    config = configparser.ConfigParser()
    config.read("report.ini")
    try:
        sales = load_sales(config.get("source", "url"))
    except urllib.error.URLError as e:
        print("Could not load sales:", e)
        return
    summarize(sales)


if __name__ == "__main__":
    main()
