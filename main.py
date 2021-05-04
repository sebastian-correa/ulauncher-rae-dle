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

logger = logging.getLogger(__name__)


class RAE(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

    @staticmethod
    def handle_multiple_defs(soup: BeautifulSoup) -> List[ExtensionResultItem]:
        items = []

        definitions = soup.find("div", {"id": "resultados"}).find_all(
            "p", {"class": "j"}
        )

        for idx, definition in enumerate(definitions):
            abbrs = " ".join(abbr.text for abbr in definition.find_all("abbr"))
            abbrs = f"[{abbrs}]"

            words = ""
            for child in definition.children:
                if child.name not in ("span", "abbr"):
                    if isinstance(child, NavigableString):
                        words += child
                    else:
                        words += child.get_text()
                # words = ' '.join(mark.text for mark in definition.find_all('mark'))
            words = words.strip()

            items.append(
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=f"{idx}",
                    description=words,
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
            items = [
                ExtensionResultItem(
                    icon="images/icon.png",
                    name="Palabra vacía",
                    description="Ingrese una palabra para buscar en el diccionario.",
                    on_enter=HideWindowAction(),
                )
            ]
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
                items = RAE.handle_multiple_defs(soup)

        return RenderResultListAction(items)


if __name__ == "__main__":
    RAE().run()
