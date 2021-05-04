import json
import logging
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, ResultSet
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.event import (
    KeywordQueryEvent,
    PreferencesEvent,
    PreferencesUpdateEvent,
)
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem

BASE_URL = "https://dle.rae.es"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36"
}
CHARACTERS_PER_LINE = 80
NUMERIC_PREFERENCES = {"max_suggested_items", "max_shown_definitions"}

p = (
    Path.home()
    / ".local"
    / "share"
    / "ulauncher"
    / "extensions"
    / "rae"
    / "manifest.json"
)
with p.open("r") as f:
    DEFAULT_MANIFEST = json.load(f)
DEFAULT_PREFERENCES = {
    x["id"]: x["default_value"] for x in DEFAULT_MANIFEST["preferences"]
}

logger = logging.getLogger(__name__)

# TODO: Check "saber"


def chunkize_sentence(sentence: str, max_characters_per_chunk: int) -> List[str]:
    """Splits a given sentence into chunks of at most max_characters_per_chunk, counting spaces.

    The method guarantees that each element of the output is an intelligible sentence with whole words.

    This is not the same as splitting into max_characters_per_chunk, because words could end up truncated.

    Args:
        sentence (str): Sentence to be split.
        max_characters_per_chunk (int): Maximum number of characters allower per chunk, spaces included. Chunks could end up being significantly shorter, depending on the length of words.

    Returns:
        List[str]: List of chunks (i.e: lines) with length at most max_characters_per_chunk.
    """
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
        self.subscribe(
            KeywordQueryEvent, KeywordQueryEventListener()
        )  # Handle user input via ulauncher.
        self.subscribe(
            PreferencesUpdateEvent, PreferencesUpdateListener()
        )  # Handle preferences update via UI.
        self.subscribe(
            PreferencesEvent, PreferencesEventListener()
        )  # To force reset toggle to be off by default.

    @staticmethod
    def handle_empty_word() -> List[ExtensionResultItem]:
        """Returns the elements to display when an empty word is given to the extension.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        return [
            ExtensionResultItem(
                icon="images/icon.png",
                name="Palabra vacía",
                description="Ingrese una palabra para buscar en el diccionario.",
                on_enter=HideWindowAction(),
            )
        ]

    @staticmethod
    def handle_approx_results(
        soup: BeautifulSoup, max_suggested_items: int, extension: Extension
    ) -> List[ExtensionResultItem]:
        """All elements to be displayed by the extension when an approximate result is found (i.e.: no exact match for given word is found).

        Args:
            soup (BeautifulSoup): Whole page soup.
            max_suggested_items (int): Show, at most, this many of the approximated results in approx_results.
            extension (Extension): The Extension.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        # approx_results = soup.find_all("a", {"data-acc": "LISTA APROX"})
        # Example result:
        #     <div class="n1"><a data-acc="LISTA APROX" data-cat="FETCH" data-eti="ad" href="/ad" title="Ir a la entrada">ad</a> (ad)</div>
        approx_results = (
            soup.find("div", {"id": "resultados"})
            .find("article")
            .find_all("div", {"class": "n1"})
        )
        print(approx_results)
        if len(approx_results) == 0:
            raise RuntimeError(
                "Attempted to handle the approx result case, but the soup doesn't have any <a> tags with 'data-acc'=='LISTA APROX'."
            )

        seen = set()
        items = []
        for i in approx_results[:max_suggested_items]:
            # Done this weird way because i.text would leave the <sup> tag as plaintext.
            # The structure of these <a> tags is, for example:
            #     <a data-acc="LISTA APROX" data-cat="FETCH" data-eti="saber" href="/saber" title="Ir a la entrada">saber<sup>1</sup></a>
            # So children is always [word_of_interest, sup tag] or just [word_of_interest].
            # Of note, the children is a NavigatableString which ulauncher doesn't like.
            a, infinitive = i.children
            display_name = str(next(a.children))

            # Guarantee list of approx suggestions shows unique results.
            # On the web, the results are duplicated cause they link to different sections of the webpage, but the webpage is the same.
            # Ergo, it doesn't add information to show the entries more than once.
            if display_name in seen:
                continue
            else:
                seen.add(display_name)

            # https://github.com/Ulauncher/Ulauncher/blob/dev/ulauncher/api/shared/action/SetUserQueryAction.py
            new_query = f"{extension.preferences['kw']} {display_name}"

            items.append(
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=f"{display_name} ꞏ {infinitive.strip()}",
                    description="Sugerencia RAE",
                    on_enter=SetUserQueryAction(new_query),
                )
            )
        return items

    @staticmethod
    def handle_multiple_defs(
        soup: BeautifulSoup, max_shown_definitions: int, word: str
    ) -> List[ExtensionResultItem]:
        """All elements to be displayed by the extension when an exact definition is found.

        Args:
            soup (BeautifulSoup): Whole page soup.
            max_shown_definitions (int): Show, at most, this many of the definitions in soup.
            word (str): Word to which the definitions belong.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        items = []

        definitions = soup.find_all("p", {"class": "j"})
        if len(definitions) == 0:
            raise RuntimeError(
                "The provided soup has no <p> tags with 'class'=='j'"
            )  # ? Should I return an empty ExtensionResultItem() ?

        for definition in definitions[:max_shown_definitions]:
            abbrs = " ".join(abbr.text for abbr in definition.find_all("abbr"))

            words = ""
            for child in definition.children:
                if child.name not in {"span", "abbr"}:
                    if isinstance(child, NavigableString):
                        words += child
                    else:
                        words += child.get_text()
                # words = ' '.join(mark.text for mark in definition.find_all('mark'))
            words = words.strip()
            chunks = chunkize_sentence(words, CHARACTERS_PER_LINE)
            definition_in_lines = "\n".join(chunks)

            code = definition["id"]

            items.append(
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=f"{word} [{abbrs}]",
                    description=definition_in_lines,
                    on_enter=CopyToClipboardAction(
                        words
                    ),  # https://github.com/Ulauncher/Ulauncher/blob/dev/ulauncher/api/shared/action/CopyToClipboardAction.py
                    on_alt_enter=OpenUrlAction(
                        f"{BASE_URL}/{word}#{code}"
                    ),  # https://github.com/Ulauncher/Ulauncher/blob/dev/ulauncher/api/shared/action/OpenUrlAction.py
                )
            )
        return items


class KeywordQueryEventListener(EventListener):
    def on_event(
        self, event: KeywordQueryEvent, extension: Extension
    ) -> RenderResultListAction:
        """Handle the user calling the extension via ulauncher.

        Args:
            event (KeywordQueryEvent): The KeywordQueryEvent generated by the user (docs.ulauncher.io/en/latest/extensions/events.html?highlight=KeywordQueryEvent).
            extension (Extension): The Extension.

        Returns:
            RenderResultListAction: Results ready to be displayed by ulauncher.
        """
        items = []

        max_suggested_items = int(extension.preferences["max_suggested_items"])
        max_shown_definitions = int(extension.preferences["max_shown_definitions"])

        logger.info(f"max_suggested_items={max_suggested_items}")
        logger.info(f"max_shown_definitions={max_shown_definitions}")

        word = event.get_argument()
        logger.info(f"word={word}")

        if word is None:
            items = RAE.handle_empty_word()
        else:
            req = requests.get(f"{BASE_URL}/{word}", headers=HEADERS)
            soup = BeautifulSoup(req.text, "html.parser")

            try:
                # Case with no exact match. Items are suggestions.
                items = RAE.handle_approx_results(soup, max_suggested_items, extension)
                # TODO: Handle case with no dfinition at all
            except RuntimeError:
                # Case with exact match.
                items = RAE.handle_multiple_defs(soup, max_shown_definitions, word)
        return RenderResultListAction(items)


class PreferencesEventListener(EventListener):
    def on_event(self, event: PreferencesEvent, extension: Extension):
        """Set this session's preferences to those of the last session, except for the reset toggle, which is reset to the default.

        Args:
            event (PreferencesEvent): The PreferencesEvent triggered once when the application starts (docs.ulauncher.io/en/latest/extensions/events.html?highlight=PreferencesEvent#preferencesevent).
            extension (Extension): The Extension.
        """
        extension.preferences.update(event.preferences)
        extension.preferences["reset_to_default"] = "-"
        # FIXME: Doesn't set to '-'.


class PreferencesUpdateListener(EventListener):
    def on_event(self, event: PreferencesUpdateEvent, extension: Extension):
        """Update extension preferences when the user saves new ones from the UI.

        Args:
            event (PreferencesUpdateEvent): The PreferencesUpdateEvent triggered when the user clicks SAVE in the Extension preference's page (docs.ulauncher.io/en/latest/extensions/events.html?highlight=PreferencesUpdateEvent#preferencesupdateevent).
            extension (Extension): The extension.
        """
        if event.id in NUMERIC_PREFERENCES:
            if float(event.new_value).is_integer():
                # Don't do the typical try/catch cause 4.2 (not "4.2") would be truncated to 4 and silently change the value to 4, instead of throwing an error.
                extension.preferences[event.id] = int(event.new_value)
                logger.info(
                    f"{event.id} changed from {event.old_value} to {event.new_value}."
                )
            else:
                extension.preferences[event.id] = int(event.old_value)
                logger.info(
                    f"{event.id} failed to change. Reverting to previous value of {event.old_value}. Given: {event.new_value}. Try an integer."
                )
        elif event.id == "reset_to_default" and event.new_value == "Reset":
            for id_, val in DEFAULT_PREFERENCES.items():
                old_val = extension.preferences[id_]
                extension.preferences[id_] = val
                logger.info(
                    f"{id_} was reset from {old_val} to its default value of {val}."
                )
        else:
            extension.preferences[event.id] = event.new_value
            logger.info(
                f"{event.id} changed from {event.old_value} to {event.new_value}."
            )


if __name__ == "__main__":
    RAE().run()
