from typing import Dict, List
from bs4.element import NavigableString
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

import json


def get_all_word_data(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """All found definitions as strings.

        Args:
            soup (BeautifulSoup): Whole page soup.
            word (str): Word to which the definitions belong.

        Returns:
            List[str]: All definitions to be saved.
        """
    items = []

    definitions = soup.find_all("p", {"class": "j"})

    for definition in definitions:
        abbrs = " ".join(abbr.text for abbr in definition.find_all("abbr"))

        # This is done this weird way cause they put words inside <mark> tags but whitespaces and puntcuations outside of them.
        words = ""
        for child in definition.children:
            if child.name not in {"span", "abbr"}:
                if isinstance(child, NavigableString):
                    words += child
                else:
                    words += child.get_text()
        words = words.strip()

        items.append(
            {"abbrs": abbrs, "definition": words, "html_code": definition["id"],}
        )
    return items


def get_top_words() -> List[str]:
    req = requests.get(
        "https://es.wiktionary.org/wiki/Ap%C3%A9ndice:1000_palabras_b%C3%A1sicas_en_espa%C3%B1ol"
    )
    soup = BeautifulSoup(req.text, "html.parser")

    top_words = []
    for item in soup.find("div", {"class": "mw-parser-output"}).children:
        if item.name != "ul":
            continue

        for entry in item.find_all("li"):
            # Handle synonyms.
            top_words.extend([word.text for word in entry.find_all("a")])
    return top_words


def get_all_words_data(words: List[str]) -> Dict[str, Dict[str, str]]:
    entries = dict()

    for idx, word in enumerate(words, start=1):
        if idx % 10 == 0:
            print("saving")
            entries["last_checked"] = datetime.now().timestamp()
            save_datas(entries, f"top_words/entry_{entries['last_checked']}.json")
            print("waiting")
            time.sleep(5)

        print(idx, word)
        req = requests.get(f"https://dle.rae.es/{word}")

        if not req.ok:
            entries["last_checked"] = datetime.now().timestamp()
            save_datas(
                entries, f"top_words/temp/entry_{datetime.now().timestamp()}.json"
            )
            print("crashing")
            break

        soup = BeautifulSoup(req.text, "html.parser")
        word_datas = get_all_word_data(soup)

        entries |= {word: word_datas}
    return entries


def save_datas(datas, path):
    with open(path, "w") as f:
        json.dump(datas, f, indent=4)


top_words = get_top_words()
all_datas = get_all_words_data(top_words)
all_datas["last_checked"] = datetime.now().timestamp()
save_datas(all_datas, "top_words/top_1k_spanish_words.json")

# save_word_list("top_words/top_1k_spanish_words.json")

