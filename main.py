import logging

import requests
from bs4 import BeautifulSoup
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.event import ItemEnterEvent, KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem

BASE_URL = "https://dle.rae.es"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36"}

logger = logging.getLogger(__name__)


class RAE(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())


class KeywordQueryEventListener(EventListener):
    def on_event(self, event: KeywordQueryEvent, extension) -> RenderResultListAction:
        items = []

        max_suggested_items = extension.preferences["max_suggested_items"]
        logger.debug(f"max_suggested_items={max_suggested_items}")

        word = event.get_argument()
        logger.debug(f"word={word}")

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
                        name=i.text,
                        description="Sugerencia RAE",
                        on_enter=HideWindowAction(),
                    )
                    for i in approx_results[:max_suggested_items]
                ]
            else:
                items = [
                    ExtensionResultItem(
                        icon="images/icon.png",
                        name="NotImplemented",
                        description="NotImplemented",
                        on_enter=HideWindowAction(),
                    )
                ]

        return RenderResultListAction(items)


if __name__ == "__main__":
    RAE().run()
