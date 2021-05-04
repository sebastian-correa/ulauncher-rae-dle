import logging
from typing import List

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, ResultSet
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.event import ItemEnterEvent, KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem

BASE_URL = "https://dle.rae.es"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36"
}
CHARACTERS_PER_LINE = 80

logger = logging.getLogger(__name__)

# TODO: Ctrl+C copies definition.
# TODO: Enter goes to the webapge of defined word.
# TODO: Enter updates the search term to the one selected (when approx result).


def chunkize_sentence(sentence: str, max_characters_per_chunk: int) -> List[str]:
    words = sentence.split(" ")
    lines = []

    word_idx, anchor = 1, 0
    while anchor <= len(words):
        partial = " ".join(words[anchor : anchor + word_idx])

        if len(partial) > max_characters_per_chunk:
            lines.append(" ".join(words[anchor : anchor + word_idx - 1]))
            anchor += word_idx - 1
            word_idx = 1
            continue

        if anchor + word_idx == len(words):
            lines.append(partial)
            break
        word_idx += 1
    return lines


class RAE(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

    @staticmethod
    def handle_empty_word() -> List[ExtensionResultItem]:
        return [
            ExtensionResultItem(
                icon="images/icon.png",
                name="Palabra vacía",
                description="Ingrese una palabra para buscar en el diccionario.",
                on_enter=HideWindowAction(),
            )
        ]

    @staticmethod
    def handle_multiple_defs(
        word: str, soup: BeautifulSoup
    ) -> List[ExtensionResultItem]:
        items = []

        resultados = soup.find("div", {"id": "resultados"})
        definitions = resultados.find_all("p", {"class": "j"})

        for definition in definitions:
            abbrs = " ".join(abbr.text for abbr in definition.find_all("abbr"))

            words = ""
            for child in definition.children:
                if child.name not in ("span", "abbr"):
                    if isinstance(child, NavigableString):
                        words += child
                    else:
                        words += child.get_text()
                # words = ' '.join(mark.text for mark in definition.find_all('mark'))
            words = words.strip()
            chunks = chunkize_sentence(words, CHARACTERS_PER_LINE)
            definition_in_lines = "\n".join(chunks)

            items.append(
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=f"{word} [{abbrs}]",
                    description=definition_in_lines,
                    on_enter=HideWindowAction(),
                )
            )
        return items


class KeywordQueryEventListener(EventListener):
    def on_event(self, event: KeywordQueryEvent, extension) -> RenderResultListAction:
        items = []

        max_suggested_items = int(extension.preferences["max_suggested_items"])
        logger.info(f"max_suggested_items={max_suggested_items}")

        word = event.get_argument()
        logger.info(f"word={word}")

        if word is None:
            items = RAE.handle_empty_word()
        else:
            req = requests.get(f"{BASE_URL}/{word}", headers=HEADERS)
            soup = BeautifulSoup(req.text, "html.parser")

            approx_results = soup.find_all("a", {"data-acc": "LISTA APROX"})
            if len(approx_results) != 0:
                # Case with no exact match. Items are suggestions.
                items = [
                    ExtensionResultItem(
                        icon="images/icon.png",
                        name=i.text,  # TODO: This leaves the superscript characters.
                        description="Sugerencia RAE",
                        on_enter=HideWindowAction(),
                    )
                    for i in approx_results[:max_suggested_items]
                ]
                # TODO: On ENTER, replace word in ulauncher with the one selected.
            else:
                # Case with exact match.
                items = RAE.handle_multiple_defs(word, soup)

        return RenderResultListAction(items)


if __name__ == "__main__":
    RAE().run()
