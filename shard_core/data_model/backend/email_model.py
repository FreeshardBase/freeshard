# DO NOT MODIFY - copied from freeshard-controller

from jinja2 import Environment
from pydantic import BaseModel


class EmailBlock(BaseModel):
    def render(self, env: Environment) -> str:
        raise NotImplementedError

    def to_plaintext(self) -> str:
        raise NotImplementedError


class ParagraphBlock(EmailBlock):
    text: str
    centered: bool = False
    muted: bool = False

    def render(self, env: Environment) -> str:
        template = env.get_template("paragraph.html")
        return template.render(text=self.text, centered=self.centered, muted=self.muted)

    def to_plaintext(self) -> str:
        return self.text


class ButtonBlock(EmailBlock):
    text: str
    url: str
    fullWidth: bool = False

    def render(self, env: Environment) -> str:
        template = env.get_template("button.html")
        return template.render(text=self.text, url=self.url, fullWidth=self.fullWidth)

    def to_plaintext(self) -> str:
        return f"{self.text}: {self.url}"
